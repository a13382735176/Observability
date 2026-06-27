"""
Aggregate anchor-F1 results from a pilot run.

Reads `results/<run_id>/anchor_summary.json` (written by tools.rescore) and
prints:
  - Per-prompt macro statistics (mean / median / std / min / max anchor F1).
  - Per-prompt micro F1 (sum of TP / FP / FN across all instances).
  - Per-instance leaderboard (sorted by anchor F1, descending).
  - Head-to-head delta between any two prompts (default p0_vanilla vs
    p2_otel_explicit).

Usage:
    python -m tools.aggregate_pilot --run-id pilot-002
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as stats
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _f1(tp: int, fp: int, fn: int) -> float:
    if tp == 0:
        return 0.0
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    return 2 * p * r / (p + r) if (p + r) else 0.0


def _fmt(x: float | None, w: int = 6) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—".rjust(w)
    return f"{x:.3f}".rjust(w)


def _macro(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    return {
        "n": len(values),
        "mean": stats.mean(values),
        "median": stats.median(values),
        "std": stats.pstdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument(
        "--results-root",
        default=str(ROOT / "results"),
    )
    ap.add_argument(
        "--compare",
        default="p0_vanilla,p2_otel_explicit",
        help="Two prompt names, comma-separated, for head-to-head diff.",
    )
    args = ap.parse_args()

    summary_path = Path(args.results_root) / args.run_id / "anchor_summary.json"
    if not summary_path.exists():
        print(f"missing {summary_path}; run tools.rescore first.")
        return 2

    rows = json.loads(summary_path.read_text())
    by_prompt: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_prompt[r["prompt"]].append(r)

    prompts = sorted(by_prompt)

    # -------- Macro statistics per prompt --------
    print(f"\n=== {args.run_id}: macro anchor-F1 per prompt ===\n")
    print(f"{'prompt':<22}{'n':>5}{'mean':>8}{'median':>8}{'std':>8}{'min':>8}{'max':>8}")
    print("-" * 67)
    macro: dict[str, dict[str, float]] = {}
    for p in prompts:
        f1s = [r["anchor_f1"] for r in by_prompt[p]]
        m = _macro(f1s)
        macro[p] = m
        print(
            f"{p:<22}{m['n']:>5}"
            f"{_fmt(m['mean'])}{_fmt(m['median'])}{_fmt(m['std'])}"
            f"{_fmt(m['min'])}{_fmt(m['max'])}"
        )

    # -------- Micro F1 per prompt --------
    print(f"\n=== {args.run_id}: micro anchor-F1 per prompt (TP/FP/FN pooled) ===\n")
    print(f"{'prompt':<22}{'TP':>6}{'FP':>6}{'FN':>6}{'P':>8}{'R':>8}{'F1':>8}")
    print("-" * 64)
    micro: dict[str, dict[str, float]] = {}
    for p in prompts:
        tp = sum(r["tp"] for r in by_prompt[p])
        fp = sum(r["fp"] for r in by_prompt[p])
        fn = sum(r["fn"] for r in by_prompt[p])
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = _f1(tp, fp, fn)
        micro[p] = {"tp": tp, "fp": fp, "fn": fn, "p": prec, "r": rec, "f1": f1}
        print(
            f"{p:<22}{tp:>6}{fp:>6}{fn:>6}"
            f"{_fmt(prec)}{_fmt(rec)}{_fmt(f1)}"
        )

    # -------- Per-instance leaderboard per prompt --------
    for p in prompts:
        print(f"\n=== {args.run_id}: per-instance leaderboard | prompt={p} ===\n")
        sorted_rows = sorted(by_prompt[p], key=lambda r: r["anchor_f1"], reverse=True)
        name_w = max((len(r["instance"]) for r in sorted_rows), default=20) + 2
        print(
            f"{'instance':<{name_w}}"
            f"{'gtA':>5}{'llmA':>6}{'TP':>4}{'FP':>4}{'FN':>4}"
            f"{'P':>8}{'R':>8}{'F1':>8}"
        )
        print("-" * (name_w + 5 + 6 + 12 + 24))
        for r in sorted_rows:
            print(
                f"{r['instance']:<{name_w}}"
                f"{r['n_anchors_gt']:>5}{r['n_anchors_llm']:>6}"
                f"{r['tp']:>4}{r['fp']:>4}{r['fn']:>4}"
                f"{_fmt(r['anchor_p'])}{_fmt(r['anchor_r'])}{_fmt(r['anchor_f1'])}"
            )

    # -------- Head-to-head delta --------
    cmp_prompts = [s.strip() for s in args.compare.split(",") if s.strip()]
    if len(cmp_prompts) == 2 and all(p in by_prompt for p in cmp_prompts):
        a, b = cmp_prompts
        by_inst_a = {r["instance"]: r for r in by_prompt[a]}
        by_inst_b = {r["instance"]: r for r in by_prompt[b]}
        common = sorted(set(by_inst_a) & set(by_inst_b))
        deltas = [by_inst_b[i]["anchor_f1"] - by_inst_a[i]["anchor_f1"] for i in common]
        n_better = sum(1 for d in deltas if d > 0)
        n_tie = sum(1 for d in deltas if d == 0)
        n_worse = sum(1 for d in deltas if d < 0)
        mean_delta = stats.mean(deltas) if deltas else 0.0
        print(f"\n=== Head-to-head: {b} − {a} on {len(common)} instances ===\n")
        print(f"  mean Δ F1   = {mean_delta:+.3f}")
        print(f"  {b} better  : {n_better}")
        print(f"  tie         : {n_tie}")
        print(f"  {a} better  : {n_worse}")
        print(
            f"  macro F1    : {a}={macro[a]['mean']:.3f}  "
            f"→  {b}={macro[b]['mean']:.3f}  (Δ={macro[b]['mean']-macro[a]['mean']:+.3f})"
        )
        print(
            f"  micro F1    : {a}={micro[a]['f1']:.3f}  "
            f"→  {b}={micro[b]['f1']:.3f}  (Δ={micro[b]['f1']-micro[a]['f1']:+.3f})"
        )

        # Save a CSV-ish head-to-head table
        out = summary_path.parent / "head_to_head.json"
        out.write_text(json.dumps({
            "a": a, "b": b,
            "macro": {a: macro[a], b: macro[b]},
            "micro": {a: micro[a], b: micro[b]},
            "per_instance": [
                {
                    "instance": i,
                    f"{a}_f1": by_inst_a[i]["anchor_f1"],
                    f"{b}_f1": by_inst_b[i]["anchor_f1"],
                    "delta": by_inst_b[i]["anchor_f1"] - by_inst_a[i]["anchor_f1"],
                }
                for i in common
            ],
        }, indent=2))
        print(f"\nwrote {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
