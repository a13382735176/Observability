"""
obs-real-bench: auto-mine candidate function-tier instances from a Python source tree.

For every .py file under one or more service roots, find each
top-level function or class method that

    (a) is non-trivial   — body has >= MIN_STMTS statements after stripping obs
    (b) contains obs     — at least one tracer/logger/meter call or `with tracer.start_*`
    (c) parses cleanly   — `ast.parse` succeeds

and emit an `instances/function/<instance_id>.json` describing it. The pilot
runner can then run strip + extract + score on each instance unchanged.

CLI:

    python -m tools.mine --repo ../source_repos/open-telemetry__opentelemetry-demo \
                        --service src/load-generator \
                        --service src/product-reviews \
                        --service src/llm \
                        --service src/recommendation \
                        --tag otel-demo --lang py \
                        --out instances/function

    python -m tools.mine --all-otel-demo                  # convenience preset
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from tools.strip.python_strip import _is_obs_call, _is_obs_assignment  # noqa: E402


# ---------------------------------------------------------------------------
# obs detection (broad; matches what score_anchor uses)
# ---------------------------------------------------------------------------

_OBS_WORD_TOKENS = {
    "span", "spans",
    "tracer", "tracers", "trace", "traces",
    "logger", "log",
    "meter", "counter", "histogram", "gauge",
    "metric", "metrics",
    "telemetry", "otel",
    "instrument", "instruments", "instr",
}


def _name_chain(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name_chain(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        prefix = _name_chain(node.value)
        return f"{prefix}[*]" if prefix else "[*]"
    if isinstance(node, ast.Call):
        return _name_chain(node.func)
    return ""


def _name_tokens(name: str) -> set[str]:
    if not name:
        return set()
    s = name
    for c in ".[]*() \t":
        s = s.replace(c, "_")
    return {t.lower() for t in s.split("_") if t}


def _is_obs_via_helper(stmt: ast.stmt) -> bool:
    """Catch helper-wrapped obs, e.g. `_set_span_attribute(...)` or `record_metric(...)`."""
    for child in ast.walk(stmt):
        if isinstance(child, ast.Call):
            chain = _name_chain(child.func)
            toks = _name_tokens(chain)
            if toks & _OBS_WORD_TOKENS:
                return True
    return False


def _is_tracer_with(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.With):
        return False
    for item in stmt.items:
        ctx = item.context_expr
        if isinstance(ctx, ast.Call):
            chain = _name_chain(ctx.func)
            if any(p in chain.lower() for p in (".start_as_current_span", ".start_span", "tracer.")):
                return True
            toks = _name_tokens(chain)
            if "tracer" in toks or "span" in toks:
                return True
    return False


def _function_has_obs(fn: ast.AST) -> bool:
    for stmt in ast.walk(fn):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            if _is_obs_call(stmt) or _is_obs_via_helper(stmt):
                return True
        elif isinstance(stmt, ast.Assign):
            if _is_obs_assignment(stmt) or _is_obs_via_helper(stmt):
                return True
        elif isinstance(stmt, ast.With):
            if _is_tracer_with(stmt):
                return True
            # also detect obs calls inside the with-block
            for child in stmt.body:
                if _is_obs_via_helper(child):
                    return True
    return False


# ---------------------------------------------------------------------------
# function discovery
# ---------------------------------------------------------------------------

@dataclass
class FunctionCandidate:
    file_rel: str          # relative to repo root
    file_abs: str          # absolute path
    func_label: str        # 'foo' or 'Bar.baz'
    plain_name: str        # 'foo' or 'baz'
    class_name: Optional[str]
    n_stmts: int           # statements in body (recursive walk count)
    has_async: bool


def _iter_class_methods(cls: ast.ClassDef) -> Iterable[ast.AST]:
    for item in cls.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield item


def _walk_functions(tree: ast.Module) -> Iterable[tuple[Optional[str], ast.AST]]:
    """Yield (class_name_or_None, fn_node) for top-level fns and class methods."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield (None, node)
        elif isinstance(node, ast.ClassDef):
            for m in _iter_class_methods(node):
                yield (node.name, m)


