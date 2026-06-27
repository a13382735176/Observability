"""
Compute and persist "sibling" functions for every instance.

A sibling is a function that lives in the same source file as the instance
target and itself has observability calls in the ground-truth source
(``n_gt > 0``). Siblings are the style anchor a real engineer would consult
("how do other functions in this file do obs?"), so they are the natural
context for few-shot prompts such as ``p_fewshot``.

This script does NOT change the prompt or the pilot. It only enriches each
``instances/function/*.json`` file with a new top-level field::

    "siblings": [
        {"function": "foo", "n_gt": 4},
        {"function": "Bar.method", "n_gt": 2},
        ...
    ]

ranked by ``n_gt`` descending (more obs = better style anchor), with the
target function itself excluded. Ties are broken by function name for
stable output across runs.

Why store the full ranked list (not just top-K)?
    The K parameter belongs to the experiment, not the bench. We want to
    run K=1, K=2, K=5 ablations later by editing prompt frontmatter, not
    by re-running this script. We do cap to ``--K`` (default 5) just to
    keep the JSON small and to avoid expanding ``available_imports``-style
    fields.

CLI::

    python -m tools.build_siblings           # K=5, all instances
    python -m tools.build_siblings --K 10
    python -m tools.build_siblings --language python --dry-run
    python -m tools.build_siblings --instance otel-demo__py__recommendation__getJSONLogger

Currently Python-only. Polyglot siblings land when polyglot extractors do.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

# Make sure we can import sibling tools package whether invoked as
# ``python -m tools.build_siblings`` or directly.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.extract import extract as extract_obs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INSTANCES_DIR = ROOT / "instances" / "function"


# ---------------------------------------------------------------------------
# enumeration
# ---------------------------------------------------------------------------

def _enumerate_function_names(source: str, *, language: str = "python") -> list[str]:
    """Return every function name in the file, including one level of method
    nesting (``Class.method``). Matches the shape ``instance.target.function``
    uses, so the candidate names we score are directly comparable to the
    target name.

    For non-Python languages, dispatches to a tree-sitter-based enumerator.
    """
    if language.lower() in ("python", "py"):
        tree = ast.parse(source)
        names: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(node.name)
                continue
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        names.append(f"{node.name}.{sub.name}")
        return names

    # tree-sitter path
    from tools import ts_obs
    from tools.langspec import require as require_langspec
    spec = require_langspec(language)
    src_bytes = source.encode("utf-8")
    tree = ts_obs.parse(source, language)
    names = []
    for node in ts_obs.walk_descendants(tree.root_node(), named_only=True):
        if node.kind() not in spec.fn_kinds:
            continue
        nm = None
        for field in spec.fn_name_fields:
            c = ts_obs.child_by_field_name(node, field)
            if c is not None:
                nm = ts_obs.node_text(c, src_bytes).strip()
                break
        if not nm:
            continue
        # is it inside a class?
        cls = None
        p = node.parent()
        while p is not None:
            if p.kind() in spec.class_kinds:
                cls_id = ts_obs.child_by_field_name(p, "name")
                if cls_id is not None:
                    cls = ts_obs.node_text(cls_id, src_bytes).strip()
                break
            p = p.parent()
        names.append(f"{cls}.{nm}" if cls else nm)
    return names


def _score_siblings(
    source: str,
    target_function: str,
    max_keep: int,
    *,
    language: str = "python",
) -> list[dict]:
    """Score every candidate function in ``source`` by its obs-site count
    in the ground truth, drop the target itself and any with ``n_gt == 0``,
    sort by (n_gt desc, function name asc) for a stable ranking, and keep
    at most ``max_keep`` of them.
    """
    candidates = _enumerate_function_names(source, language=language)
    scored: list[tuple[int, str]] = []
    for name in candidates:
        if name == target_function:
            continue
        try:
            sites = extract_obs(source, language=language, function=name)
        except (ValueError, SyntaxError):
            # Some odd shapes (decorators we don't understand, etc.) can
            # break extract; skip silently — those just won't be siblings.
            continue
        n_gt = len(sites)
        if n_gt <= 0:
            continue
        scored.append((n_gt, name))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [{"function": name, "n_gt": n_gt} for n_gt, name in scored[:max_keep]]


# ---------------------------------------------------------------------------
# per-instance + driver
# ---------------------------------------------------------------------------

def _process_instance(
    inst_path: Path,
    *,
    max_keep: int,
    dry_run: bool,
) -> tuple[list[dict], str]:
    """Update one instance file. Returns ``(siblings, status)`` for the
    driver to report on. ``status`` is one of: ``ok``, ``skip-lang``,
    ``skip-noread``, ``err-parse``. ``siblings`` is empty for non-``ok``.
    """
    inst = json.loads(inst_path.read_text())
    language = (inst.get("target", {}) or {}).get("language", "").lower()
    # accept every language that has a langspec entry
    from tools.langspec import get as _get_langspec
    if _get_langspec(language) is None:
        return [], "skip-lang"

    repo = inst.get("repo", {}) or {}
    file_rel = (inst.get("target", {}) or {}).get("file")
    target_fn = (inst.get("target", {}) or {}).get("function")
    if not (repo.get("local_path") and file_rel and target_fn):
        return [], "skip-noread"

    file_abs = Path(repo["local_path"]) / file_rel
    if not file_abs.exists():
        return [], "skip-noread"
    try:
        source = file_abs.read_text()
    except OSError:
        return [], "skip-noread"

    try:
        siblings = _score_siblings(source, target_fn, max_keep, language=language)
    except SyntaxError:
        return [], "err-parse"

    inst["siblings"] = siblings
    if not dry_run:
        inst_path.write_text(json.dumps(inst, indent=2) + "\n")
    return siblings, "ok"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Enrich instance JSON files with a ranked sibling list "
                    "of obs-bearing functions in the same file."
    )
    ap.add_argument(
        "--K", type=int, default=5,
        help="Maximum number of siblings to record per instance "
             "(ranked by n_gt desc). The actual k used at render time is "
             "set by the prompt's frontmatter. Default: 5.",
    )
    ap.add_argument(
        "--language", default="python",
        help="Only process instances with this language. Default: python.",
    )
    ap.add_argument(
        "--instance", default=None,
        help="Process only this single instance (id without .json).",
    )
    ap.add_argument(
        "--instances-dir", type=Path, default=INSTANCES_DIR,
        help="Directory containing instance JSON files.",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Compute and print sibling lists but do NOT write JSON back.",
    )
    args = ap.parse_args()

    if args.instance:
        paths = [args.instances_dir / f"{args.instance}.json"]
        if not paths[0].exists():
            print(f"[err] instance not found: {paths[0]}", file=sys.stderr)
            return 2
    else:
        paths = sorted(args.instances_dir.glob("*.json"))
        paths = [p for p in paths if not p.name.startswith("_")]

    totals = {"ok": 0, "skip-lang": 0, "skip-noread": 0, "err-parse": 0}
    sib_counts: list[int] = []
    for p in paths:
        # quick language gate without reading repo just to save IO on the
        # 60+ non-Python instances in the corpus
        try:
            head = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        lang = (head.get("target", {}) or {}).get("language", "").lower()
        if lang not in ("python", "py") and args.language.lower() in ("python", "py"):
            totals["skip-lang"] += 1
            continue

        siblings, status = _process_instance(
            p, max_keep=args.K, dry_run=args.dry_run
        )
        totals[status] += 1
        if status == "ok":
            n_sibs = len(siblings)
            sib_counts.append(n_sibs)
            sib_str = ", ".join(
                f"{s['function']}({s['n_gt']})" for s in siblings[:5]
            )
            print(
                f"[{'dry-run' if args.dry_run else 'wrote'}] "
                f"{p.stem} -> {n_sibs} siblings"
                + (f"   {sib_str}" if n_sibs else ""),
                flush=True,
            )

    print(
        f"\n[build_siblings] processed: ok={totals['ok']} "
        f"skip-lang={totals['skip-lang']} skip-noread={totals['skip-noread']} "
        f"err-parse={totals['err-parse']}",
        flush=True,
    )
    if sib_counts:
        mean = sum(sib_counts) / len(sib_counts)
        nzero = sum(1 for c in sib_counts if c == 0)
        print(
            f"[build_siblings] siblings/instance: "
            f"mean={mean:.2f}  min={min(sib_counts)}  max={max(sib_counts)}  "
            f"instances with 0 siblings={nzero}/{len(sib_counts)}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
