#!/usr/bin/env python3
"""Generate a paper-style SVG for the blind-vs-hinted quantity/quality finding.

This script uses only the Python standard library. It aggregates per-cell
``result.json`` files from an obs-real-bench run and writes:
  - one SVG figure with four panels (a--d)
  - one CSV file containing the plotted values

Example:
    python tools/plot_quantity_quality_finding.py \
        --run-dir results/agent-sanitized-copy-gpt5.5 \
        --out results/agent-sanitized-copy-gpt5.5/quantity_quality_finding.svg
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean


PROMPTS = ("p_blind", "p1_obs_hinted")
PROMPT_LABELS = {"p_blind": "Blind", "p1_obs_hinted": "Hinted"}

# Muted, print-friendly palette.
INK = "#111827"
MUTED = "#64748B"
GRID = "#E5E7EB"
AXIS = "#334155"
REFERENCE = "#7C8794"
BLIND = "#2563EB"
HINTED = "#EA580C"
OVERLAP = "#059669"


@dataclass
class PromptStats:
    cells: int
    original_obs_per_cell: float
    generated_obs_per_cell: float
    matched_obs_per_cell: float
    generated_over_original: float
    position_precision: float
    position_recall: float
    position_f1: float
    comparable_cells: int
    reference_keyvars_per_cell: float
    generated_keyvars_per_cell: float
    overlap_keyvars_per_cell: float
    keyvars_generated_over_reference: float
    keybag_precision: float
    keybag_recall: float
    keybag_f1: float
    reference_keyvars_total: int
    generated_keyvars_total: int
    overlap_keyvars_total: int
    extra_keyvars_total: int
    missed_keyvars_total: int


def nonnull(value: object) -> float:
    return 0.0 if value is None else float(value)


def load_stats(run_dir: Path) -> dict[str, PromptStats]:
    records: list[tuple[str, dict, dict]] = []
    for path in run_dir.glob("*/*/*/result.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        prompt = payload.get("prompt_level")
        if prompt not in PROMPTS:
            continue
        score = payload.get("score") or {}
        anchor = payload.get("anchor_score") or {}
        if (score.get("n_gt") or 0) <= 0:
            continue
        records.append((prompt, score, anchor))

    stats: dict[str, PromptStats] = {}
    for prompt in PROMPTS:
        rows = [(score, anchor) for p, score, anchor in records if p == prompt]
        if not rows:
            raise SystemExit(f"No rows found for {prompt!r} under {run_dir}")

        cells = len(rows)
        original_obs = sum(int(score.get("n_gt") or 0) for score, _ in rows)
        generated_obs = sum(int(score.get("n_llm") or 0) for score, _ in rows)
        matched_obs = sum(int(score.get("n_matched") or 0) for score, _ in rows)

        keybag_tp = sum(int(anchor.get("key_bag_tp") or 0) for _, anchor in rows)
        keybag_fp = sum(int(anchor.get("key_bag_fp") or 0) for _, anchor in rows)
        keybag_fn = sum(int(anchor.get("key_bag_fn") or 0) for _, anchor in rows)
        reference_keyvars = keybag_tp + keybag_fn
        generated_keyvars = keybag_tp + keybag_fp

        stats[prompt] = PromptStats(
            cells=cells,
            original_obs_per_cell=original_obs / cells,
            generated_obs_per_cell=generated_obs / cells,
            matched_obs_per_cell=matched_obs / cells,
            generated_over_original=generated_obs / original_obs if original_obs else 0.0,
            position_precision=mean(nonnull(anchor.get("precision")) for _, anchor in rows),
            position_recall=mean(nonnull(anchor.get("recall")) for _, anchor in rows),
            position_f1=mean(nonnull(anchor.get("f1")) for _, anchor in rows),
            comparable_cells=sum(1 for _, anchor in rows if int(anchor.get("key_bag_n_comparable_buckets") or 0) > 0),
            reference_keyvars_per_cell=reference_keyvars / cells,
            generated_keyvars_per_cell=generated_keyvars / cells,
            overlap_keyvars_per_cell=keybag_tp / cells,
            keyvars_generated_over_reference=generated_keyvars / reference_keyvars if reference_keyvars else 0.0,
            keybag_precision=mean(nonnull(anchor.get("key_bag_precision")) for _, anchor in rows),
            keybag_recall=mean(nonnull(anchor.get("key_bag_recall")) for _, anchor in rows),
            keybag_f1=mean(nonnull(anchor.get("key_bag_f1")) for _, anchor in rows),
            reference_keyvars_total=reference_keyvars,
            generated_keyvars_total=generated_keyvars,
            overlap_keyvars_total=keybag_tp,
            extra_keyvars_total=keybag_fp,
            missed_keyvars_total=keybag_fn,
        )
    return stats


class Svg:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.parts: list[str] = []

    def add(self, raw: str) -> None:
        self.parts.append(raw)

    def text(
        self,
        x: float,
        y: float,
        text: object,
        *,
        size: int = 16,
        weight: int = 400,
        fill: str = INK,
        anchor: str = "start",
        rotate: float | None = None,
    ) -> None:
        transform = f' transform="rotate({rotate:.1f} {x:.1f} {y:.1f})"' if rotate is not None else ""
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial, Helvetica, sans-serif" '
            f'font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{transform}>'
            f'{html.escape(str(text), quote=True)}</text>'
        )

    def rect(self, x: float, y: float, w: float, h: float, fill: str, *, rx: float = 0, stroke: str = "none", opacity: float = 1.0) -> None:
        self.add(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx:.1f}" '
            f'fill="{fill}" stroke="{stroke}" opacity="{opacity:.3f}"/>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, *, stroke: str = AXIS, width: float = 1.0, dash: str | None = None) -> None:
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{stroke}" stroke-width="{width:.1f}"{dash_attr}/>'
        )

    def circle(self, cx: float, cy: float, r: float, fill: str, *, stroke: str = "none") -> None:
        self.add(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill}" stroke="{stroke}"/>')

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(self.parts)
        path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}">\n'
            f'<rect width="100%" height="100%" fill="#FFFFFF"/>\n{body}\n</svg>\n',
            encoding="utf-8",
        )


def panel_title(svg: Svg, x: float, y: float, letter: str, title: str) -> None:
    svg.circle(x + 10, y - 7, 15, "#F1F5F9", stroke="#CBD5E1")
    svg.text(x + 10, y - 1, letter, size=13, weight=700, fill=AXIS, anchor="middle")
    svg.text(x + 36, y, title, size=19, weight=700)


def legend(svg: Svg, x: float, y: float, items: list[tuple[str, str]]) -> None:
    cursor = x
    for label, color in items:
        svg.rect(cursor, y - 11, 20, 10, color, rx=2)
        svg.text(cursor + 28, y, label, size=13, fill=MUTED)
        cursor += 28 + len(label) * 7.4 + 30


def draw_axes(svg: Svg, x: float, y: float, w: float, h: float, ymax: float, *, ticks: int, ylabel: str, fmt: str) -> tuple[float, float, float, float]:
    left = x + 72
    right = x + w - 20
    top = y + 44
    bottom = y + h - 58
    plot_h = bottom - top
    for i in range(ticks + 1):
        value = ymax * i / ticks
        yy = bottom - plot_h * value / ymax
        svg.line(left, yy, right, yy, stroke=GRID, width=0.8)
        svg.text(left - 10, yy + 4, fmt.format(value), size=11, fill=MUTED, anchor="end")
    svg.line(left, bottom, right, bottom, stroke=AXIS, width=1.1)
    svg.line(left, top, left, bottom, stroke=AXIS, width=1.1)
    svg.text(x + 18, top + plot_h / 2, ylabel, size=12, fill=MUTED, anchor="middle", rotate=-90)
    return left, top, right, bottom


def draw_grouped_bars(
    svg: Svg,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    letter: str,
    categories: list[str],
    series: list[tuple[str, list[float], str]],
    ymax: float,
    ylabel: str,
    fmt: str,
    annotation: str | None = None,
) -> None:
    panel_title(svg, x, y, letter, title)
    left, top, right, bottom = draw_axes(svg, x, y, w, h, ymax, ticks=4, ylabel=ylabel, fmt=fmt)
    plot_w = right - left
    plot_h = bottom - top
    group_w = plot_w / len(categories)
    gap = 8
    bar_w = min(50, (group_w - 24 - gap * (len(series) - 1)) / len(series))

    for ci, category in enumerate(categories):
        group_left = left + ci * group_w
        bars_w = len(series) * bar_w + (len(series) - 1) * gap
        start = group_left + (group_w - bars_w) / 2
        for si, (_, values, color) in enumerate(series):
            value = values[ci]
            bh = plot_h * value / ymax
            bx = start + si * (bar_w + gap)
            by = bottom - bh
            svg.rect(bx, by, bar_w, bh, color, rx=2)
            svg.text(bx + bar_w / 2, by - 7, fmt.format(value), size=11, fill=INK, anchor="middle")
        svg.text(group_left + group_w / 2, bottom + 26, category, size=13, fill=INK, anchor="middle")

    if annotation:
        svg.text(right, y + 4, annotation, size=13, weight=700, fill=HINTED, anchor="end")


def write_csv(path: Path, stats: dict[str, PromptStats]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["prompt"] + list(PromptStats.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for prompt in PROMPTS:
            row = stats[prompt].__dict__.copy()
            row["prompt"] = PROMPT_LABELS[prompt]
            writer.writerow(row)


def build_figure(stats: dict[str, PromptStats], out: Path) -> None:
    blind = stats["p_blind"]
    hinted = stats["p1_obs_hinted"]
    svg = Svg(1500, 980)

    svg.text(60, 52, "Explicit hints increase volume, not quality", size=30, weight=700)
    svg.text(
        60,
        80,
        "Static source analysis of observability statements and KeyBag variables across 1,223 cells.",
        size=15,
        fill=MUTED,
    )
    legend(svg, 1040, 74, [("Original", REFERENCE), ("Blind", BLIND), ("Hinted", HINTED), ("Overlap", OVERLAP)])

    x1, x2 = 58, 780
    y1, y2 = 132, 556
    w, h = 660, 350

    draw_grouped_bars(
        svg,
        x=x1,
        y=y1,
        w=w,
        h=h,
        title="Observability statements per cell",
        letter="a",
        categories=["Original", "Blind", "Hinted"],
        series=[("Count", [blind.original_obs_per_cell, blind.generated_obs_per_cell, hinted.generated_obs_per_cell], REFERENCE)],
        ymax=5.5,
        ylabel="Statements / cell",
        fmt="{:.1f}",
        annotation=f"Hinted = {hinted.generated_over_original:.2f}x original",
    )
    # Recolor single-series bars in panel (a) for direct semantic mapping.
    left, top, right, bottom = x1 + 72, y1 + 44, x1 + w - 20, y1 + h - 58
    plot_w, plot_h = right - left, bottom - top
    group_w = plot_w / 3
    values = [blind.original_obs_per_cell, blind.generated_obs_per_cell, hinted.generated_obs_per_cell]
    colors = [REFERENCE, BLIND, HINTED]
    for i, (value, color) in enumerate(zip(values, colors)):
        bw = 50
        bx = left + i * group_w + (group_w - bw) / 2
        bh = plot_h * value / 5.5
        by = bottom - bh
        svg.rect(bx, by, bw, bh, color, rx=2)
        svg.text(bx + bw / 2, by - 7, f"{value:.1f}", size=11, anchor="middle")

    draw_grouped_bars(
        svg,
        x=x2,
        y=y1,
        w=w,
        h=h,
        title="Placement quality",
        letter="b",
        categories=["Precision", "Recall", "F1"],
        series=[
            ("Blind", [blind.position_precision, blind.position_recall, blind.position_f1], BLIND),
            ("Hinted", [hinted.position_precision, hinted.position_recall, hinted.position_f1], HINTED),
        ],
        ymax=1.0,
        ylabel="Score",
        fmt="{:.2f}",
        annotation=f"F1 {hinted.position_f1 - blind.position_f1:+.3f}",
    )

    draw_grouped_bars(
        svg,
        x=x1,
        y=y2,
        w=w,
        h=h,
        title="KeyBag variable volume",
        letter="c",
        categories=["Reference", "Generated", "Overlap"],
        series=[
            ("Blind", [blind.reference_keyvars_per_cell, blind.generated_keyvars_per_cell, blind.overlap_keyvars_per_cell], BLIND),
            ("Hinted", [hinted.reference_keyvars_per_cell, hinted.generated_keyvars_per_cell, hinted.overlap_keyvars_per_cell], HINTED),
        ],
        ymax=25.0,
        ylabel="Variables / cell",
        fmt="{:.1f}",
        annotation="Overlap stays flat",
    )

    draw_grouped_bars(
        svg,
        x=x2,
        y=y2,
        w=w,
        h=h,
        title="KeyBag variable quality",
        letter="d",
        categories=["Precision", "Recall", "F1"],
        series=[
            ("Blind", [blind.keybag_precision, blind.keybag_recall, blind.keybag_f1], BLIND),
            ("Hinted", [hinted.keybag_precision, hinted.keybag_recall, hinted.keybag_f1], HINTED),
        ],
        ymax=1.0,
        ylabel="Score",
        fmt="{:.2f}",
        annotation=f"F1 {hinted.keybag_f1 - blind.keybag_f1:+.3f}",
    )

    svg.text(
        60,
        952,
        "Note: Original/reference values are extracted from the original implementation. KeyBag variables are compared within aligned observable regions.",
        size=13,
        fill=MUTED,
    )
    svg.write(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path("results/agent-sanitized-copy-gpt5.5"))
    parser.add_argument("--out", type=Path, default=Path("results/agent-sanitized-copy-gpt5.5/quantity_quality_finding.svg"))
    parser.add_argument("--csv", type=Path, default=None)
    args = parser.parse_args()

    stats = load_stats(args.run_dir)
    build_figure(stats, args.out)
    csv_path = args.csv or args.out.with_suffix(".csv")
    write_csv(csv_path, stats)

    print(f"Wrote figure: {args.out}")
    print(f"Wrote data:   {csv_path}")
    for prompt in PROMPTS:
        row = stats[prompt]
        print(
            f"{PROMPT_LABELS[prompt]}: generated obs/cell={row.generated_obs_per_cell:.3f}, "
            f"Position F1={row.position_f1:.3f}, KeyBag F1={row.keybag_f1:.3f}, "
            f"generated KeyBag vars/cell={row.generated_keyvars_per_cell:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())