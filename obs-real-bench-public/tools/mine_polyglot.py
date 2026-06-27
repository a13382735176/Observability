"""
obs-real-bench: polyglot mining for opentelemetry-demo.

Same goal as `tools/mine.py` but spans Go / Java / TypeScript / JS / C# / C++ /
Ruby / Rust / PHP via tree-sitter. Generates instance JSONs that the existing
`results/` layout can consume.

WARNING: `tools/strip` and `tools/extract` are Python-only today, so non-Python
instances DO NOT run through the pilot pipeline yet. They are "frozen" candidate
records — useful for:

  (a) Documenting the addressable universe of obs-bearing functions in this repo.
  (b) Being ready to plug in per-language strippers / extractors later
      without re-discovering candidates.

Each instance JSON includes `_meta.span_byte_range` and `_meta.start_line` so a
future per-language stripper can find the function back deterministically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from tree_sitter_language_pack import get_parser
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "tree_sitter_language_pack not installed. Run:\n"
        "    pip install tree-sitter tree-sitter-language-pack"
    ) from e


# ---------------------------------------------------------------------------
# language config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LangCfg:
    short: str                 # used in instance id, e.g. 'go'
    full: str                  # used in instance.target.language, e.g. 'go'
    extensions: tuple[str, ...]
    fn_node_kinds: tuple[str, ...]
    # tree-sitter children fields that hold the symbol name
    name_fields: tuple[str, ...]
    obs_tokens: tuple[str, ...]


LANGS: dict[str, LangCfg] = {
    "go": LangCfg(
        short="go", full="go",
        extensions=(".go",),
        fn_node_kinds=("function_declaration", "method_declaration"),
        name_fields=("name",),
        obs_tokens=(
            "tracer.Start", ".SetAttributes(", ".AddEvent(", ".RecordError(", ".SetStatus(",
            "Counter.Add", "otel.", "logger.", "log.", "metric.", "Meter.", ".Record(",
        ),
    ),
    "java": LangCfg(
        short="java", full="java",
        extensions=(".java",),
        fn_node_kinds=("method_declaration", "constructor_declaration"),
        name_fields=("name",),
        obs_tokens=(
            "Span.current", ".spanBuilder", ".setAttribute(", ".addEvent(",
            ".counter(", ".histogram(", ".recordException(",
            "LOGGER.", "logger.", "log.",
        ),
    ),
    "typescript": LangCfg(
        short="ts", full="typescript",
        extensions=(".ts",),
        fn_node_kinds=(
            "function_declaration", "method_definition", "function_expression",
            "arrow_function",
        ),
        name_fields=("name",),
        obs_tokens=(
            "tracer.startSpan", "tracer.startActiveSpan", ".setAttribute(",
            ".addEvent(", ".recordException(", "counter.add(", "histogram.record(",
            "logger.", " log.", "diag.", "span.",
        ),
    ),
    "tsx": LangCfg(
        short="tsx", full="tsx",
        extensions=(".tsx",),
        fn_node_kinds=("function_declaration", "method_definition", "arrow_function"),
        name_fields=("name",),
        obs_tokens=(".setAttribute(", "logger.", "tracer.", "span."),
    ),
    "javascript": LangCfg(
        short="js", full="javascript",
        extensions=(".js",),
        fn_node_kinds=("function_declaration", "method_definition", "arrow_function"),
        name_fields=("name",),
        obs_tokens=("tracer.startSpan", ".setAttribute(", "logger.", "log.", "span."),
    ),
    "csharp": LangCfg(
        short="cs", full="csharp",
        extensions=(".cs",),
        fn_node_kinds=("method_declaration", "constructor_declaration"),
        name_fields=("name",),
        obs_tokens=(
            "ActivitySource", "Activity.Current", "AddTag", "SetTag",
            "Meter.Create", "_logger.", "logger.", "ILogger", ".LogInformation",
            ".LogWarning", ".LogError",
        ),
    ),
    "cpp": LangCfg(
        short="cpp", full="cpp",
        extensions=(".cpp", ".cc"),
        fn_node_kinds=("function_definition",),
        name_fields=("declarator",),  # nested; we'll extract symbol via regex fallback
        obs_tokens=("StartSpan", "SetAttribute", "AddEvent", "logger->"),
    ),
    "ruby": LangCfg(
        short="rb", full="ruby",
        extensions=(".rb",),
        fn_node_kinds=("method", "singleton_method"),
        name_fields=("name",),
        obs_tokens=("OpenTelemetry.tracer", "in_span", "set_attribute", "logger."),
    ),
    "rust": LangCfg(
        short="rs", full="rust",
        extensions=(".rs",),
        fn_node_kinds=("function_item",),
        name_fields=("name",),
        obs_tokens=("tracing::", "info_span!", "instrument", "info!", "warn!", "error!"),
    ),
    "php": LangCfg(
        short="php", full="php",
        extensions=(".php",),
        fn_node_kinds=("method_declaration", "function_definition"),
        name_fields=("name",),
        obs_tokens=("startSpan", "setAttribute", "->logger", "Tracer::"),
    ),
}


# ---------------------------------------------------------------------------
# tree-sitter helpers
# ---------------------------------------------------------------------------

EXCLUDE_PARTS = (
    "/node_modules/", "/vendor/", "/bin/", "/obj/", "/dist/", "/.next/",
    "/build/", "/target/", "/.gradle/", "/cmake-build", "/test/", "/Test",
    "/tests/", "/__pycache__/",
)
SKIP_FILE_SUFFIX = (".pb.go", ".d.ts", ".min.js")
SKIP_FILE_CONTAINS = ("_pb2",)


def _is_excluded(path: Path) -> bool:
    sp = str(path)
    if any(x in sp for x in EXCLUDE_PARTS):
        return True
    if any(path.name.endswith(s) for s in SKIP_FILE_SUFFIX):
        return True
    if any(s in path.name for s in SKIP_FILE_CONTAINS):
        return True
    return False


def _walk_nodes(node, fn_kinds, callback, depth: int = 0) -> None:
    if depth > 0 and node.kind() in fn_kinds:
        callback(node)
    for i in range(node.child_count()):
        _walk_nodes(node.child(i), fn_kinds, callback, depth + 1)


def _node_text(src_bytes: bytes, node) -> str:
    return src_bytes[node.start_byte():node.end_byte()].decode("utf-8", errors="replace")


def _find_named_child(node, field_names: tuple[str, ...]) -> Optional[object]:
    for fname in field_names:
        try:
            c = node.child_by_field_name(fname)
        except Exception:
            c = None
        if c is not None:
            return c
    return None


def _extract_symbol(node, src_bytes: bytes, lang: str) -> str:
    """Best-effort: derive the symbol name for a function/method node."""
    cfg = LANGS[lang]
    nm = _find_named_child(node, cfg.name_fields)
    if nm is not None:
        return _node_text(src_bytes, nm).strip()
    # cpp etc. — fall back to first identifier-ish token in the header
    text = _node_text(src_bytes, node)
    m = re.search(r"([A-Za-z_]\w*)\s*\(", text[:300])
    if m:
        return m.group(1)
    # last resort: short hash of byte range
    return f"anon_{hashlib.md5(text[:200].encode()).hexdigest()[:6]}"


def _ancestor_class(node) -> Optional[str]:
    """Walk parents looking for a class-like declaration; return its name text if any."""
    CLASS_KINDS = {
        "class_declaration", "class_specifier",
        "class",
        "namespace_declaration",
        "interface_declaration",
        "impl_item",
    }
    p = node.parent() if callable(node.parent) else node.parent
    while p is not None:
        if p.kind() in CLASS_KINDS:
            nm = _find_named_child(p, ("name", "type"))
            if nm is not None:
                return _node_text(_src_cache, nm).strip()
            return None
        p = p.parent() if callable(p.parent) else p.parent
    return None


# we use a module-level cache so _ancestor_class can read source bytes;
# set by mine_file().
_src_cache: bytes = b""


# ---------------------------------------------------------------------------
# main miner
# ---------------------------------------------------------------------------

@dataclass
class Cand:
    file_rel: str
    lang: str
    symbol: str
    class_name: Optional[str]
    start_byte: int
    end_byte: int
    start_line: int          # 1-based
    n_lines: int
    n_obs_tokens: int        # how many distinct obs tokens matched


def mine_file(file_abs: Path, file_rel: str, lang: str, *, min_lines: int) -> list[Cand]:
    cfg = LANGS[lang]
    parser = get_parser(cfg.full if lang != "csharp" else "csharp")
    try:
        src = file_abs.read_text(errors="replace")
    except Exception:
        return []
    try:
        tree = parser.parse(src)
    except Exception:
        return []
    src_bytes = src.encode("utf-8", errors="replace")

    global _src_cache
    _src_cache = src_bytes

    out: list[Cand] = []

    def cb(node):
        body_text = _node_text(src_bytes, node)
        n_lines = body_text.count("\n") + 1
        if n_lines < min_lines:
            return
        matches = sum(1 for t in cfg.obs_tokens if t in body_text)
        if matches == 0:
            return
        symbol = _extract_symbol(node, src_bytes, lang)
        cls = _ancestor_class(node)
        out.append(Cand(
            file_rel=file_rel,
            lang=lang,
            symbol=symbol,
            class_name=cls,
            start_byte=node.start_byte(),
            end_byte=node.end_byte(),
            start_line=node.start_position().row + 1,
            n_lines=n_lines,
            n_obs_tokens=matches,
        ))

    _walk_nodes(tree.root_node(), cfg.fn_node_kinds, cb)
    return out


def mine_repo(repo_root: Path, langs: list[str], min_lines: int) -> list[Cand]:
    candidates: list[Cand] = []
    for lang in langs:
        cfg = LANGS[lang]
        for ext in cfg.extensions:
            for p in repo_root.rglob(f"*{ext}"):
                if _is_excluded(p):
                    continue
                file_rel = str(p.relative_to(repo_root))
                candidates.extend(mine_file(p, file_rel, lang, min_lines=min_lines))
    return candidates


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def build_instance(cand: Cand, repo_name: str, repo_local: str, tag: str) -> dict:
    # service short name = first path component after `src/`
    parts = cand.file_rel.split("/")
    service = parts[1].replace("-", "_") if len(parts) > 1 and parts[0] == "src" else "misc"
    short = LANGS[cand.lang].short
    sym = _slug(cand.symbol)
    cls = _slug(cand.class_name) if cand.class_name else None
    file_stem = _slug(Path(cand.file_rel).stem)
    label = f"{cls}_{sym}" if cls else sym
    instance_id_core = f"{tag}__{short}__{service}__{file_stem}__{label}__L{cand.start_line}"
    full_id = f"{instance_id_core}-v1"
    return {
        "instance_id": full_id,
        "schema_version": "0.1",
        "tier": "function",
        "_auto_mined": True,
        "_runnable": True,
        "repo": {
            "name": repo_name,
            "local_path": repo_local,
            "_base_commit": "local-checkout",
        },
        "target": {
            "language": LANGS[cand.lang].full,
            "file": cand.file_rel,
            "function": f"{cand.class_name}.{cand.symbol}" if cand.class_name else cand.symbol,
        },
        "task": {
            "available_imports": [],
        },
        "_meta": {
            "service": service,
            "class": cand.class_name,
            "symbol": cand.symbol,
            "start_line": cand.start_line,
            "n_lines": cand.n_lines,
            "n_obs_tokens": cand.n_obs_tokens,
            "span_byte_range": [cand.start_byte, cand.end_byte],
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="../source_repos/open-telemetry__opentelemetry-demo")
    ap.add_argument("--repo-name", default="open-telemetry/opentelemetry-demo")
    ap.add_argument("--tag", default="otel-demo")
    ap.add_argument("--min-lines", type=int, default=4)
    ap.add_argument("--langs", default="go,java,typescript,javascript,csharp,cpp,ruby,rust,php")
    ap.add_argument("--out", default="instances/function")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo).resolve()
    out_dir = Path(args.out).resolve() if Path(args.out).is_absolute() else (Path.cwd() / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    requested_langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    for l in requested_langs:
        if l not in LANGS:
            raise SystemExit(f"unknown lang: {l}. Known: {sorted(LANGS)}")

    cands = mine_repo(repo_root, requested_langs, args.min_lines)
    print(f"discovered {len(cands)} non-Python candidates across {len(requested_langs)} languages")
    by_lang: dict[str, int] = {}
    for c in cands:
        by_lang[c.lang] = by_lang.get(c.lang, 0) + 1
    for l, n in sorted(by_lang.items(), key=lambda x: -x[1]):
        print(f"  {l:10s} {n:4d}")

    seen_ids: set[str] = set()
    written = 0
    skipped = 0
    rows = []
    for c in cands:
        doc = build_instance(c, args.repo_name, str(repo_root), args.tag)
        iid = doc["instance_id"].rsplit("-v", 1)[0]
        if iid in seen_ids:
            continue
        seen_ids.add(iid)
        out_path = out_dir / f"{iid}.json"
        rows.append({
            "id": iid,
            "lang": c.lang,
            "file": c.file_rel,
            "symbol": c.symbol,
            "class": c.class_name,
            "n_lines": c.n_lines,
            "n_obs_tokens": c.n_obs_tokens,
        })
        if out_path.exists() and not args.overwrite:
            skipped += 1
            continue
        if not args.dry_run:
            out_path.write_text(json.dumps(doc, indent=2) + "\n")
            written += 1

    print(f"\nwrote={written} skipped_existing={skipped}")
    manifest = out_dir / "_polyglot_manifest.json"
    manifest.write_text(json.dumps({
        "n_candidates": len(cands),
        "by_lang": by_lang,
        "rows": rows,
    }, indent=2) + "\n")
    print(f"manifest -> {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
