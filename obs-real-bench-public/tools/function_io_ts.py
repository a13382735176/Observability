"""
Tree-sitter-based function I/O for polyglot pipelines.

Mirrors the four public helpers in `function_io.py` (Python) for any language
present in `tools.langspec`. Public API:

    extract_target_function(source, function, language)        -> str
    extract_module_context(source, function, language, ...)    -> str
    splice_function(stripped, function, new_block, language)   -> str
    extract_code_from_response(response, language)             -> str

Design notes
------------
- The text-edit philosophy from `ts_strip.py` carries over: we slice the
  function's byte range out of the original source and return it AS-IS. No
  dedent is done because non-Python languages keep top-level functions at
  column 0, and Java/C# methods at column 4 (a 4-space indent inside a
  class) are best left indented so the LLM sees the actual style.
- `extract_module_context` collects imports + module-level obs declarations
  using tree-sitter shape detection plus the same name-suffix lexicon used
  by Python.
"""
from __future__ import annotations

import re
from typing import Optional

from . import ts_obs
from .langspec import LangSpec, require as require_langspec


# ---------------------------------------------------------------------------
# import-statement detection (per-language)
# ---------------------------------------------------------------------------

# Node kinds that hold import-like declarations, by language.
_IMPORT_KINDS: dict[str, tuple[str, ...]] = {
    "go": ("import_declaration",),
    "java": ("import_declaration",),
    "typescript": ("import_statement", "import_alias", "import_clause"),
    "javascript": ("import_statement", "import_alias"),
    "csharp": ("using_directive",),
}


# Obs-marker substrings reused across languages (case-insensitive).
_OBS_IMPORT_MARKERS = (
    "opentelemetry", "otel",
    "prometheus",
    "jaeger",
    "structlog", "loguru", "logbook",
    "zerolog", "zap", "logrus", "slog",
    "log4j", "slf4j", "logback",
    "winston", "pino", "bunyan",
    "serilog", "nlog",
    "trace", "telemetry",
)


def _import_kinds_for(spec: LangSpec) -> tuple[str, ...]:
    return _IMPORT_KINDS.get(spec.name, ("import_declaration", "import_statement"))


def _looks_obs_import(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _OBS_IMPORT_MARKERS)


# ---------------------------------------------------------------------------
# module-level obs declarations (var/const/private static final/etc.)
# ---------------------------------------------------------------------------

# Per-language node kinds for "module-level declarations" worth scanning.
_DECL_KINDS: dict[str, tuple[str, ...]] = {
    "go": ("var_declaration", "const_declaration", "short_var_declaration"),
    "java": ("field_declaration",),
    "typescript": ("lexical_declaration", "variable_declaration"),
    "javascript": ("lexical_declaration", "variable_declaration"),
    "csharp": ("field_declaration",),
}


_OBS_LHS_NAMES = {
    "tracer", "meter", "logger", "log", "instruments",
    "tracer_provider", "meter_provider", "logger_provider",
    "Tracer", "Meter", "Logger", "Log",  # Capitalised variants for Go / C# / Java
}
_OBS_LHS_SUFFIXES = (
    "_tracer", "_meter", "_logger", "_log",
    "_counter", "_histogram", "_gauge", "_metrics",
    "_instruments", "_observer",
    "Tracer", "Meter", "Logger", "Counter", "Histogram",  # camelCase
)


def _name_matches_obs(name: str) -> bool:
    if name in _OBS_LHS_NAMES:
        return True
    low = name.lower()
    if low in {n.lower() for n in _OBS_LHS_NAMES}:
        return True
    return any(name.endswith(suf) for suf in _OBS_LHS_SUFFIXES) or any(
        low.endswith(suf.lower()) for suf in _OBS_LHS_SUFFIXES
    )


def _decl_smells_obs(decl_node, spec: LangSpec, src_bytes: bytes) -> bool:
    """True iff a module-level decl looks obs-related (by LHS name or RHS hints)."""
    text = ts_obs.node_text(decl_node, src_bytes)
    low = text.lower()
    for h in (
        "tracer", "meter", "logger",
        "opentelemetry", "otel.tracer", "otel.meter",
        "getlogger", "newlogger", "loggerfactory",
        "startactivity", "activitysource",
        "newcounter", "newhistogram", "newgauge",
    ):
        if h in low:
            return True
    # also check identifier children for LHS name match
    for child in ts_obs.walk_descendants(decl_node, named_only=True):
        if child.kind() in spec.identifier_kinds:
            nm = ts_obs.node_text(child, src_bytes)
            if _name_matches_obs(nm):
                return True
    return False


