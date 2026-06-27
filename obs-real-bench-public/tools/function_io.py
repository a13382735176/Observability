"""
Function-tier I/O helpers for the LLM roundtrip.

The pilot in v1 only modifies ONE function per instance. To keep the LLM's
task scoped to exactly that, we:

    1. extract just the target function's source from the (already stripped)
       file, dedented to column 0;
    2. extract a small "module context" block — imports + module-level obs
       setup assignments — for the LLM to read but not modify;
    3. splice the LLM-returned function back into the original stripped file
       at the same byte location, with the original indentation restored.

This is intentionally Python-only for v1. Polyglot instances are not yet
runnable and will be added once their strippers land.
"""
from __future__ import annotations

import ast
import re
import textwrap
from typing import Union

_FuncNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]

# Heuristic markers used to recognise module-level observability setup
# statements. Kept deliberately narrow: we'd rather miss a quirky setup
# pattern than leak unrelated business globals into the prompt.
_OBS_LHS_NAMES = {
    "tracer", "meter", "logger", "log", "instruments",
    "tracer_provider", "meter_provider", "logger_provider",
}
_OBS_LHS_SUFFIXES = (
    "_tracer", "_meter", "_logger", "_log",
    "_counter", "_histogram", "_gauge", "_metrics",
    "_instruments", "_observer",
)
_OBS_RHS_HINTS = (
    "get_tracer", "get_meter", "getLogger", "get_logger",
    "set_tracer_provider", "set_meter_provider", "set_logger_provider",
    "init_metrics", "init_logger", "init_tracer",
    "LoggerProvider", "TracerProvider", "MeterProvider",
)

# Modules whose presence in `import ...` / `from ... import ...` reveals to the
# LLM that observability is wired up in this codebase. Used by the "blind"
# extraction path (strip_telemetry=True) to hide telemetry tells from p0-class
# experiments. Each entry is matched as a case-insensitive substring against
# the dotted module path.
_OBS_IMPORT_MARKERS = (
    "opentelemetry",
    "prometheus",       # covers prometheus_client too
    "jaeger",
    "structlog",
    "loguru",
    "logbook",
)
# Stdlib `logging` and its submodules — handled separately since exact-match
# semantics differ from the substring markers above.
_OBS_IMPORT_EXACT = (
    "logging",
)


def _import_is_obs(node: ast.AST) -> bool:
    """Return True iff this Import/ImportFrom statement is a telemetry tell."""
    def _hit(name: str | None) -> bool:
        if not name:
            return False
        low = name.lower()
        if low in _OBS_IMPORT_EXACT or any(low.startswith(p + ".") for p in _OBS_IMPORT_EXACT):
            return True
        return any(m in low for m in _OBS_IMPORT_MARKERS)

    if isinstance(node, ast.ImportFrom):
        return _hit(node.module)
    if isinstance(node, ast.Import):
        return any(_hit(alias.name) for alias in node.names)
    return False


# ---------------------------------------------------------------------------
# locating the target function
# ---------------------------------------------------------------------------

def _locate(source: str, function: str) -> tuple[_FuncNode, int, int, int]:
    """Find the target function in `source`.

    `function` may be ``"name"`` (top-level) or ``"Class.method"`` (one level
    of nesting; v1 mining never produces deeper paths).

    Returns ``(node, start_lineno, end_lineno, col_offset)`` where lineno are
    1-based inclusive and start_lineno is the first decorator line if any.
    """
    tree = ast.parse(source)
    parts = function.split(".")
    nodes: list[ast.stmt] = list(tree.body)
    node: ast.stmt | None = None

    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        node = None
        for n in nodes:
            if last and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part:
                node = n
                break
            if (not last) and isinstance(n, ast.ClassDef) and n.name == part:
                node = n
                nodes = list(n.body)
                break
        if node is None:
            raise ValueError(f"function_io: could not locate {function!r} (segment {part!r})")

    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError(f"function_io: {function!r} did not resolve to a function")

    decorators = node.decorator_list
    start = decorators[0].lineno if decorators else node.lineno
    end = node.end_lineno or node.lineno
    return node, start, end, node.col_offset


# ---------------------------------------------------------------------------
# extract target function (dedented)
# ---------------------------------------------------------------------------

