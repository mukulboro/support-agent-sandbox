"""Measures how long the server takes to answer, over HTTP, for each kind of question and under parallel load.

    uv run python -m evals.latency --url http://localhost:9090 --label docker
    uv run python -m evals.latency --repeats 8 --concurrency 4,8

Every timed question runs in a fresh conversation, so the history is the same size each time. Results are printed and
written to evals/runs/latency-<label>/summary.json together with the raw samples. Conversations are not deleted
afterwards, so the auditor does not add its own LLM calls to the measurement (the "end" scenario ends itself, which
does trigger one audit per repeat).
"""
import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

HERE = Path(__file__).parent

# name, messages sent in one fresh conversation. Only the last message is timed; earlier ones just build up history.
SCENARIOS = [
    ("docs question", ["How do I add a vendor?"]),
    ("docs follow-up (2nd turn)", ["How do I add a vendor?", "and for a bill instead?"]),
    ("data, one tool call", ["How many vendors do we have?"]),
    ("data, two tool calls", ["Why hasn't Halberd Components been paid yet?"]),
    ("docs and data together", ["How do I add a vendor, and how many vendors do we have?"]),
    ("unsupported request", ["What's our current wallet balance?"]),
    ("end of conversation", ["Thanks, that's all I needed."]),
]
LOAD_QUESTION = ["Why hasn't Halberd Components been paid yet?"]


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


def timed_turn(client: httpx.Client, messages: list[str]) -> dict:
    convo_id = client.post("/conversations").json()["conversation_id"]
    for message in messages[:-1]:
        client.post(f"/conversations/{convo_id}/messages", json={"message": message})
    start = time.perf_counter()
    response = client.post(f"/conversations/{convo_id}/messages", json={"message": messages[-1]})
    seconds = time.perf_counter() - start
    data = response.json() if response.status_code == 200 else {}
    timings = data.get("timings_ms", {})
    return {
        "seconds": seconds, "http_status": response.status_code, "route": data.get("route"),
        "router_ms": timings.get("router"), "agents_ms": timings.get("agents"), "total_ms": timings.get("total"),
        "tool_calls": len(data.get("tool_calls", [])),
    }


def run_scenarios(url: str, repeats: int) -> list[dict]:
    rows = []
    with httpx.Client(base_url=url, timeout=180) as client:
        for name, messages in SCENARIOS:
            samples = [timed_turn(client, messages) for _ in range(repeats)]
            seconds = [s["seconds"] for s in samples]
            rows.append({
                "scenario": name,
                "n": len(samples),
                "errors": sum(s["http_status"] != 200 or s["route"] == "error" for s in samples),
                "median_s": round(statistics.median(seconds), 2),
                "p95_s": round(percentile(seconds, 0.95), 2),
                "max_s": round(max(seconds), 2),
                "router_median_ms": round(statistics.median(s["router_ms"] or 0 for s in samples)),
                "agents_median_ms": round(statistics.median(s["agents_ms"] or 0 for s in samples)),
                "tool_calls_median": statistics.median(s["tool_calls"] for s in samples),
                "routes_seen": sorted({str(s["route"]) for s in samples}),
                "samples": samples,
            })
            print(f"  {name:28} median {rows[-1]['median_s']:>5}s  p95 {rows[-1]['p95_s']:>5}s  max {rows[-1]['max_s']:>5}s", flush=True)
    return rows


def run_load(url: str, level: int) -> dict:
    """`level` conversations ask the two-tool-call question at the same moment."""
    def one(_):
        with httpx.Client(base_url=url, timeout=300) as client:
            return timed_turn(client, LOAD_QUESTION)

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=level) as pool:
        samples = list(pool.map(one, range(level)))
    wall = time.perf_counter() - start
    seconds = [s["seconds"] for s in samples]
    return {
        "parallel_conversations": level,
        "wall_s": round(wall, 2),
        "median_s": round(statistics.median(seconds), 2),
        "max_s": round(max(seconds), 2),
        "errors": sum(s["http_status"] != 200 or s["route"] == "error" for s in samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:9090")
    parser.add_argument("--label", default="local", help="results go to evals/runs/latency-<label>/")
    parser.add_argument("--repeats", type=int, default=8, help="timed runs per scenario")
    parser.add_argument("--concurrency", default="4,8", help="comma separated numbers of parallel conversations")
    args = parser.parse_args()

    health = httpx.get(f"{args.url}/health", timeout=10)
    health.raise_for_status()

    print(f"Sequential, {args.repeats} runs per scenario (each in a fresh conversation):")
    rows = run_scenarios(args.url, args.repeats)

    print("\nUnder parallel load (same question, all at once):")
    loads = []
    for level in [int(x) for x in args.concurrency.split(",") if x]:
        loads.append(run_load(args.url, level))
        r = loads[-1]
        print(f"  {level:>2} at once: wall {r['wall_s']}s, median {r['median_s']}s, slowest {r['max_s']}s, errors {r['errors']}", flush=True)

    out = HERE / "runs" / f"latency-{args.label}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps({"url": args.url, "repeats": args.repeats, "scenarios": rows, "load": loads}, indent=2), encoding="utf-8")
    print(f"\nsaved to {out / 'summary.json'}")


if __name__ == "__main__":
    main()
