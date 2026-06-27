"""
Tree-sitter-based obs stripper (non-Python).

Replicates `python_strip.strip()` behaviour using `ts_obs` primitives:

    strip(source, *, language, function) -> str

Removes obs statements inside the target function while leaving everything
else (imports, other functions, module decls, comments) byte-for-byte
identical.

Strategy:
    1. Parse the source.
    2. Locate the target function via `ts_obs.find_function`.
    3. Walk every statement-shaped descendant of the function body. For each
       statement node, ask `_is_obs_statement`. Collect byte ranges to drop.
    4. Extend each range backward to absorb its leading whitespace (the
       indent on that line) and forward to absorb its trailing newline, so
       the function body remains well-formatted.
    5. Stitch the kept slices together.

Caveats accepted for the polyglot pilot:
    - We do NOT rewrite nested `if`/`for` blocks to inject a no-op when
      stripping leaves them empty. Languages with `block` non-terminals
      (Go, Java) accept empty blocks; languages that don't (none of our
      targets currently) would need extra care.
    - We do not collapse Go's `ctx, span := tracer.Start(ctx, "F")` to a
      bare `ctx, _ = something(ctx, "F")`; we drop the line outright. Any
      downstream uses of `ctx`/`span` will get their own obs-drop too if
      the user only uses them for obs. If `ctx` is reused for non-obs
      calls, the resulting stripped source will reference an undefined
      `ctx` — a known and acceptable limitation for the pilot.
    - Comments embedded within the function body survive only if they are
      on their own line AND not on a dropped statement's line.
"""
from __future__ import annotations

from typing import Optional

from .. import ts_obs
from ..langspec import LangSpec, require as require_langspec


def _is_obs_statement(stmt_node, spec: LangSpec, src_bytes: bytes) -> bool:
    """True iff the entire statement should be dropped as obs.

    Recognised shapes:
      - `defer X.Y(...)` where Y is an obs call             (Go)
      - expression-statement wrapping an obs call           (all langs)
      - short-var-decl / assignment whose RHS is an obs setup call
        (e.g. `ctx, span := tracer.Start(...)`)
    """
    kind = stmt_node.kind()

    # Go's defer + similar wrapped-statement constructs
    if kind in spec.defer_kinds:
        for child in ts_obs.iter_named_children(stmt_node):
            if child.kind() in spec.call_kinds:
                if ts_obs.is_obs_call(child, spec, src_bytes) is not None:
                    return True
                # also drop defer of helper-wrapped obs (e.g. `defer span.End()`)
                if ts_obs.is_helper_obs_call(child, spec, src_bytes):
                    return True
        return False

    # expression statement: wraps a single expression (typically a call)
    if "expression_statement" in kind or kind == "expression_statement":
        for child in ts_obs.iter_named_children(stmt_node):
            if child.kind() in spec.call_kinds:
                return ts_obs.is_obs_call(child, spec, src_bytes) is not None
        return False

    # assignment / short-var-decl with obs RHS
    if kind in spec.assign_kinds:
        if ts_obs.is_obs_assignment(stmt_node, spec, src_bytes):
            return True
        return False

    return False


def _line_extents(src_bytes: bytes, start_byte: int, end_byte: int) -> tuple[int, int]:
    """Extend a byte range backward to BOL (absorbing only whitespace on its
    leading line) and forward through one trailing newline.

    We extend backward only if everything between the previous newline and
    `start_byte` is whitespace (so we don't eat code that shares the same
    physical line). We extend forward to include exactly one trailing '\\n'.
    """
    n = len(src_bytes)
    # backward to start of line
    bol = src_bytes.rfind(b"\n", 0, start_byte)
    bol = 0 if bol == -1 else bol + 1
    prefix = src_bytes[bol:start_byte]
    if prefix.strip() == b"":
        start = bol
    else:
        start = start_byte
    # forward through the trailing newline
    eol = src_bytes.find(b"\n", end_byte)
    end = (eol + 1) if eol != -1 else n
    return start, end


def _collect_drop_ranges(fn_node, spec: LangSpec, src_bytes: bytes) -> list[tuple[int, int]]:
    """Walk the function body and collect (start_byte, end_byte) ranges to drop."""
    ranges: list[tuple[int, int]] = []

    # We want statement-level nodes. Collect all named descendants whose kind
    # is "statement-like": expression_statement, defer_statement, plus
    # whatever's in spec.assign_kinds. We skip descendants of an already-
    # dropped range to avoid double-counting nested ones inside dropped lines.
    candidate_kinds = (
        set(spec.defer_kinds)
        | set(spec.assign_kinds)
        # expression-statement spelling varies across grammars
        | {"expression_statement", "expression_statement_list"}
    )

    for n in ts_obs.walk_descendants(fn_node, named_only=True):
        if n is fn_node:
            continue
        if n.kind() not in candidate_kinds:
            continue
        # don't process descendants of an already-dropped node
        # (we sort by start_byte to deduplicate later)
        if _is_obs_statement(n, spec, src_bytes):
            s, e = _line_extents(src_bytes, n.start_byte(), n.end_byte())
            ranges.append((s, e))

    # sort + merge overlapping
    ranges.sort()
    merged: list[tuple[int, int]] = []
    for s, e in ranges:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def strip(source: str, *, language: str, function: str) -> str:
    """Return `source` with obs statements removed from inside `function`.

    Outside the named function, the output is byte-identical to the input.
    """
    spec = require_langspec(language)
    src_bytes = source.encode("utf-8")
    tree = ts_obs.parse(source, language)
    loc = ts_obs.find_function(tree, language, function, src_bytes)
    if loc is None:
        raise ValueError(f"function not found: {function}")

    ranges = _collect_drop_ranges(loc.node, spec, src_bytes)
    if not ranges:
        return source

    # stitch kept slices
    pieces: list[bytes] = []
    cursor = 0
    for s, e in ranges:
        pieces.append(src_bytes[cursor:s])
        cursor = e
    pieces.append(src_bytes[cursor:])
    return b"".join(pieces).decode("utf-8")