# ---------------------------------------------------------------------------
# extract_target_function
# ---------------------------------------------------------------------------

def extract_target_function(source: str, function: str, *, language: str) -> str:
    """Return just the target function's source, preserving its leading indent.

    Unlike the Python version we do NOT dedent — multi-language source files
    often have functions/methods at varying indent levels, and stripping the
    indent would surprise the LLM about the surrounding context.
    """
    spec = require_langspec(language)
    src_bytes = source.encode("utf-8")
    tree = ts_obs.parse(source, language)
    loc = ts_obs.find_function(tree, language, function, src_bytes)
    if loc is None:
        raise ValueError(f"function_io_ts: could not locate {function!r}")

    # extend backward to absorb leading whitespace on the first line so we
    # capture the indent that precedes the function definition
    bol = src_bytes.rfind(b"\n", 0, loc.start_byte)
    bol = 0 if bol == -1 else bol + 1
    prefix = src_bytes[bol:loc.start_byte]
    start = bol if prefix.strip() == b"" else loc.start_byte

    block = src_bytes[start:loc.end_byte].decode("utf-8")
    if not block.endswith("\n"):
        block += "\n"
    return block


# ---------------------------------------------------------------------------
# extract_module_context
# ---------------------------------------------------------------------------

def _filter_import_block(text: str) -> str:
    """Remove obs-flavoured lines from a grouped import declaration.

    Languages like Go bundle many imports inside a single `import (...)`
    block, so dropping the whole declaration on telemetry-strip is too
    aggressive — it would erase legitimate imports too. Instead, split the
    block by line, drop only the lines that hit `_looks_obs_import`, and
    keep the rest.

    Falls back to dropping the whole declaration only if NO non-obs line
    survives.
    """
    lines = text.splitlines()
    kept: list[str] = []
    for ln in lines:
        if _looks_obs_import(ln) and not (ln.strip().startswith("import") or ln.strip() in ("(", ")")):
            continue
        kept.append(ln)
    # if all that's left is the bare `import (` + `)` shell, drop the block
    payload = [ln for ln in kept if ln.strip() not in ("import (", "(", ")", "")]
    if not payload:
        return ""
    return "\n".join(kept)


def extract_module_context(
    source: str,
    function: str,
    *,
    language: str,
    strip_telemetry: bool = False,
) -> str:
    """Imports + module-level obs setup, language-aware.

    When `strip_telemetry=True`, telemetry-flavoured imports are dropped and
    the obs setup block is omitted (blind variant for p0-class prompts).
    """
    spec = require_langspec(language)
    src_bytes = source.encode("utf-8")
    tree = ts_obs.parse(source, language)
    root = tree.root_node()

    import_pieces: list[str] = []
    obs_pieces: list[str] = []
    import_kinds = set(_import_kinds_for(spec))
    decl_kinds = set(_DECL_KINDS.get(spec.name, ()))

    # Walk only TOP-LEVEL declarations (direct children of the root) to avoid
    # pulling in function-local imports / shadow declarations.
    for child in ts_obs.iter_named_children(root):
        kind = child.kind()
        text = ts_obs.node_text(child, src_bytes).rstrip()
        if kind in import_kinds:
            if strip_telemetry:
                # filter line-by-line so non-obs imports inside a grouped
                # `import (...)` block survive
                filtered = _filter_import_block(text)
                if filtered:
                    import_pieces.append(filtered)
            else:
                import_pieces.append(text)
            continue
        if kind in decl_kinds and not strip_telemetry:
            if _decl_smells_obs(child, spec, src_bytes):
                obs_pieces.append(text)

    parts: list[str] = []
    if import_pieces:
        parts.append("\n".join(import_pieces))
    if obs_pieces:
        parts.append("\n".join(obs_pieces))
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# splice_function
# ---------------------------------------------------------------------------

