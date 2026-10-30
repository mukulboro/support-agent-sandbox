"""Runs the golden set against the agents, scores every turn and writes traces.

    uv run python -m evals.run --label baseline
    uv run python -m evals.run --label try2 --only acct-overdue-bills,fail-invoices-500 --repeats 2
"""
import argparse
import json
import re
import statistics
import time
from pathlib import Path

from app.agents.agents import DynamicAgent, StaticAgent, load_api_tools
from app.config import get_settings
from app.mock_api.mock_api import mock_request
from app.rag.ingestor import StaticKnowledgeIngester
from app.rag.retriever import Retriever
from app.repository.vector import VectorStore
from app.tools.convo_manager import ConversationManager
from app.tools.embed import Embedder
from app.tools.llm import LLM
from app.tools.tools import ToolDispatcher
from evals.faults import FaultyAPI

HERE = Path(__file__).parent
PRICE_PER_MILLION = {"gpt-5-nano": (0.05, 0.40)}  # (input, output) USD, list-price estimate from third-party trackers


def normalise(text: str) -> str:
    """Lower case and straighten curly quotes: the model writes "couldn’t", the expectations say "couldn't"."""
    return text.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')


def matches(item: str, text: str, phrases: dict) -> bool:
    """One thing the answer must contain: plain text, a regex ('re:...') or a named phrase list ('ref:...')."""
    text = normalise(text)
    if item.startswith("ref:"):
        return any(normalise(p) in text for p in phrases[item[4:]])
    if item.startswith("re:"):
        return re.search(item[3:], text, re.IGNORECASE) is not None
    return normalise(item) in text


def check(result: dict, expect: dict, phrases: dict) -> list[str]:
    """Returns the list of failed checks; empty means the turn passed."""
    failures = []
    answer = result["answer"]
    if result.get("error"):
        failures.append(f"agent error: {result['error']}")

    for item in expect.get("include", []):
        options = item if isinstance(item, list) else [item]
        if not any(matches(o, answer, phrases) for o in options):
            failures.append(f"missing: {options}")
    for item in expect.get("exclude", []):
        if matches(item, answer, phrases):
            failures.append(f"should not contain: {item}")

    sources = result["sources"]
    if expect.get("no_sources") and sources:
        failures.append(f"expected no sources, got {sources}")
    if "sources_any" in expect and not any(w.lower() in s.lower() for w in expect["sources_any"] for s in sources):
        failures.append(f"no source matched {expect['sources_any']}, got {sources}")

    called = [c["tool"] for c in result.get("tool_calls", [])]
    for tool in expect.get("tools", []):
        if tool not in called:
            failures.append(f"tool not called: {tool}")
    if "max_tool_calls" in expect and len(called) > expect["max_tool_calls"]:
        failures.append(f"{len(called)} tool calls, expected at most {expect['max_tool_calls']}")
    return failures


def build_agents(llm: LLM):
    settings = get_settings()
    embedder = Embedder(settings.openai_api_key, settings.embed_model)
    store = VectorStore("", "evals", settings.embed_dimension)  # in-memory Qdrant, nothing to clean up
    ingester = StaticKnowledgeIngester(settings.guide_path, embedder, store, settings.chunk_size)
    ingester.ingest()
    static = StaticAgent(llm, Retriever(embedder, store, ingester))

    def dynamic_for(inject: dict) -> DynamicAgent:
        dispatcher = ToolDispatcher(FaultyAPI(mock_request, inject), load_api_tools())
        return DynamicAgent(llm, dispatcher, settings.today, settings.max_tool_rounds)

    return static, dynamic_for