def _count_real_stmts(fn: ast.AST) -> int:
    """Count statements in body, recursively, excluding pure docstrings & pass."""
    n = 0
    for s in ast.walk(fn):
        if isinstance(s, ast.stmt) and s is not fn:
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str):
                continue  # docstring
            if isinstance(s, ast.Pass):
                continue
            n += 1
    return n


def discover_in_file(
    file_abs: Path,
    file_rel: str,
    *,
    min_stmts: int,
    skip_dunder: bool,
) -> list[FunctionCandidate]:
    try:
        tree = ast.parse(file_abs.read_text())
    except (SyntaxError, ValueError):
        return []

    out: list[FunctionCandidate] = []
    for cls_name, fn in _walk_functions(tree):
        name: str = fn.name  # type: ignore[attr-defined]
        if skip_dunder and name.startswith("__") and name.endswith("__"):
            continue
        if not _function_has_obs(fn):
            continue
        n_stmts = _count_real_stmts(fn)
        if n_stmts < min_stmts:
            continue
        label = f"{cls_name}.{name}" if cls_name else name
        out.append(FunctionCandidate(
            file_rel=file_rel,
            file_abs=str(file_abs),
            func_label=label,
            plain_name=name,
            class_name=cls_name,
            n_stmts=n_stmts,
            has_async=isinstance(fn, ast.AsyncFunctionDef),
        ))
    return out


# ---------------------------------------------------------------------------
# instance JSON synthesis
# ---------------------------------------------------------------------------

def _module_imports(file_abs: Path) -> list[str]:
    """Return verbatim import lines (top-level only) plus interesting module-level globals."""
    src = file_abs.read_text()
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return []
    imports: list[str] = []
    interesting_globals: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(ast.unparse(node))
        elif isinstance(node, ast.Assign):
            # module-level assignments that *look* obs-related
            for t in node.targets:
                if isinstance(t, ast.Name):
                    tokens = _name_tokens(t.id)
                    if tokens & _OBS_WORD_TOKENS:
                        interesting_globals.append(f"{t.id}  (module-level)")
    return imports + interesting_globals


def make_instance_json(
    cand: FunctionCandidate,
    repo_name: str,
    repo_local: str,
    tag: str,
    lang_short: str,
    service: str,
) -> dict:
    """Build the instance JSON document for one candidate."""
    available_imports = _module_imports(Path(cand.file_abs))

    instance_id = build_instance_id(tag, lang_short, service, cand)

    return {
        "instance_id": f"{instance_id}-v1",
        "schema_version": "0.1",
        "tier": "function",
        "_auto_mined": True,
        "repo": {
            "name": repo_name,
            "local_path": repo_local,
            "_base_commit": "local-checkout",
        },
        "target": {
            "language": "python",
            "file": cand.file_rel,
            "function": cand.func_label,
        },
        "task": {
            "available_imports": available_imports,
        },
        "_meta": {
            "n_stmts": cand.n_stmts,
            "is_async": cand.has_async,
            "class": cand.class_name,
            "service": service,
        },
    }


def build_instance_id(tag: str, lang_short: str, service: str, cand: FunctionCandidate) -> str:
    """
    Produce a filename-safe instance id.

    Format: <tag>__<lang>__<service>__<func_label>
    where func_label collapses '.' to '_' (e.g. RecommendationService.ListRecommendations
    -> RecommendationService_ListRecommendations).

    NOTE: an older hand-built convention dropped the class prefix for top-level
    services. To keep file-name uniqueness deterministic we ALWAYS include the
    class prefix in auto-mined ids.
    """
    label = cand.func_label.replace(".", "_")
    return f"{tag}__{lang_short}__{service}__{label}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

OTEL_DEMO_REPO = Path("../source_repos/open-telemetry__opentelemetry-demo")

OTEL_DEMO_SERVICES = [
    # (relative_service_dir, service_short_name)
    ("src/load-generator", "load_generator"),
    ("src/product-reviews", "product_reviews"),
    ("src/llm", "llm"),
    ("src/recommendation", "recommendation"),
]

