"""
obs-real-bench: instance builder.

Walks a pinned source repo and produces instance JSON files under
instances/{tier}/. Does NOT modify the source repo — repos/ is read-only.

Pipeline (per candidate target):

    1. Identify target (function / file / system) — driven either by:
         (a) hand-written specs/*.yaml (preferred for hand-pilot)
         (b) heuristic auto-discovery (later)
    2. Read ground-truth source from repos/<repo>@<base_commit>.
    3. Run language-specific stripper -> stripped source.
    4. Compute unified diff (ground_truth -> stripped) = obs_patch.
       Note the diff direction: applying obs_patch to ground_truth gives stripped.
    5. Run language-specific extractor over ground_truth -> obs_sites list.
    6. Emit instances/<tier>/<instance_id>.json.

Skeleton only. The stripper and extractor are not yet implemented.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
INSTANCES = ROOT / "instances"
REPOS = ROOT / "repos"


@dataclass
class BuildTarget:
    tier: str          # "function" | "file" | "system"
    repo_name: str
    base_commit: str
    language: str
    files: list[str]
    function: str | None  # None for file/system tier
    prompt_level: str
    extra: dict[str, Any]


def load_spec(spec_path: Path) -> list[BuildTarget]:
    """Load a hand-written target spec (YAML) into BuildTarget records.

    TODO: implement YAML loader. For now this raises so the file is obviously
    incomplete.
    """
    raise NotImplementedError(
        "load_spec: hand-written spec loader not implemented yet. "
        "For the hand-pilot you can build instances directly by editing "
        "instances/{tier}/*.json files."
    )


def strip_observability(source: str, language: str, function: str | None) -> str:
    """Remove observability calls from source, preserving everything else.

    TODO: dispatch to tools.strip.<language>. For multi-language support we
    plan to use tree-sitter so the matching logic is shared.
    """
    raise NotImplementedError(
        f"strip_observability: stripper for language={language!r} not implemented yet."
    )


def extract_obs_sites(source: str, language: str, function: str | None) -> list[dict]:
    """Return list of ObsSite records extracted from source.

    See README.md for the ObsSite schema. TODO: dispatch to
    tools.extract.<language>.
    """
    raise NotImplementedError(
        f"extract_obs_sites: extractor for language={language!r} not implemented yet."
    )


def make_obs_patch(ground_truth: str, stripped: str, file_path: str) -> str:
    """Return a unified diff that, when applied to ground_truth, produces stripped."""
    import difflib
    diff = difflib.unified_diff(
        ground_truth.splitlines(keepends=True),
        stripped.splitlines(keepends=True),
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
    )
    return "".join(diff)


def build_one(target: BuildTarget) -> dict:
    """Build a single instance dict from a target.

    Skeleton — pieces marked TODO when their dependencies are missing.
    """
    repo_root = REPOS / target.repo_name.replace("/", "__")
    if not repo_root.exists():
        sys.stderr.write(
            f"[warn] repo not cloned: {target.repo_name} -> {repo_root}. "
            "Run `git clone --depth 1 ...` into repos/ first.\n"
        )

    # For now: we only emit the *shape* of the instance. Real content goes in
    # once strip / extract land.
    primary_file = target.files[0]
    instance = {
        "instance_id": f"{target.repo_name.replace('/', '_')}__{target.language}__"
                       f"{(target.function or 'file')}-v1",
        "schema_version": "0.1",
        "tier": target.tier,
        "repo": {
            "name": target.repo_name,
            "base_commit": target.base_commit,
            "local_path": f"repos/{target.repo_name.replace('/', '__')}",
        },
        "target": {
            "language": target.language,
            "file": primary_file if target.tier == "function" else None,
            "files": target.files if target.tier != "function" else None,
            "function": target.function,
        },
        "task": {
            "prompt_level": target.prompt_level,
            "obs_patch": "TODO_GENERATE_AFTER_STRIPPER_LANDS",
            "available_imports": target.extra.get("available_imports", []),
        },
        "ground_truth": {
            "obs_sites": "TODO_GENERATE_AFTER_EXTRACTOR_LANDS",
        },
        "metadata": {
            "created_by": "build_instances.py",
            "created_at": "",
            "notes": "skeleton output — stripper and extractor not yet wired",
        },
    }
    return instance


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build obs-real-bench instances from a target spec."
    )
    parser.add_argument(
        "--spec",
        type=Path,
        required=True,
        help="Path to a YAML target spec (not implemented yet — placeholder).",
    )
    parser.add_argument(
        "--tier",
        choices=["function", "file", "system"],
        required=True,
        help="Which tier to write into.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print instances to stdout instead of writing files.",
    )
    args = parser.parse_args()

    targets = load_spec(args.spec)  # raises NotImplementedError today
    out_dir = INSTANCES / args.tier
    out_dir.mkdir(parents=True, exist_ok=True)

    for tgt in targets:
        inst = build_one(tgt)
        if args.dry_run:
            json.dump(inst, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            path = out_dir / f"{inst['instance_id']}.json"
            path.write_text(json.dumps(inst, indent=2) + "\n")
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
