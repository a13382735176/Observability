#!/usr/bin/env python3
"""Aggregate KeyBag F1 and Position F1 by repo and by language.

STRICT scoring policy (paper-grade):
  - exclude cells with n_gt == 0   (auto-filter: function had no observability
    in ground truth, so the comparison is undefined)
    - for the remaining cells, treat key_bag_f1 == null as 0 and pos_f1 == null as 0
        (null is not a free pass)

Reads:  results/<run_id>/summary.json
Writes: results/<run_id>/aggregate_repo_lang.md

Usage:
  python tools/aggregate_repo_lang.py [run_id]
  default run_id = polyglot-pilot-001
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "polyglot-pilot-001"
SUMMARY = Path(f"results/{RUN_ID}/summary.json")
OUT_MD = Path(f"results/{RUN_ID}/aggregate_repo_lang.md")
RESULTS_ROOT = Path(f"results/{RUN_ID}")

PROMPTS = ["p_blind", "p1_obs_hinted", "p_fewshot"]
LANG_DISPLAY = {
    "go": "Go", "java": "Java", "py": "Python", "js": "JS",
    "cs": "C#", "cpp": "C++", "ts": "TS", "rs": "Rust",
    "rb": "Ruby", "php": "PHP",
}
REPO_DISPLAY = {
    "trainticket": "TrainTicket",
    "otel-demo":   "OTel-Demo",
    "deathstar":   "DeathStar",
    "boutique":    "Boutique",
    "sockshop":    "SockShop",
}


def parse_instance(inst: str) -> tuple[str, str]:
    """`{repo}__{lang}__...` -> (repo, lang). Handles otel-demo dashed prefix."""
    parts = inst.split("__")
    # otel-demo is hyphen-joined in repo field
    repo = parts[0]
    lang = parts[1] if len(parts) > 1 else "?"
    return repo, lang


def strict_metric(cell: dict, field: str) -> float | None:
    """Return metric field under STRICT policy, or None if excluded.

    STRICT exclusion is driven only by n_gt == 0.
    Remaining null metric values are treated as 0.
    """
    if cell.get("n_gt", 0) == 0:
        return None  # auto-filter
    value = cell.get(field)
    return 0.0 if value is None else float(value)


def cell_result_path(cell: dict) -> Path:
    """Path to per-cell result.json for this summary row."""
    model = cell.get("model", "")
    if not model:
        return Path()
    return RESULTS_ROOT / cell["instance"] / cell["prompt"] / model / "result.json"


def llm_keyword_count(cell: dict) -> int | None:
    """Count unique LLM observability keyword tokens for one cell.

    Source: result.json -> anchor_score.buckets[*].llm_keywords
    Rule: only buckets with llm_obs=True participate; token count is unique
    per-cell across all such buckets.
    """
    rp = cell_result_path(cell)
    if not rp.exists():
        return None
    try:
        data = json.loads(rp.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    buckets = (data.get("anchor_score") or {}).get("buckets") or []
    kws: set[str] = set()
    for b in buckets:
        if not isinstance(b, dict):
            continue
        if not b.get("llm_obs", False):
            continue
        for token in b.get("llm_keywords", []) or []:
            if isinstance(token, str) and token:
                kws.add(token)
    return len(kws)


def md_table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    def fmt_row(r):
        return "| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)) + " |"
    out = [fmt_row(headers)]
    out.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    for r in rows:
        out.append(fmt_row(r))
    return "\n".join(out)


def main():
    if not SUMMARY.exists():
        sys.exit(f"missing {SUMMARY}")
    cells = json.loads(SUMMARY.read_text())

    # filter to the 3 prompts we care about
    cells = [c for c in cells if c["prompt"] in PROMPTS]
    print(f"loaded {len(cells)} cells across {len(PROMPTS)} prompts")

    # group by (axis_value, prompt)
    by_repo_keybag: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_lang_keybag: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_repo_pos: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_lang_pos: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_prompt_keybag_p: dict[str, list[float]] = defaultdict(list)
    by_prompt_keybag_r: dict[str, list[float]] = defaultdict(list)
    by_prompt_keybag_f1: dict[str, list[float]] = defaultdict(list)
    by_prompt_pos_p: dict[str, list[float]] = defaultdict(list)
    by_prompt_pos_r: dict[str, list[float]] = defaultdict(list)
    by_prompt_pos_f1: dict[str, list[float]] = defaultdict(list)
    llm_n_sites_by_prompt: dict[str, list[float]] = defaultdict(list)
    llm_kw_by_prompt: dict[str, list[float]] = defaultdict(list)
    llm_kw_missing_by_prompt: dict[str, int] = defaultdict(int)
    n_excluded_per_prompt = defaultdict(int)
    n_total_per_prompt = defaultdict(int)

    for c in cells:
        repo, lang = parse_instance(c["instance"])
        prompt = c["prompt"]
        n_total_per_prompt[prompt] += 1
        keybag = strict_metric(c, "key_bag_f1")
        pos = strict_metric(c, "pos_f1")
        if keybag is None or pos is None:
            n_excluded_per_prompt[prompt] += 1
            continue
        by_repo_keybag[(repo, prompt)].append(keybag)
        by_lang_keybag[(lang, prompt)].append(keybag)
        by_repo_pos[(repo, prompt)].append(pos)
        by_lang_pos[(lang, prompt)].append(pos)
        by_prompt_keybag_p[prompt].append(strict_metric(c, "key_bag_precision") or 0.0)
        by_prompt_keybag_r[prompt].append(strict_metric(c, "key_bag_recall") or 0.0)
        by_prompt_keybag_f1[prompt].append(keybag)
        by_prompt_pos_p[prompt].append(strict_metric(c, "pos_precision") or 0.0)
        by_prompt_pos_r[prompt].append(strict_metric(c, "pos_recall") or 0.0)
        by_prompt_pos_f1[prompt].append(pos)
        llm_n_sites_by_prompt[prompt].append(float(c.get("n_llm", 0)))
        kw_count = llm_keyword_count(c)
        if kw_count is None:
            llm_kw_missing_by_prompt[prompt] += 1
        else:
            llm_kw_by_prompt[prompt].append(float(kw_count))

    print("\n=== filter accounting (STRICT, exclude n_gt=0) ===")
    for p in PROMPTS:
        total = n_total_per_prompt[p]
        excl = n_excluded_per_prompt[p]
        kept = total - excl
        print(f"  {p:18s}  total={total}  excluded={excl}  kept={kept}")

    # === build markdown ===
    lines = ["# obs-real-bench: 3-prompt ladder — per-repo & per-language breakdown\n"]
    lines.append("**Metrics:** KeyBag F1 and Position F1 (STRICT). Cells with `n_gt == 0` are excluded; "
                 "remaining cells with `key_bag_f1 == null` or `pos_f1 == null` are treated as 0.\n")
    n_instances = len({c["instance"] for c in cells})
    lines.append(f"**Run:** `{RUN_ID}` — {n_instances} instances × {len(PROMPTS)} prompts = {n_instances * len(PROMPTS)} cells.\n")

    # ---------- OVERALL ----------
    lines.append("\n## Overall\n")
    rows = []
    for p in PROMPTS:
        vals_keybag_p = by_prompt_keybag_p.get(p, [])
        vals_keybag_r = by_prompt_keybag_r.get(p, [])
        vals_keybag_f1 = by_prompt_keybag_f1.get(p, [])
        vals_pos_p = by_prompt_pos_p.get(p, [])
        vals_pos_r = by_prompt_pos_r.get(p, [])
        vals_pos_f1 = by_prompt_pos_f1.get(p, [])
        rows.append([
            p,
            len(vals_keybag_f1),
            f"{mean(vals_keybag_p):.3f}" if vals_keybag_p else "-",
            f"{mean(vals_keybag_r):.3f}" if vals_keybag_r else "-",
            f"{mean(vals_keybag_f1):.3f}" if vals_keybag_f1 else "-",
            f"{mean(vals_pos_p):.3f}" if vals_pos_p else "-",
            f"{mean(vals_pos_r):.3f}" if vals_pos_r else "-",
            f"{mean(vals_pos_f1):.3f}" if vals_pos_f1 else "-",
        ])
    lines.append(
        md_table(
            rows,
            [
                "Prompt",
                "n (kept)",
                "KeyBag P (mean)",
                "KeyBag R (mean)",
                "KeyBag F1 (mean)",
                "Pos P (mean)",
                "Pos R (mean)",
                "Pos F1 (mean)",
            ],
        )
    )

    # ---------- LLM generation volume ----------
    lines.append("\n\n## LLM observability generation volume (STRICT)\n")
    lines.append(
        "**Keyword-count definition:** for each cell, read "
        "`anchor_score.buckets[*].llm_keywords` from `result.json`, "
        "take only buckets with `llm_obs=true`, deduplicate tokens within "
        "the cell, then compute the prompt-wise mean."
    )
    rows = []
    for p in PROMPTS:
        kept = len(llm_n_sites_by_prompt.get(p, []))
        n_llm_mean = mean(llm_n_sites_by_prompt[p]) if kept else None
        kw_vals = llm_kw_by_prompt.get(p, [])
        kw_mean = mean(kw_vals) if kw_vals else None
        kw_cov = f"{len(kw_vals)}/{kept}"
        rows.append([
            p,
            kept,
            f"{n_llm_mean:.3f}" if n_llm_mean is not None else "-",
            f"{kw_mean:.3f}" if kw_mean is not None else "-",
            kw_cov,
        ])
    lines.append(
        md_table(
            rows,
            [
                "Prompt",
                "n (kept)",
                "LLM obs sites (mean n_llm)",
                "LLM obs keyword tokens (mean)",
                "keyword data coverage",
            ],
        )
    )

    blind_nllm = mean(llm_n_sites_by_prompt["p_blind"]) if llm_n_sites_by_prompt.get("p_blind") else None
    few_nllm = mean(llm_n_sites_by_prompt["p_fewshot"]) if llm_n_sites_by_prompt.get("p_fewshot") else None
    blind_kw = mean(llm_kw_by_prompt["p_blind"]) if llm_kw_by_prompt.get("p_blind") else None
    few_kw = mean(llm_kw_by_prompt["p_fewshot"]) if llm_kw_by_prompt.get("p_fewshot") else None
    if blind_nllm is not None and few_nllm is not None:
        lines.append(f"- Δ fewshot−blind (mean n_llm): {few_nllm - blind_nllm:+.3f}")
    if blind_kw is not None and few_kw is not None:
        lines.append(f"- Δ fewshot−blind (mean keyword tokens): {few_kw - blind_kw:+.3f}")

    # ---------- PER-REPO ----------
    lines.append("\n\n## Per-repo (KeyBag F1, STRICT)\n")
    repos = sorted({k[0] for k in by_repo_keybag.keys()},
                   key=lambda r: -sum(len(by_repo_keybag.get((r, p), [])) for p in PROMPTS))
    headers = ["Repo"] + [f"n_{p[:8]}" for p in PROMPTS] + [f"{p}" for p in PROMPTS] + ["Δ fewshot−blind"]
    rows = []
    for r in repos:
        n_per_prompt = [len(by_repo_keybag.get((r, p), [])) for p in PROMPTS]
        means = [mean(by_repo_keybag[(r, p)]) if by_repo_keybag.get((r, p)) else None for p in PROMPTS]
        m_blind = means[0]
        m_few = means[2]
        delta = f"{m_few - m_blind:+.3f}" if (m_blind is not None and m_few is not None) else "-"
        rows.append(
            [REPO_DISPLAY.get(r, r)]
            + n_per_prompt
            + [f"{m:.3f}" if m is not None else "-" for m in means]
            + [delta]
        )
    lines.append(md_table(rows, headers))

    lines.append("\n\n## Per-repo (Position F1, STRICT)\n")
    rows = []
    for r in repos:
        n_per_prompt = [len(by_repo_pos.get((r, p), [])) for p in PROMPTS]
        means = [mean(by_repo_pos[(r, p)]) if by_repo_pos.get((r, p)) else None for p in PROMPTS]
        m_blind = means[0]
        m_few = means[2]
        delta = f"{m_few - m_blind:+.3f}" if (m_blind is not None and m_few is not None) else "-"
        rows.append(
            [REPO_DISPLAY.get(r, r)]
            + n_per_prompt
            + [f"{m:.3f}" if m is not None else "-" for m in means]
            + [delta]
        )
    lines.append(md_table(rows, headers))

    # ---------- PER-LANGUAGE ----------
    lines.append("\n\n## Per-language (KeyBag F1, STRICT)\n")
    langs = sorted({k[0] for k in by_lang_keybag.keys()},
                   key=lambda l: -sum(len(by_lang_keybag.get((l, p), [])) for p in PROMPTS))
    headers = ["Lang"] + [f"n_{p[:8]}" for p in PROMPTS] + [f"{p}" for p in PROMPTS] + ["Δ fewshot−blind"]
    rows = []
    for l in langs:
        n_per_prompt = [len(by_lang_keybag.get((l, p), [])) for p in PROMPTS]
        means = [mean(by_lang_keybag[(l, p)]) if by_lang_keybag.get((l, p)) else None for p in PROMPTS]
        m_blind = means[0]
        m_few = means[2]
        delta = f"{m_few - m_blind:+.3f}" if (m_blind is not None and m_few is not None) else "-"
        rows.append(
            [LANG_DISPLAY.get(l, l)]
            + n_per_prompt
            + [f"{m:.3f}" if m is not None else "-" for m in means]
            + [delta]
        )
    lines.append(md_table(rows, headers))

    lines.append("\n\n## Per-language (Position F1, STRICT)\n")
    rows = []
    for l in langs:
        n_per_prompt = [len(by_lang_pos.get((l, p), [])) for p in PROMPTS]
        means = [mean(by_lang_pos[(l, p)]) if by_lang_pos.get((l, p)) else None for p in PROMPTS]
        m_blind = means[0]
        m_few = means[2]
        delta = f"{m_few - m_blind:+.3f}" if (m_blind is not None and m_few is not None) else "-"
        rows.append(
            [LANG_DISPLAY.get(l, l)]
            + n_per_prompt
            + [f"{m:.3f}" if m is not None else "-" for m in means]
            + [delta]
        )
    lines.append(md_table(rows, headers))

    # ---------- robustness sanity check ----------
    lines.append("\n\n## Robustness (KeyBag F1): does p_fewshot > p_blind hold per-repo and per-lang?\n")
    flips = []
    holds_repo = 0
    for r in repos:
        m_blind = mean(by_repo_keybag[(r, "p_blind")]) if by_repo_keybag.get((r, "p_blind")) else None
        m_few = mean(by_repo_keybag[(r, "p_fewshot")]) if by_repo_keybag.get((r, "p_fewshot")) else None
        if m_blind is None or m_few is None:
            continue
        if m_few > m_blind:
            holds_repo += 1
        else:
            flips.append(("repo", REPO_DISPLAY.get(r, r), m_blind, m_few))
    holds_lang = 0
    for l in langs:
        m_blind = mean(by_lang_keybag[(l, "p_blind")]) if by_lang_keybag.get((l, "p_blind")) else None
        m_few = mean(by_lang_keybag[(l, "p_fewshot")]) if by_lang_keybag.get((l, "p_fewshot")) else None
        if m_blind is None or m_few is None:
            continue
        if m_few > m_blind:
            holds_lang += 1
        else:
            flips.append(("lang", LANG_DISPLAY.get(l, l), m_blind, m_few))

    n_repos_with_data = sum(1 for r in repos if by_repo_keybag.get((r, "p_blind")) and by_repo_keybag.get((r, "p_fewshot")))
    n_langs_with_data = sum(1 for l in langs if by_lang_keybag.get((l, "p_blind")) and by_lang_keybag.get((l, "p_fewshot")))
    lines.append(f"- **Per-repo:** {holds_repo}/{n_repos_with_data} repos show fewshot > blind")
    lines.append(f"- **Per-lang:** {holds_lang}/{n_langs_with_data} languages show fewshot > blind")
    if flips:
        lines.append("\n### Exceptions (where fewshot did NOT beat blind):")
        for kind, name, b, f in flips:
            lines.append(f"  - {kind} `{name}`: blind={b:.3f}, fewshot={f:.3f}  (Δ={f-b:+.3f})")
    else:
        lines.append("\n_No exceptions — the finding holds universally across all axes with sufficient data._")

    lines.append("\n\n## Robustness (Position F1): does p_fewshot > p_blind hold per-repo and per-lang?\n")
    flips = []
    holds_repo = 0
    for r in repos:
        m_blind = mean(by_repo_pos[(r, "p_blind")]) if by_repo_pos.get((r, "p_blind")) else None
        m_few = mean(by_repo_pos[(r, "p_fewshot")]) if by_repo_pos.get((r, "p_fewshot")) else None
        if m_blind is None or m_few is None:
            continue
        if m_few > m_blind:
            holds_repo += 1
        else:
            flips.append(("repo", REPO_DISPLAY.get(r, r), m_blind, m_few))
    holds_lang = 0
    for l in langs:
        m_blind = mean(by_lang_pos[(l, "p_blind")]) if by_lang_pos.get((l, "p_blind")) else None
        m_few = mean(by_lang_pos[(l, "p_fewshot")]) if by_lang_pos.get((l, "p_fewshot")) else None
        if m_blind is None or m_few is None:
            continue
        if m_few > m_blind:
            holds_lang += 1
        else:
            flips.append(("lang", LANG_DISPLAY.get(l, l), m_blind, m_few))

    n_repos_with_data = sum(1 for r in repos if by_repo_pos.get((r, "p_blind")) and by_repo_pos.get((r, "p_fewshot")))
    n_langs_with_data = sum(1 for l in langs if by_lang_pos.get((l, "p_blind")) and by_lang_pos.get((l, "p_fewshot")))
    lines.append(f"- **Per-repo:** {holds_repo}/{n_repos_with_data} repos show fewshot > blind")
    lines.append(f"- **Per-lang:** {holds_lang}/{n_langs_with_data} languages show fewshot > blind")
    if flips:
        lines.append("\n### Exceptions (where fewshot did NOT beat blind):")
        for kind, name, b, f in flips:
            lines.append(f"  - {kind} `{name}`: blind={b:.3f}, fewshot={f:.3f}  (Δ={f-b:+.3f})")
    else:
        lines.append("\n_No exceptions — the finding holds universally across all axes with sufficient data._")

    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {OUT_MD}")
    print("\n" + "=" * 70)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
