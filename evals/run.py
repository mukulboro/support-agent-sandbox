"""Runs the golden set against the agents, scores every turn and writes traces.

    uv run python -m evals.run --label baseline
    uv run python -m evals.run --label try2 --only acct-overdue-bills,fail-invoices-500 --repeats 2
    uv run python -m evals.run --label routing --category routing --repeats 3

Most cases call one agent directly (the `agent` field). Cases with "mode": "routed" go through the whole
ChatService (router, then agents) and are also scored on the route taken and the conversation status.
"""
import argparse
import json
import re
import statistics
import time
from pathlib import Path

from app.agents.agents import DynamicAgent, RouterAgent, StaticAgent, load_api_tools
from app.config import get_settings
from app.http.services import ChatService
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
# (input, output) USD per million tokens. Estimates from third-party price trackers, not billed amounts.
PRICE_PER_MILLION = {"gpt-5-nano": (0.05, 0.40), "gpt-5-mini": (0.25, 2.00)}


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

    # only routed cases have these
    if "route" in expect and result.get("route") != expect["route"]:
        failures.append(f"route was {result.get('route')!r}, expected {expect['route']!r}")
    if "status" in expect and result.get("status") != expect["status"]:
        failures.append(f"status was {result.get('status')!r}, expected {expect['status']!r}")
    for word in expect.get("rewrite_include", []):
        if not any(normalise(word) in normalise(q["query"]) for q in result.get("queries", [])):
            failures.append(f"no routed query mentions {word!r}, got {[q['query'] for q in result.get('queries', [])]}")
    return failures


def build_agents(llm: LLM, router_llm: LLM):
    settings = get_settings()
    embedder = Embedder(settings.openai_api_key, settings.embed_model)
    store = VectorStore("", "evals", settings.embed_dimension)  # in-memory Qdrant, nothing to clean up
    ingester = StaticKnowledgeIngester(settings.guide_path, embedder, store, settings.chunk_size)
    ingester.ingest()
    retriever = Retriever(
        embedder, store, ingester, settings.chunks_to_fetch, settings.sections_to_return, settings.max_section_chars
    )
    static = StaticAgent(llm, retriever)

    def dynamic_for(inject: dict) -> DynamicAgent:
        dispatcher = ToolDispatcher(FaultyAPI(mock_request, inject), load_api_tools())
        return DynamicAgent(llm, dispatcher, settings.today, settings.max_tool_rounds)

    def service_for(inject: dict) -> ChatService:
        """The real chat path (router, agents, conversations) without the auditor."""
        agents = {"static": static, "dynamic": dynamic_for(inject)}
        return ChatService(RouterAgent(router_llm), agents, ConversationManager())

    return static, dynamic_for, service_for


def play_routed(service: ChatService, convo_id: str, user: str) -> dict:
    data = service.send(convo_id, user)
    return {
        "answer": data["reply"].split("\n\nSources:\n")[0],  # the check should not match the appended source list
        "sources": data["sources"], "tool_calls": data["tool_calls"],
        "route": data["route"], "status": data["status"], "queries": data["queries"],
    }


def run_case(case: dict, llm: LLM, router_llm: LLM, static: StaticAgent, dynamic_for, service_for, phrases: dict) -> list[dict]:
    """Plays the turns of one case in fresh conversations and returns one trace per turn."""
    routed = case.get("mode") == "routed"
    if routed:
        service = service_for(case.get("inject", {}))
    else:
        convos = ConversationManager()
        dynamic = dynamic_for(case.get("inject", {}))
    ids: dict[str, str] = {}
    traces = []

    for number, turn in enumerate(case["turns"], start=1):
        name = turn.get("convo", "main")
        if name not in ids:
            ids[name] = service.begin() if routed else convos.begin()

        before, router_before = dict(llm.usage), dict(router_llm.usage)
        start = time.time()
        try:
            if routed:
                result = play_routed(service, ids[name], turn["user"])
                agent_name = result["route"]
            else:
                agent_name = turn.get("agent", case["agent"])
                agent = static if agent_name == "static" else dynamic
                result = agent.answer(turn["user"], convos.history(ids[name]))
        except Exception as error:  # a crash is a failed turn, not a failed run
            result = {"answer": "", "sources": [], "error": repr(error)}
            agent_name = "error"
        latency = time.time() - start
        if not routed:
            convos.add_turn(ids[name], turn["user"], agent_name, result)

        failures = check(result, turn["expect"], phrases)
        traces.append({
            "case": case["id"], "category": case["category"], "turn": number, "agent": agent_name,
            "user": turn["user"], "answer": result["answer"], "sources": result["sources"],
            "tool_calls": result.get("tool_calls", []), "error": result.get("error"),
            "route": result.get("route"), "status": result.get("status"), "queries": result.get("queries"),
            "failures": failures, "passed": not failures, "latency_s": round(latency, 2),
            "llm_calls": llm.usage["calls"] - before["calls"] + router_llm.usage["calls"] - router_before["calls"],
            "prompt_tokens": llm.usage["prompt_tokens"] - before["prompt_tokens"],
            "completion_tokens": llm.usage["completion_tokens"] - before["completion_tokens"],
            "router_prompt_tokens": router_llm.usage["prompt_tokens"] - router_before["prompt_tokens"],
            "router_completion_tokens": router_llm.usage["completion_tokens"] - router_before["completion_tokens"],
        })
    return traces