def extract_target_function(
    source: str,
    function: str,
    *,
    language: str = "python",
) -> str:
    """Return the target function's source, dedented to column 0.

    Decorators are included.
    """
    if language.lower() not in ("python", "py"):
        from .function_io_ts import extract_target_function as _ts_impl
        return _ts_impl(source, function, language=language)
    _node, start, end, col = _locate(source, function)
    lines = source.splitlines(keepends=True)
    block = "".join(lines[start - 1 : end])
    if col > 0:
        block = textwrap.dedent(block)
    if not block.endswith("\n"):
        block += "\n"
    return block


# ---------------------------------------------------------------------------
# extract module-level obs context
# ---------------------------------------------------------------------------

def _name_matches_obs(name: str) -> bool:
    low = name.lower()
    if low in _OBS_LHS_NAMES:
        return True
    return any(low.endswith(suf) for suf in _OBS_LHS_SUFFIXES)


def _value_smells_obs(node: ast.AST) -> bool:
    try:
        text = ast.unparse(node)
    except (AttributeError, ValueError):
        return False
    return any(h in text for h in _OBS_RHS_HINTS)


def _collect_obs_assigns(tree: ast.AST, keep: dict[int, int]) -> None:
    """Walk ANY level of nesting to find `x = ...` that looks obs-related.

    Many real projects (incl. OpenTelemetry demo) initialise `tracer`,
    `logger`, etc. inside ``if __name__ == "__main__":``. Those assignments
    still become module-level globals at runtime, so we include them so the
    LLM knows the names exist.

    `keep` maps lineno -> the assignment node's col_offset, so the caller
    can dedent each kept block to column 0 when emitting (otherwise these
    lines appear indented and look like locals, confusing the LLM).
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        kept = False
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and _name_matches_obs(tgt.id):
                kept = True
                break
        if not kept and _value_smells_obs(node.value):
            kept = True
        if kept:
            for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                keep[ln] = node.col_offset


def extract_module_context(
    source: str,
    function: str,
    *,
    strip_telemetry: bool = False,
    language: str = "python",
) -> str:
    """Return a small read-only context block for the LLM.

    When ``language`` is non-Python the call is forwarded to the tree-sitter
    based implementation in ``function_io_ts``.

    Includes:
        - every top-level `import` and `from ... import` statement;
        - every assignment (at any depth) whose LHS or RHS looks like obs
          setup (tracer/meter/logger/instruments providers and handles).

    Each obs-related assignment is dedented to column 0 in the emitted
    block so the LLM does not mistake it for a local. Imports keep their
    original (top-level, col 0) shape. Non-contiguous regions are
    separated by a single blank line.

    When ``strip_telemetry=True`` the "blind" variant is emitted: every
    telemetry-flavoured import is dropped and the obs-assignment block is
    omitted entirely. This is used by p0-class experiments that need the
    LLM to not even know observability is wired up in this codebase.
    """
    if language.lower() not in ("python", "py"):
        from .function_io_ts import extract_module_context as _ts_impl
        return _ts_impl(
            source, function,
            language=language, strip_telemetry=strip_telemetry,
        )
    tree = ast.parse(source)
    import_lines: set[int] = set()
    obs_lines: dict[int, int] = {}  # lineno -> stmt col_offset

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if strip_telemetry and _import_is_obs(node):
                continue
            for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                import_lines.add(ln)

    if not strip_telemetry:
        _collect_obs_assigns(tree, obs_lines)

    if not import_lines and not obs_lines:
        return ""

    lines = source.splitlines()
    out: list[str] = []

    # imports first, in source order, col 0 already
    prev: int | None = None
    for ln in sorted(import_lines):
        if prev is not None and ln > prev + 1:
            out.append("")
        out.append(lines[ln - 1].rstrip())
        prev = ln

    # obs assigns next, dedented per-statement
    if obs_lines:
        if out:
            out.append("")  # separator between imports and obs setup
        # group consecutive linenos that share the same col_offset (same stmt
        # or stmts at same indent), then dedent each group
        sorted_obs = sorted(obs_lines.items())
        prev_ln: int | None = None
        cur_block: list[str] = []
        cur_col: int = 0
        flushed = False

        def _flush(block: list[str], col: int) -> None:
            if not block:
                return
            text = "\n".join(block)
            if col > 0:
                # only strip exactly `col` leading spaces (textwrap.dedent
                # would only strip the common prefix, which works here)
                text = textwrap.dedent(text)
            out.append(text.rstrip("\n"))

        for ln, col in sorted_obs:
            if prev_ln is not None and (ln > prev_ln + 1 or col != cur_col):
                _flush(cur_block, cur_col)
                if ln > prev_ln + 1:
                    out.append("")
                cur_block = []
            cur_col = col
            cur_block.append(lines[ln - 1])
            prev_ln = ln
        _flush(cur_block, cur_col)

    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# splice the LLM-returned function back into the file
# ---------------------------------------------------------------------------

_DEF_LINE_RE = re.compile(r"^(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
_DECORATOR_LINE_RE = re.compile(r"^@", re.MULTILINE)


def _strip_leading_blanks_and_comments(block: str) -> str:
    """Trim leading lines that aren't part of the function definition.

    Some LLMs prepend a short comment ("# instrumented version") or an
    explanatory line before the `def`. We want only the function itself.
    """
    lines = block.splitlines(keepends=True)
    # Find first line that is either a decorator or a def
    for i, line in enumerate(lines):
        if line.lstrip().startswith("@") or re.match(r"^(?:async\s+)?def\s+\w+\s*\(", line.lstrip()):
            return "".join(lines[i:])
    return block  # no def found — let downstream parse fail loudly


def splice_function(
    stripped_source: str,
    function: str,
    new_function_block: str,
    *,
    language: str = "python",
) -> str:
    """Replace the target function in `stripped_source` with `new_function_block`.

    `new_function_block` is the LLM-returned function at column 0 (dedented).
    We re-indent it to match the original function's column, then byte-splice
    over the original line range.
    """
    if language.lower() not in ("python", "py"):
        from .function_io_ts import splice_function as _ts_impl
        return _ts_impl(stripped_source, function, new_function_block, language=language)
    _node, start, end, col = _locate(stripped_source, function)
    lines = stripped_source.splitlines(keepends=True)

    cleaned = _strip_leading_blanks_and_comments(new_function_block)

    # Verify the returned block actually defines the target function name.
    target_name = function.rsplit(".", 1)[-1]
    defs = _DEF_LINE_RE.findall(cleaned)
    if not defs:
        raise ValueError(
            f"splice: LLM output did not contain a `def` line for {function!r}"
        )
    if target_name not in defs:
        raise ValueError(
            f"splice: LLM output defines {defs!r} but target is {target_name!r}"
        )

    if col > 0:
        cleaned = textwrap.indent(cleaned, " " * col)

    if not cleaned.endswith("\n"):
        cleaned += "\n"

    return "".join(lines[: start - 1]) + cleaned + "".join(lines[end:])


# ---------------------------------------------------------------------------
# extract from raw LLM response (handles fenced code blocks)
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9_+\-]*)\n(.*?)```", re.DOTALL)


def extract_code_from_response(
    response: str,
    *,
    language: str = "python",
    function: str | None = None,
) -> str:
    """Pull out the function block from a raw LLM response.

    Strategy:
      1. If there are fenced code blocks, pick the LARGEST one that contains
         a `def ` line. (Models sometimes wrap a one-line example in another
         fence; we want the real one.)
      2. If no fence: return the response as-is and let the caller validate.

    If `function` is provided, prefer the LAST fenced block that defines the
    exact target function name. This guards against prompt-echo responses that
    include unrelated fenced snippets.
    """
    if language.lower() not in ("python", "py"):
        from .function_io_ts import extract_code_from_response as _ts_impl
        return _ts_impl(response, language=language, function=function)
    blocks = _FENCE_RE.findall(response)

    if function and blocks:
        target_name = function.rsplit(".", 1)[-1]
        target_re = re.compile(rf"(?:async\s+)?def\s+{re.escape(target_name)}\s*\(")
        for block in reversed(blocks):
            if target_re.search(block):
                return block.strip() + "\n"

    candidates = [b for b in blocks if re.search(r"(?:async\s+)?def\s+\w+\s*\(", b)]
    if candidates:
        return max(candidates, key=len).strip() + "\n"
    if blocks:
        # no block had a def — fall back to largest anyway
        return max(blocks, key=len).strip() + "\n"
    return response.strip() + "\n"
