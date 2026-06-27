"""One-shot: walk all instances, attempt the strip step that pilot.py performs,
and mark any that fail with `_runnable: false` + `_skip_reason`.

This is purely a hygiene pass — it does NOT touch instances that already strip
cleanly. Re-runs are idempotent.

Usage:
    python -m tools._quarantine_bad_instances           # dry-run
    python -m tools._quarantine_bad_instances --commit  # write changes
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.strip import strip as do_strip  # noqa: E402

INSTANCES_DIR = ROOT / "instances" / "function"


def _resolve_source(inst: dict) -> str | None:
    """Mirror pilot._read_ground_truth: repo.local_path + target.file."""
    repo = inst.get("repo", {})
    tgt = inst.get("target", {})
    local = repo.get("local_path")
    file_rel = tgt.get("file")
    if local and file_rel:
        p = Path(local) / file_rel
        if p.exists():
            return p.read_text(errors="replace")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="Persist `_runnable: false` to disk. Otherwise dry-run.")
    args = ap.parse_args()

    reasons: Counter[str] = Counter()
    flagged: list[tuple[str, str]] = []
    ok = 0
    already_unrunnable = 0

    for path in sorted(INSTANCES_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            inst = json.loads(path.read_text())
        except Exception as e:
            reasons[f"parse-err: {type(e).__name__}"] += 1
            continue

        if inst.get("_runnable") is False:
            already_unrunnable += 1
            continue

        tgt = inst.get("target", {})
        lang = tgt.get("language")
        fn = tgt.get("function")

        src = _resolve_source(inst)
        if src is None:
            reasons["source-missing"] += 1
            flagged.append((path.stem, "source-missing"))
            continue

        try:
            do_strip(src, language=lang, function=fn)
            ok += 1
        except Exception as e:
            msg = str(e)
            kind = msg.split(":", 1)[0].strip() if ":" in msg else type(e).__name__
            # Trim verbose messages
            short = msg if len(msg) < 120 else msg[:117] + "..."
            reasons[kind] += 1
            flagged.append((path.stem, short))

    print(f"OK strip      : {ok}")
    print(f"already unrun.: {already_unrunnable}")
    print(f"to flag       : {len(flagged)}")
    print()
    print("Failure breakdown:")
    for k, n in reasons.most_common():
        print(f"  {n:4d}  {k}")
    print()
    print("Sample flagged (first 12):")
    for stem, reason in flagged[:12]:
        print(f"  {stem[:60]:60s}  -> {reason[:60]}")

    if args.commit and flagged:
        for stem, reason in flagged:
            path = INSTANCES_DIR / f"{stem}.json"
            inst = json.loads(path.read_text())
            inst["_runnable"] = False
            inst["_skip_reason"] = f"strip-fail: {reason}"
            path.write_text(json.dumps(inst, indent=2) + "\n")
        print(f"\n[commit] wrote _runnable=False to {len(flagged)} instances")
    elif flagged and not args.commit:
        print("\n(dry-run; re-run with --commit to write)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
