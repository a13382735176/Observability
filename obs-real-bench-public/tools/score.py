"""
obs-real-bench: scorer.

Compares two ObsSite lists (LLM output vs ground truth) and returns
precision / recall / weighted F1 using a graded bipartite match.

Match grade ladder (per-pair scores in [0, 1]):

    1.0  Exact          same type AND same key set (or keys empty on both)
    0.7  Strong         same type AND non-empty key-set Jaccard >= 0.5
    0.4  Type-only      same type but no key overlap
    0.0  Missing        type mismatch (unmatched)

The greedy bipartite assignment is fine for ~10 sites per function;
swap for Hungarian / linear_sum_assignment if instance sizes grow.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

# allow `python tools/score.py` and `python -m tools.score`
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from tools.extract import ObsSite  # noqa: E402


# ---------------------------------------------------------------------------
# pair grading
# ---------------------------------------------------------------------------

def _key_jaccard(a: list[str], b: list[str]) -> float:
    sa = {x for x in a if x}
    sb = {x for x in b if x}
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def grade(gt: ObsSite | dict, llm: ObsSite | dict) -> float:
    g = gt.to_dict() if isinstance(gt, ObsSite) else gt
    l = llm.to_dict() if isinstance(llm, ObsSite) else llm
    if g["type"] != l["type"]:
        return 0.0
    j = _key_jaccard(g.get("keys", []), l.get("keys", []))
    if j == 1.0:
        return 1.0
    if j >= 0.5:
        return 0.7
    return 0.4


# ---------------------------------------------------------------------------
# greedy assignment + F1
# ---------------------------------------------------------------------------

def _to_dicts(sites: Iterable[ObsSite | dict]) -> list[dict]:
    return [s.to_dict() if isinstance(s, ObsSite) else dict(s) for s in sites]


def score_sites(
    gt_sites: Iterable[ObsSite | dict],
    llm_sites: Iterable[ObsSite | dict],
) -> dict:
    gt = _to_dicts(gt_sites)
    llm = _to_dicts(llm_sites)
    n_gt = len(gt)
    n_llm = len(llm)
    if n_gt == 0 and n_llm == 0:
        return {
            "n_gt": 0, "n_llm": 0, "n_matched": 0,
            "precision": 1.0, "recall": 1.0, "f1": 1.0, "pairs": [],
        }
    if n_gt == 0:
        return {
            "n_gt": 0, "n_llm": n_llm, "n_matched": 0,
            "precision": 0.0, "recall": 1.0, "f1": 0.0, "pairs": [],
        }
    if n_llm == 0:
        return {
            "n_gt": n_gt, "n_llm": 0, "n_matched": 0,
            "precision": 1.0, "recall": 0.0, "f1": 0.0, "pairs": [],
        }

    # greedy: at each step take the highest-scoring unused pair
    used_gt: set[int] = set()
    used_llm: set[int] = set()
    pairs: list[dict] = []
    while True:
        best = (0.0, -1, -1)
        for i, g in enumerate(gt):
            if i in used_gt:
                continue
            for j, m in enumerate(llm):
                if j in used_llm:
                    continue
                s = grade(g, m)
                if s > best[0]:
                    best = (s, i, j)
        if best[0] <= 0 or best[1] < 0:
            break
        used_gt.add(best[1])
        used_llm.add(best[2])
        pairs.append({
            "score": best[0],
            "gt_type": gt[best[1]]["type"],
            "llm_type": llm[best[2]]["type"],
            "gt_keys": gt[best[1]].get("keys", []),
            "llm_keys": llm[best[2]].get("keys", []),
        })

    matched_score_sum = sum(p["score"] for p in pairs)
    precision = matched_score_sum / n_llm
    recall = matched_score_sum / n_gt
    f1 = (
        0.0
        if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    return {
        "n_gt": n_gt,
        "n_llm": n_llm,
        "n_matched": len(pairs),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "pairs": pairs,
    }