def run_case(case: dict, llm: LLM, static: StaticAgent, dynamic_for, phrases: dict) -> list[dict]:
    """Plays the turns of one case in fresh conversations and returns one trace per turn."""
    convos = ConversationManager()
    ids: dict[str, str] = {}
    dynamic = dynamic_for(case.get("inject", {}))
    traces = []

    for number, turn in enumerate(case["turns"], start=1):
        name = turn.get("convo", "main")
        if name not in ids:
            ids[name] = convos.begin()
        agent_name = turn.get("agent", case["agent"])
        agent = static if agent_name == "static" else dynamic

        before = dict(llm.usage)
        start = time.time()
        try:
            result = agent.answer(turn["user"], convos.history(ids[name]))
        except Exception as error:  # a crash is a failed turn, not a failed run
            result = {"answer": "", "sources": [], "error": repr(error)}
        latency = time.time() - start
        convos.add_turn(ids[name], turn["user"], agent_name, result)

        failures = check(result, turn["expect"], phrases)
        traces.append({
            "case": case["id"], "category": case["category"], "turn": number, "agent": agent_name,
            "user": turn["user"], "answer": result["answer"], "sources": result["sources"],
            "tool_calls": result.get("tool_calls", []), "error": result.get("error"),
            "failures": failures, "passed": not failures, "latency_s": round(latency, 2),
            "llm_calls": llm.usage["calls"] - before["calls"],
            "prompt_tokens": llm.usage["prompt_tokens"] - before["prompt_tokens"],
            "completion_tokens": llm.usage["completion_tokens"] - before["completion_tokens"],
        })
    return traces


def summarise(traces: list[dict], model: str) -> dict:
    cases: dict[str, list[dict]] = {}
    for t in traces:
        cases.setdefault(t["case"], []).append(t)
    passed = {cid: all(t["passed"] for t in turns) for cid, turns in cases.items()}

    by_category: dict[str, list[bool]] = {}
    for cid, turns in cases.items():
        by_category.setdefault(turns[0]["category"], []).append(passed[cid])

    latencies = sorted(t["latency_s"] for t in traces)
    prompt = sum(t["prompt_tokens"] for t in traces)
    completion = sum(t["completion_tokens"] for t in traces)
    price_in, price_out = PRICE_PER_MILLION.get(model, (0, 0))
    return {
        "model": model,
        "cases": len(cases),
        "passed": sum(passed.values()),
        "pass_rate": round(sum(passed.values()) / len(cases), 3),
        "by_category": {c: f"{sum(v)}/{len(v)}" for c, v in sorted(by_category.items())},
        "case_results": passed,
        "latency_median_s": statistics.median(latencies),
        "latency_p95_s": latencies[int(0.95 * (len(latencies) - 1))],
        "llm_calls": sum(t["llm_calls"] for t in traces),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "est_cost_usd": round(prompt / 1e6 * price_in + completion / 1e6 * price_out, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="name of this run, results go to evals/runs/<label>/")
    parser.add_argument("--only", help="comma separated case ids")
    parser.add_argument("--category", help="run only this category")
    parser.add_argument("--repeats", type=int, default=1, help="run every case this many times")
    args = parser.parse_args()

    golden = json.loads((HERE / "golden_set.json").read_text(encoding="utf-8"))
    cases = golden["cases"]
    if args.only:
        cases = [c for c in cases if c["id"] in args.only.split(",")]
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]

    settings = get_settings()
    llm = LLM(settings.openai_api_key, settings.llm_model, settings.llm_retries,
              settings.llm_reasoning_first, settings.llm_reasoning_retry)
    static, dynamic_for = build_agents(llm)

    out = HERE / "runs" / args.label
    out.mkdir(parents=True, exist_ok=True)
    traces = []
    for repeat in range(1, args.repeats + 1):
        for case in cases:
            case_traces = run_case(case, llm, static, dynamic_for, golden["phrases"])
            for t in case_traces:
                t["repeat"] = repeat
            traces += case_traces
            ok = all(t["passed"] for t in case_traces)
            print(f"{'PASS' if ok else 'FAIL'}  {case['id']}", flush=True)
            for t in case_traces:
                for failure in t["failures"]:
                    print(f"        turn {t['turn']}: {failure}", flush=True)

    (out / "traces.jsonl").write_text("\n".join(json.dumps(t) for t in traces) + "\n", encoding="utf-8")
    summary = summarise(traces, settings.llm_model)
    summary["label"] = args.label
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{summary['passed']}/{summary['cases']} cases passed ({summary['pass_rate']:.0%})")
    print("by category:", summary["by_category"])
    print(f"latency median {summary['latency_median_s']}s, p95 {summary['latency_p95_s']}s | "
          f"{summary['llm_calls']} llm calls, {summary['prompt_tokens']} in / {summary['completion_tokens']} out tokens, "
          f"about ${summary['est_cost_usd']}")
    print(f"traces: {out / 'traces.jsonl'}")


if __name__ == "__main__":
    main()