def splice_function(
    stripped_source: str,
    function: str,
    new_function_block: str,
    *,
    language: str,
) -> str:
    """Replace the target function in `stripped_source` with `new_function_block`.

    Lighter-weight than the Python version: we don't validate that the LLM
    returned a `def` line for the right symbol (each grammar's keyword
    differs); we just verify a function-keyword landmark and splice over
    the original byte range.
    """
    spec = require_langspec(language)
    src_bytes = stripped_source.encode("utf-8")
    tree = ts_obs.parse(stripped_source, language)
    loc = ts_obs.find_function(tree, language, function, src_bytes)
    if loc is None:
        raise ValueError(f"function_io_ts.splice: could not locate {function!r}")

    cleaned = _clean_llm_block(new_function_block, spec)
    target_name = function.rsplit(".", 1)[-1]
    # Allow generic methods like GetEcsValue<T>(...) in C# and TS/JS.
    target_call_re = re.compile(
        rf"\b{re.escape(target_name)}(?:\s*<[^>\n]+>)?\s*\(",
        re.IGNORECASE,
    )
    if not target_call_re.search(cleaned):
        raise ValueError(
            "function_io_ts.splice: LLM block does not define target function "
            f"{function!r}"
        )

    if not cleaned.endswith("\n"):
        cleaned += "\n"

    # absorb leading whitespace on the function's first source line so we
    # cleanly overwrite the indent too
    bol = src_bytes.rfind(b"\n", 0, loc.start_byte)
    bol = 0 if bol == -1 else bol + 1
    prefix = src_bytes[bol:loc.start_byte]
    start = bol if prefix.strip() == b"" else loc.start_byte

    return (
        src_bytes[:start].decode("utf-8")
        + cleaned
        + src_bytes[loc.end_byte:].decode("utf-8")
    )


# function-keyword landmarks per language (case-sensitive)
_FUNC_LANDMARKS: dict[str, tuple[str, ...]] = {
    "go": ("func ",),
    "java": ("public ", "private ", "protected ", "static "),  # any method-modifier
    "typescript": ("function ", "async function", "export function"),
    "javascript": ("function ", "async function", "export function"),
    "csharp": ("public ", "private ", "protected ", "static ", "internal "),
}


def _clean_llm_block(block: str, spec: LangSpec) -> str:
    """Strip surrounding code-fence and leading non-function lines.

    LLMs sometimes prepend a one-line note before the function; this rips
    leading blank/comment lines off until we hit a line that contains a
    function-keyword landmark for this language. Falls back to the raw
    block if no landmark is found.
    """
    block = block.strip()
    # remove a single surrounding fence if present
    fence_re = re.compile(r"^```(?:[a-zA-Z0-9_+\-]*)\n(.*?)\n```$", re.DOTALL)
    m = fence_re.match(block)
    if m:
        block = m.group(1)

    landmarks = _FUNC_LANDMARKS.get(spec.name, ("function",))
    lines = block.splitlines(keepends=True)
    for i, line in enumerate(lines):
        s = line.lstrip()
        if any(s.startswith(lm) for lm in landmarks):
            return "".join(lines[i:])
    return block


# ---------------------------------------------------------------------------
# extract_code_from_response
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9_+\-]*)\n(.*?)```", re.DOTALL)


def extract_code_from_response(
    response: str,
    *,
    language: str,
    function: str | None = None,
) -> str:
    """Pull out the function block from a raw LLM response.

    For non-Python, if `function` is provided we first try to pick the LAST
    fenced block that mentions the target function name (e.g., `Foo(`).
    This avoids selecting unrelated prompt/code snippets in prompt-echo cases.

    If no target match exists, prefer the largest fenced block that looks like
    a function/method by language landmarks, else fall back to the largest
    fenced block, else the raw response.
    """
    spec = require_langspec(language)
    blocks = _FENCE_RE.findall(response)
    if blocks:
        if function:
            target_name = function.rsplit(".", 1)[-1]
            target_re = re.compile(
                rf"\b{re.escape(target_name)}(?:\s*<[^>\n]+>)?\s*\(",
                re.IGNORECASE,
            )
            for block in reversed(blocks):
                if target_re.search(block):
                    return block.strip() + "\n"

        landmarks = _FUNC_LANDMARKS.get(spec.name, ("function",))
        landmark_blocks: list[str] = []
        for block in blocks:
            for line in block.splitlines():
                s = line.lstrip()
                if any(s.startswith(lm) for lm in landmarks):
                    landmark_blocks.append(block)
                    break
        if landmark_blocks:
            return max(landmark_blocks, key=len).strip() + "\n"

        return max(blocks, key=len).strip() + "\n"
    return response.strip() + "\n"
