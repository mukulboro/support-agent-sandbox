"""Scores saved traces again with the current golden set and scorer. Makes no LLM calls, so it costs nothing.

    uv run python -m evals.rescore --from baseline --to baseline-rescored
"""
import argparse
import json

from evals.run import HERE, check, summarise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="source", required=True, help="run to read traces from")
    parser.add_argument("--to", dest="target", required=True, help="run to write the re-scored traces to")
    args = parser.parse_args()

    golden = json.loads((HERE / "golden_set.json").read_text(encoding="utf-8"))
    expects = {c["id"]: c["turns"] for c in golden["cases"]}

    source = HERE / "runs" / args.source
    traces = [json.loads(line) for line in (source / "traces.jsonl").read_text(encoding="utf-8").splitlines()]
    for t in traces:
        expect = expects[t["case"]][t["turn"] - 1]["expect"]
        t["failures"] = check(t, expect, golden["phrases"])
        t["passed"] = not t["failures"]

    model = json.loads((source / "summary.json").read_text(encoding="utf-8"))["model"]
    summary = summarise(traces, model)
    summary["label"] = args.target
    summary["rescored_from"] = args.source

    out = HERE / "runs" / args.target
    out.mkdir(parents=True, exist_ok=True)
    (out / "traces.jsonl").write_text("\n".join(json.dumps(t) for t in traces) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    before = json.loads((source / "summary.json").read_text(encoding="utf-8"))["case_results"]
    for case_id, passed in summary["case_results"].items():
        if passed != before[case_id]:
            print(f"{'now passes' if passed else 'now FAILS '}  {case_id}")
    print(f"\n{args.source}: {sum(before.values())}/{len(before)}  ->  {args.target}: {summary['passed']}/{summary['cases']}")
    print("by category:", summary["by_category"])
    for t in traces:
        for failure in t["failures"]:
            print(f"  still failing  {t['case']}: {failure}")


if __name__ == "__main__":
    main()