def summarise(traces: list[dict], model: str, router_model: str = "") -> dict:
    cases: dict[str, list[dict]] = {}
    for t in traces:
        cases.setdefault(t["case"], []).append(t)
    passed = {cid: all(t["passed"] for t in turns) for cid, turns in cases.items()}  # every turn of every repeat

    by_category: dict[str, list[bool]] = {}
    for cid, turns in cases.items():
        by_category.setdefault(turns[0]["category"], []).append(passed[cid])

    # one "run" is one case played once; with repeats a case can pass some runs and fail others (flaky)
    runs: dict[tuple, list[bool]] = {}
    for t in traces:
        runs.setdefault((t["case"], t.get("repeat", 1)), []).append(t["passed"])
    outcomes: dict[str, list[bool]] = {}
    for (cid, _), turns in runs.items():
        outcomes.setdefault(cid, []).append(all(turns))
    flaky = sorted(cid for cid, o in outcomes.items() if any(o) and not all(o))

    latencies = sorted(t["latency_s"] for t in traces)
    prompt = sum(t["prompt_tokens"] for t in traces)
    completion = sum(t["completion_tokens"] for t in traces)
    router_prompt = sum(t.get("router_prompt_tokens", 0) for t in traces)
    router_completion = sum(t.get("router_completion_tokens", 0) for t in traces)
    price_in, price_out = PRICE_PER_MILLION.get(model, (0, 0))
    router_in, router_out = PRICE_PER_MILLION.get(router_model, (0, 0))
    return {
        "model": model,
        "router_model": router_model,
        "cases": len(cases),
        "passed": sum(passed.values()),
        "pass_rate": round(sum(passed.values()) / len(cases), 3),
        "runs": len(runs),
        "runs_passed": sum(all(turns) for turns in runs.values()),
        "flaky": flaky,
        "by_category": {c: f"{sum(v)}/{len(v)}" for c, v in sorted(by_category.items())},
        "case_results": passed,
        "latency_median_s": statistics.median(latencies),
        "latency_p95_s": latencies[int(0.95 * (len(latencies) - 1))],
        "llm_calls": sum(t["llm_calls"] for t in traces),
        "prompt_tokens": prompt + router_prompt,
        "completion_tokens": completion + router_completion,
        "est_cost_usd": round(
            prompt / 1e6 * price_in + completion / 1e6 * price_out
            + router_prompt / 1e6 * router_in + router_completion / 1e6 * router_out, 4),
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
    router_llm = LLM(settings.openai_api_key, settings.router_model, settings.llm_retries,
                     settings.router_reasoning_first, settings.router_reasoning_retry)
    static, dynamic_for, service_for = build_agents(llm, router_llm)

    out = HERE / "runs" / args.label
    out.mkdir(parents=True, exist_ok=True)
    traces = []
    for repeat in range(1, args.repeats + 1):
        for case in cases:
            case_traces = run_case(case, llm, router_llm, static, dynamic_for, service_for, golden["phrases"])
            for t in case_traces:
                t["repeat"] = repeat
            traces += case_traces
            ok = all(t["passed"] for t in case_traces)
            print(f"{'PASS' if ok else 'FAIL'}  {case['id']}" + (f"  (repeat {repeat})" if args.repeats > 1 else ""), flush=True)
            for t in case_traces:
                for failure in t["failures"]:
                    print(f"        turn {t['turn']}: {failure}", flush=True)

    (out / "traces.jsonl").write_text("\n".join(json.dumps(t) for t in traces) + "\n", encoding="utf-8")
    summary = summarise(traces, settings.llm_model, settings.router_model)
    summary["label"] = args.label
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{summary['passed']}/{summary['cases']} cases passed in every repeat ({summary['pass_rate']:.0%})")
    print(f"{summary['runs_passed']}/{summary['runs']} individual runs passed" + (f", flaky: {summary['flaky']}" if summary["flaky"] else ""))
    print("by category:", summary["by_category"])
    print(f"latency median {summary['latency_median_s']}s, p95 {summary['latency_p95_s']}s | "
          f"{summary['llm_calls']} llm calls, {summary['prompt_tokens']} in / {summary['completion_tokens']} out tokens, "
          f"about ${summary['est_cost_usd']}")
    print(f"traces: {out / 'traces.jsonl'}")


if __name__ == "__main__":
    main()
