"""Compares two runs on the same cases: what got fixed, what regressed, and the change in latency and cost.

    uv run python -m evals.compare baseline-rescored revised-priya

Both runs must be scored with the same golden set; rescore the older one first if the scorer changed.
"""
import json
import sys

from evals.run import HERE


def load(label: str) -> tuple[dict, dict]:
    run = HERE / "runs" / label
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    traces = {}
    for line in (run / "traces.jsonl").read_text(encoding="utf-8").splitlines():
        t = json.loads(line)
        traces[(t["case"], t["turn"])] = t
    return summary, traces


def main() -> None:
    before_label, after_label = sys.argv[1], sys.argv[2]
    before, before_traces = load(before_label)
    after, after_traces = load(after_label)

    fixed = [c for c, ok in after["case_results"].items() if ok and not before["case_results"].get(c, False)]
    regressed = [c for c, ok in after["case_results"].items() if not ok and before["case_results"].get(c, False)]
    still_failing = [c for c, ok in after["case_results"].items() if not ok and not before["case_results"].get(c, True)]

    print(f"{before_label}: {before['passed']}/{before['cases']}   ->   {after_label}: {after['passed']}/{after['cases']}\n")
    for title, cases in (("FIXED", fixed), ("REGRESSED", regressed), ("STILL FAILING", still_failing)):
        print(f"{title} ({len(cases)})")
        for case in cases:
            print(f"  {case}")
            if title != "FIXED":
                for (c, turn), t in after_traces.items():
                    for failure in t["failures"] if c == case else []:
                        print(f"      turn {turn}: {failure}")
        print()

    print("by category:")
    for category in sorted(set(before["by_category"]) | set(after["by_category"])):
        print(f"  {category:13} {before['by_category'].get(category, '-'):>5} -> {after['by_category'].get(category, '-')}")
    print(f"\nlatency median {before['latency_median_s']}s -> {after['latency_median_s']}s, "
          f"p95 {before['latency_p95_s']}s -> {after['latency_p95_s']}s")
    print(f"llm calls {before['llm_calls']} -> {after['llm_calls']}, "
          f"tokens in {before['prompt_tokens']} -> {after['prompt_tokens']}, out {before['completion_tokens']} -> {after['completion_tokens']}, "
          f"cost ${before['est_cost_usd']} -> ${after['est_cost_usd']}")


if __name__ == "__main__":
    main()