"""
obs-real-bench: hygiene filter + stratified sampling for newly mined repos.

Strategy (broad observability framing):
  - hygiene: drop test/spec files (path or filename match)
  - diversity: max 3 instances per source file (avoid go-kit logging.go-style flood)
  - balance: cap PER_REPO_CAP per repo (random.seed=42, stratified by source file)
  - keep: anything that mine_polyglot/mine accepted (any obs library — log/trace/metric)

Inputs:  /tmp/mine_staging_<tag>/*.json
Output:  instances/function/<id>.json  (only on --commit)

Usage:
  python -m tools.filter_and_sample              # dry-run report
  python -m tools.filter_and_sample --commit     # write to instances/function/
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PER_REPO_CAP = 100
PER_FILE_CAP = 3
RANDOM_SEED = 42

SOURCE_DIRS = {
    "trainticket": "/tmp/mine_staging_trainticket",
    "deathstar":   "/tmp/mine_staging_deathstar",
    "sockshop":    "/tmp/mine_staging_sockshop",
    "boutique":    "/tmp/mine_staging_boutique",
    # 2nd wave — polyglot booster repos
    "eshop":       "/tmp/mine_staging_eshop",
    "vector":      "/tmp/mine_staging_vector",
    "strapi":      "/tmp/mine_staging_strapi",
    "robusta":     "/tmp/mine_staging_robusta",
    # 3rd wave — TS-heavy booster
    "nestjs":      "/tmp/mine_staging_nestjs",
}
TARGET = ROOT / "instances" / "function"

# match common test-file naming across languages
TEST_FILE_RE = re.compile(
    r"(_test\.|_tests\.|\.test\.|\.spec\.|^test_|tests?\.java$|Test\.java$|Tests\.java$|TestImpl\.|IT\.java$|_spec\.rb$)",
    re.I,
)
TEST_PATH_RE = re.compile(
    r"(^|/)(test|tests|__tests__|spec|specs|integration[-_]?test)(/|$)",
    re.I,
)


def is_test_file(rel_path: str) -> bool:
    name = os.path.basename(rel_path)
    if TEST_FILE_RE.search(name):
        return True
    if TEST_PATH_RE.search(rel_path):
        return True
    return False


def load_all() -> dict[str, list[tuple[str, dict]]]:
    out: dict[str, list[tuple[str, dict]]] = {}
    for tag, src in SOURCE_DIRS.items():
        items: list[tuple[str, dict]] = []
        for fp in sorted(glob.glob(f"{src}/*.json")):
            base = os.path.basename(fp)
            if base.startswith("_"):  # _mine_manifest.json, _status.log
                continue
            try:
                d = json.load(open(fp))
            except Exception:
                continue
            f = d.get("target", {}).get("file", "")
            if not f or is_test_file(f):
                continue
            items.append((fp, d))
        out[tag] = items
    return out


def stratified_sample(items: list[tuple[str, dict]], cap: int, per_file_cap: int) -> list[tuple[str, dict]]:
    """Round-robin sample by source file, bounded by per_file_cap, total <= cap."""
    by_file: dict[str, list[tuple[str, dict]]] = {}
    for fp, d in items:
        by_file.setdefault(d["target"]["file"], []).append((fp, d))
    # truncate each file to per_file_cap (random pick within file)
    rng = random.Random(RANDOM_SEED)
    for f in by_file:
        if len(by_file[f]) > per_file_cap:
            by_file[f] = rng.sample(by_file[f], per_file_cap)
    # round-robin across files in random order
    files = sorted(by_file.keys())
    rng.shuffle(files)
    out: list[tuple[str, dict]] = []
    pos = {f: 0 for f in files}
    while len(out) < cap:
        progressed = False
        for f in files:
            if len(out) >= cap:
                break
            if pos[f] < len(by_file[f]):
                out.append(by_file[f][pos[f]])
                pos[f] += 1
                progressed = True
        if not progressed:
            break
    return out


def report(all_items: dict[str, list[tuple[str, dict]]], sampled: dict[str, list[tuple[str, dict]]]) -> None:
    print("=" * 78)
    print(f"{'repo':<14}{'raw':>8}{'after-hygiene':>16}{'after-cap':>12}")
    print("-" * 78)
    grand_raw = 0
    grand_kept = 0
    grand_sampled = 0
    raw_counts = {tag: 0 for tag in SOURCE_DIRS}
    for tag in SOURCE_DIRS:
        raw = len(list(glob.glob(f"{SOURCE_DIRS[tag]}/*.json")))
        raw -= len([p for p in glob.glob(f"{SOURCE_DIRS[tag]}/*.json") if os.path.basename(p).startswith("_")])
        raw_counts[tag] = raw
        kept = len(all_items[tag])
        sam = len(sampled[tag])
        grand_raw += raw
        grand_kept += kept
        grand_sampled += sam
        print(f"{tag:<14}{raw:>8}{kept:>16}{sam:>12}")
    print("-" * 78)
    print(f"{'TOTAL':<14}{grand_raw:>8}{grand_kept:>16}{grand_sampled:>12}")
    print()
    # language breakdown across all sampled
    by_lang: dict[str, int] = {}
    by_repo_lang: dict[str, dict[str, int]] = {}
    for tag, items in sampled.items():
        by_repo_lang[tag] = {}
        for _, d in items:
            l = d["target"]["language"]
            by_lang[l] = by_lang.get(l, 0) + 1
            by_repo_lang[tag][l] = by_repo_lang[tag].get(l, 0) + 1
    print("LANGUAGE DISTRIBUTION (sampled):")
    for l, n in sorted(by_lang.items(), key=lambda x: -x[1]):
        print(f"  {l:<12}{n:>6}")
    print()
    print("PER-REPO × LANGUAGE:")
    print(f"  {'':<14}", end="")
    langs = sorted(by_lang.keys())
    for l in langs:
        print(f"{l:>8}", end="")
    print()
    for tag in SOURCE_DIRS:
        print(f"  {tag:<14}", end="")
        for l in langs:
            print(f"{by_repo_lang[tag].get(l, 0):>8}", end="")
        print()


def commit(sampled: dict[str, list[tuple[str, dict]]]) -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    written = 0
    for tag, items in sampled.items():
        for fp, d in items:
            dst = TARGET / os.path.basename(fp)
            shutil.copy(fp, dst)
            written += 1
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="actually copy filtered instances into instances/function/")
    ap.add_argument("--per-repo-cap", type=int, default=PER_REPO_CAP)
    ap.add_argument("--per-file-cap", type=int, default=PER_FILE_CAP)
    ap.add_argument("--tag", action="append",
                    help="only process these tags (repeatable). Default: all SOURCE_DIRS.")
    args = ap.parse_args()

    if args.tag:
        unknown = [t for t in args.tag if t not in SOURCE_DIRS]
        if unknown:
            raise SystemExit(f"unknown tag(s): {unknown}. Known: {sorted(SOURCE_DIRS)}")
        # narrow SOURCE_DIRS in-place so load_all/report/commit only see selected tags
        for t in list(SOURCE_DIRS):
            if t not in args.tag:
                del SOURCE_DIRS[t]

    all_items = load_all()
    sampled = {tag: stratified_sample(items, args.per_repo_cap, args.per_file_cap)
               for tag, items in all_items.items()}

    report(all_items, sampled)

    if args.commit:
        n = commit(sampled)
        print()
        print(f"[committed] wrote {n} instance JSONs to {TARGET}")
    else:
        print()
        print("[dry-run] no files written. Re-run with --commit to materialise.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