SKIP_FILE_RE = ("_pb2.py", "_pb2_grpc.py")


def _service_files(repo_root: Path, service_rel: str) -> list[tuple[Path, str]]:
    """Return (abs_path, repo_relative_path) for every .py file under service_rel."""
    base = repo_root / service_rel
    out = []
    for p in sorted(base.rglob("*.py")):
        if any(p.name.endswith(s) for s in SKIP_FILE_RE):
            continue
        rel = str(p.relative_to(repo_root))
        out.append((p, rel))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="Absolute path to repo root.", default=str(OTEL_DEMO_REPO))
    ap.add_argument(
        "--service",
        action="append",
        help="repo-relative service directory (e.g. src/recommendation). Repeatable.",
    )
    ap.add_argument("--tag", default="otel-demo", help="Repo tag (e.g. otel-demo).")
    ap.add_argument("--lang", default="py", help="Language short code in instance id.")
    ap.add_argument("--repo-name", default="open-telemetry/opentelemetry-demo")
    ap.add_argument("--min-stmts", type=int, default=4, help="Minimum body statements.")
    ap.add_argument("--out", default="instances/function", help="Output dir for JSONs.")
    ap.add_argument("--all-otel-demo", action="store_true", help="Preset: scan all 4 OTel-demo Py services.")
    ap.add_argument("--overwrite", action="store_true", help="Allow overwriting existing JSONs.")
    ap.add_argument("--dry-run", action="store_true", help="List but do not write.")
    args = ap.parse_args()

    repo_root = Path(args.repo).resolve()

    # decide service list
    if args.all_otel_demo:
        services = OTEL_DEMO_SERVICES
    elif args.service:
        services = [(s, Path(s).name.replace("-", "_")) for s in args.service]
    else:
        ap.error("specify --service ... (repeatable) OR --all-otel-demo")

    out_dir = (Path.cwd() / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[tuple[FunctionCandidate, str]] = []  # (cand, service_short)
    for service_rel, service_short in services:
        for file_abs, file_rel in _service_files(repo_root, service_rel):
            cands = discover_in_file(
                file_abs, file_rel,
                min_stmts=args.min_stmts,
                skip_dunder=True,
            )
            for c in cands:
                candidates.append((c, service_short))

    print(f"discovered {len(candidates)} candidate functions across {len(services)} service(s).")

    written = 0
    skipped = 0
    duplicates = 0
    summary_rows: list[dict] = []
    seen_ids: set[str] = set()

    for cand, service_short in candidates:
        doc = make_instance_json(
            cand,
            repo_name=args.repo_name,
            repo_local=str(repo_root),
            tag=args.tag,
            lang_short=args.lang,
            service=service_short,
        )
        instance_id = doc["instance_id"].rsplit("-v", 1)[0]
        if instance_id in seen_ids:
            duplicates += 1
            continue
        seen_ids.add(instance_id)

        out_path = out_dir / f"{instance_id}.json"
        if out_path.exists() and not args.overwrite:
            skipped += 1
            summary_rows.append({"id": instance_id, "status": "skipped-exists",
                                 "file": cand.file_rel, "func": cand.func_label, "n_stmts": cand.n_stmts})
            continue
        if not args.dry_run:
            out_path.write_text(json.dumps(doc, indent=2) + "\n")
        written += 1
        summary_rows.append({"id": instance_id, "status": "written",
                             "file": cand.file_rel, "func": cand.func_label, "n_stmts": cand.n_stmts})

    print(f"wrote={written}  skipped_existing={skipped}  duplicates={duplicates}")
    if args.dry_run:
        print("(dry-run: no files written)")

    # also dump a manifest for traceability
    manifest = out_dir / "_mine_manifest.json"
    manifest.write_text(json.dumps({
        "services": [s for s, _ in services],
        "n_discovered": len(candidates),
        "n_written": written,
        "n_skipped": skipped,
        "n_duplicates": duplicates,
        "rows": summary_rows,
    }, indent=2) + "\n")
    print(f"manifest -> {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
