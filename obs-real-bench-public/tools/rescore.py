"""
Re-score an existing pilot run with the anchor-based F1 metric.

Walks results/<run_id>/<instance>/<prompt>/<model>/, reads ground_truth.py
and llm_source.py, computes the anchor F1, writes the result back as
`anchor_score` into result.json, and prints a comparison summary.

Usage:
    python -m tools.rescore --run-id pilot-001
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from tools.score_anchor import score_anchor  # noqa: E402

ROOT = _HERE.parent


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _load_function_name(results_root: Path, instance_id: str) -> str:
    """Look up the target function from the instance JSON."""
    return _load_instance_target(results_root, instance_id)["function"]


def _load_instance_target(results_root: Path, instance_id: str) -> dict:
    """Return ``{function, language}`` for the instance."""
    inst_root = results_root.parent.parent / "instances" / "function"
    instance_path = inst_root / f"{instance_id}.json"
    if not instance_path.exists():
        for candidate in [ROOT / "instances" / "function" / f"{instance_id}.json"]:
            if candidate.exists():
                instance_path = candidate
                break
    data = json.loads(instance_path.read_text(encoding="utf-8"))
    tgt = data.get("target", {}) or {}
    return {
        "function": tgt.get("function", ""),
        "language": (tgt.get("language") or "python").lower(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="pilot-001")
    ap.add_argument(
        "--results-root",
        default=str(ROOT / "results"),
    )
    args = ap.parse_args()

    root = Path(args.results_root) / args.run_id
    if not root.exists():
        print(f"no such run: {root}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    for inst_dir in sorted(root.iterdir()):
        if not inst_dir.is_dir():
            continue
        instance_id = inst_dir.name
        try:
            target_info = _load_instance_target(root, instance_id)
            function_name = target_info["function"]
            language = target_info["language"]
        except Exception as e:  # noqa: BLE001
            print(f"  skip {instance_id}: cannot resolve function name ({e})")
            continue
        for prompt_dir in sorted(inst_dir.iterdir()):
            if not prompt_dir.is_dir():
                continue
            for model_dir in sorted(prompt_dir.iterdir()):
                if not model_dir.is_dir():
                    continue
                result_path = model_dir / "result.json"
                gt_path = model_dir / "ground_truth.py"
                llm_path = model_dir / "llm_source.py"
                if not (result_path.exists() and gt_path.exists() and llm_path.exists()):
                    continue
                gt_src = _read(gt_path)
                llm_src = _read(llm_path)
                anchor = score_anchor(
                    gt_src, llm_src, function_name, language=language
                )

                # merge anchor score back into result.json
                result = json.loads(result_path.read_text(encoding="utf-8"))
                result["anchor_score"] = anchor
                result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

                old_f1 = result.get("score", {}).get("f1")
                old_score = result.get("score", {}) or {}
                rows.append({
                    "instance": instance_id,
                    "prompt": prompt_dir.name,
                    "model": model_dir.name,
                    "old_f1": old_f1,
                    # legacy obs-site counts (F1-free signal, useful per-prompt)
                    "n_gt":  old_score.get("n_gt"),
                    "n_llm": old_score.get("n_llm"),
                    "anchor_f1": anchor["f1"],
                    "anchor_p": anchor["precision"],
                    "anchor_r": anchor["recall"],
                    "tp": anchor["tp"], "fp": anchor["fp"], "fn": anchor["fn"],
                    "n_anchors_gt": anchor["n_anchors_gt"],
                    "n_anchors_llm": anchor["n_anchors_llm"],
                    "n_aligned": anchor["n_anchors_aligned"],
                    "n_buckets": anchor["n_buckets"],
                    # Key F1 (strict) axis (independent of Position F1)
                    "key_f1": anchor["key_f1"],
                    "key_p": anchor["key_precision"],
                    "key_r": anchor["key_recall"],
                    "key_tp": anchor["key_tp"],
                    "key_fp": anchor["key_fp"],
                    "key_fn": anchor["key_fn"],
                    "key_n": anchor["key_n_comparable_buckets"],
                    # Key F1 (bag, lenient token-level) — headline = recall
                    "key_bag_f1": anchor["key_bag_f1"],
                    "key_bag_p":  anchor["key_bag_precision"],
                    "key_bag_r":  anchor["key_bag_recall"],
                    "key_bag_tp": anchor["key_bag_tp"],
                    "key_bag_fp": anchor["key_bag_fp"],
                    "key_bag_fn": anchor["key_bag_fn"],
                    "key_bag_n":  anchor["key_bag_n_comparable_buckets"],
                })

    # Print a comparison table
    if not rows:
        print("no cells found.")
        return 1

    # column widths
    name_w = max(len(r["instance"]) for r in rows) + 2
    prompt_w = max(len(r["prompt"]) for r in rows) + 2
    print()
    # Headline = Bag Recall (the cleanest 'did LLM record the concepts GT cared
    # about'). Bag F1 next to it shows precision-pulled-down (LLM verbosity).
    # Strict KeyF1 kept as a compact column for legacy comparison.
    print(
        f"{'instance'.ljust(name_w)}{'prompt'.ljust(prompt_w)}"
        f"{'aligned':>9}"
        f"{'PosP':>7}{'PosR':>7}{'PosF1':>8}"
        f"{'StrN':>6}{'StrF1':>7}"
        f"{'BagN':>6}{'BagP':>7}{'BagR':>7}{'BagF1':>8}"
        f"{'OldF1':>9}"
    )
    print("-" * (name_w + prompt_w + 9 + 22 + 13 + 28 + 9))
    for r in rows:
        if r["key_f1"] is None:
            strict_cell = f"{r['key_n']:>6}{'  N/A ':>7}"
        else:
            strict_cell = f"{r['key_n']:>6}{r['key_f1']:>7.3f}"
        if r["key_bag_f1"] is None:
            bag_cell = f"{r['key_bag_n']:>6}{'  N/A ':>7}{'  N/A ':>7}{'  N/A ':>8}"
        else:
            bag_cell = (
                f"{r['key_bag_n']:>6}{r['key_bag_p']:>7.3f}"
                f"{r['key_bag_r']:>7.3f}{r['key_bag_f1']:>8.3f}"
            )
        print(
            f"{r['instance'].ljust(name_w)}{r['prompt'].ljust(prompt_w)}"
            f"{r['n_aligned']:>9}"
            f"{r['anchor_p']:>7.3f}{r['anchor_r']:>7.3f}{r['anchor_f1']:>8.3f}"
            f"{strict_cell}"
            f"{bag_cell}"
            f"{(r['old_f1'] or 0):>9.3f}"
        )

    # ---- aggregate means -------------------------------------------------
    def _mean(vals: list) -> Optional[float]:  # type: ignore[type-arg]
        vs = [v for v in vals if v is not None]
        return sum(vs) / len(vs) if vs else None

    def _mean_harsh(vals: list) -> float | None:
        """Mean treating None as 0.0 — counts every cell in the denominator.

        Use for headline F1: prompts that silence the LLM (e.g. p_blind)
        should not benefit from filtering their silent cells out of the
        average.
        """
        if not vals:
            return None
        return sum((v if v is not None else 0.0) for v in vals) / len(vals)

    def _fmt(v) -> str:
        return " N/A " if v is None else f"{v:.3f}"

    def _print_block(rs: list[dict], label: str) -> None:
        """Print one OldF1 / Position / Key(strict) / Key(bag) aggregate.
        Used once for ALL rows and once per prompt-level so p0 / p1 / p2 /
        p_blind can be compared at a glance without re-running.

        Key strict / Key bag are HARSH: every cell is in the denominator,
        N/A counts as 0. The '(zero-score cells: M/N)' note next to each
        line tells you how many of N cells were N/A → 0 — i.e. how much
        survivor-bias this harshness corrected for.
        """
        n_ = len(rs)
        if n_ == 0:
            print(f"  {label}: no rows")
            return
        m_old = _mean([r["old_f1"] for r in rs])
        m_n_llm = _mean([r.get("n_llm") for r in rs])
        m_n_gt  = _mean([r.get("n_gt")  for r in rs])
        m_pos_p = _mean([r["anchor_p"]  for r in rs])
        m_pos_r = _mean([r["anchor_r"]  for r in rs])
        m_pos_f = _mean([r["anchor_f1"] for r in rs])
        # Harsh Key strict + Key bag (headline): every row in denominator.
        n_strict_zero = sum(1 for r in rs if r["key_f1"] is None)
        m_strict_p = _mean_harsh([r["key_p"]  for r in rs])
        m_strict_r = _mean_harsh([r["key_r"]  for r in rs])
        m_strict_f = _mean_harsh([r["key_f1"] for r in rs])
        n_bag_zero = sum(1 for r in rs if r["key_bag_f1"] is None)
        m_bag_p = _mean_harsh([r["key_bag_p"]  for r in rs])
        m_bag_r = _mean_harsh([r["key_bag_r"]  for r in rs])
        m_bag_f = _mean_harsh([r["key_bag_f1"] for r in rs])
        print(f"  === {label} (n={n_}) ===")
        print(
            f"    counts                   :  "
            f"n_gt={_fmt(m_n_gt)}  n_llm={_fmt(m_n_llm)}    "
            f"(raw obs-site counts; F1-free signal)"
        )
        print(f"    OldF1   (legacy type-bag) :  F1={_fmt(m_old)}")
        print(
            f"    Position                  :  "
            f"P={_fmt(m_pos_p)}  R={_fmt(m_pos_r)}  F1={_fmt(m_pos_f)}"
        )
        print(
            f"    Key strict ({n_}-cell mean):  "
            f"P={_fmt(m_strict_p)}  R={_fmt(m_strict_r)}  F1={_fmt(m_strict_f)}   "
            f"[{n_strict_zero} of those {n_} cells contributed 0]"
        )
        print(
            f"    Key bag    ({n_}-cell mean):  "
            f"P={_fmt(m_bag_p)}  R={_fmt(m_bag_r)}  F1={_fmt(m_bag_f)}   "
            f"[{n_bag_zero} of those {n_} cells contributed 0]    \u2190 HEADLINE"
        )

    print()
    _print_block(rows, "ALL")

    # Per-prompt breakdown so p0 / p1 / p2 / p_blind can be compared
    # directly. Sorted by prompt name for stable ordering across runs.
    prompts_seen = sorted({r.get("prompt", "") for r in rows if r.get("prompt")})
    if len(prompts_seen) > 1:
        for p in prompts_seen:
            sub = [r for r in rows if r.get("prompt") == p]
            _print_block(sub, f"prompt={p}")

    # save summary
    out = root / "anchor_summary.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
