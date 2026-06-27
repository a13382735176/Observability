"""
Polyglot anchor scorer (tree-sitter backed).

Mirrors `tools.score_anchor.collect()` but works on tree-sitter parse trees
so it covers Go / Java / C# / TS / JS. Exposes a single function:

    collect_ts(source, function_name, language) -> FunctionWalk

The returned `FunctionWalk` is shape-compatible with the Python one — same
field names, same semantics — so `score_anchor()` can dispatch to either
backend and reuse the alignment + F1 plumbing unchanged.

Design notes:
- "Statement" = a named child of a block-like node (function body, then
  recursively any nested `block` / `statement_block` / `compound_statement`).
- "Obs statement" detection mirrors `strip/ts_strip.py::_is_obs_statement`
  plus a helper-wrapped heuristic (any bare call whose name-chain tokens
  intersect the obs lexicon).
- Canonical fingerprints drop literals and call arg-lists, replacing them
  with `<lit>` / `(...)`. Recursive, modeled on `score_anchor._shape`.
- Key extraction: first positional string-literal arg of an obs call, plus
  every key of a dict/map argument to `set_attributes` / `add_event`.
- Keyword bag: every string-literal value + every identifier / attribute /
  method name encountered in the obs statement, tokenised and stop-word
  filtered (re-uses score_anchor._tokenize_text).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tools import ts_obs
from tools.langspec import LangSpec, require as require_langspec


# ---------------------------------------------------------------------------
# data types — match score_anchor.py field-for-field
# ---------------------------------------------------------------------------

@dataclass
class Anchor:
    canonical: str
    depth: int


@dataclass
class FunctionWalk:
    anchors: list[Anchor]
    slot_has_obs: list[bool]
    slot_keys: list[set[str]]
    slot_keywords: list[set[str]]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

# Block-ish node kinds we recurse into. Different languages spell this
# differently; this set covers Go / Java / C# / TS / JS.
_BLOCK_KINDS = {
    "block",                  # Go, Java, Rust
    "compound_statement",     # C#
    "statement_block",        # TS / JS
    "function_body",          # some grammars
    "method_body",
    "constructor_body",
    "do_block",
}


def _is_block(node) -> bool:
    return node.kind() in _BLOCK_KINDS


def _is_obs_stmt(stmt_node, spec: LangSpec, src_bytes: bytes) -> bool:
    """True iff the entire statement is observability.

    Recognised shapes (mirrors ts_strip._is_obs_statement + helper-call
    heuristic):
      - defer <obs_call>                              (Go)
      - expression_statement wrapping an obs call     (all)
      - expression_statement wrapping a helper-named  (all)
      - assign / short-var-decl with obs RHS          (all)
    """
    kind = stmt_node.kind()

    # Go's defer-statement
    if kind in spec.defer_kinds:
        for child in ts_obs.iter_named_children(stmt_node):
            if child.kind() in spec.call_kinds:
                if ts_obs.is_obs_call(child, spec, src_bytes) is not None:
                    return True
                if ts_obs.is_helper_obs_call(child, spec, src_bytes):
                    return True
        return False

    # expression-statement: wraps a single expression (typically a call)
    if kind == "expression_statement":
        for child in ts_obs.iter_named_children(stmt_node):
            if child.kind() in spec.call_kinds:
                if ts_obs.is_obs_call(child, spec, src_bytes) is not None:
                    return True
                if ts_obs.is_helper_obs_call(child, spec, src_bytes):
                    return True
        return False

    # local_variable_declaration / assignment with obs RHS
    if kind in spec.assign_kinds:
        return ts_obs.is_obs_assignment(stmt_node, spec, src_bytes)

    return False


# ---------------------------------------------------------------------------
# canonical fingerprint — language-agnostic, drops literals + call args
# ---------------------------------------------------------------------------

def _shape(node, spec: LangSpec, src_bytes: bytes) -> str:
    """Recursive structural fingerprint, parallel to score_anchor._shape."""
    if node is None:
        return ""
    kind = node.kind()

    if kind in spec.identifier_kinds:
        return ts_obs.node_text(node, src_bytes)

    if kind in spec.string_literal_kinds:
        return "<lit>"

    # numeric / boolean / null literals across grammars
    if "literal" in kind or kind in (
        "number", "integer", "float", "true", "false", "null", "nil",
        "boolean", "raw_string_literal", "interpreted_string_literal",
    ):
        return "<lit>"

    if kind in spec.attribute_kinds:
        lhs = (
            ts_obs.child_by_field_name(node, "object")
            or ts_obs.child_by_field_name(node, "operand")
            or ts_obs.child_by_field_name(node, "value")
            or ts_obs.child_by_field_name(node, "expression")
        )
        rhs = (
            ts_obs.child_by_field_name(node, "field")
            or ts_obs.child_by_field_name(node, "property")
            or ts_obs.child_by_field_name(node, "name")
        )
        left = _shape(lhs, spec, src_bytes) if lhs is not None else ""
        right = ts_obs.node_text(rhs, src_bytes) if rhs is not None else ""
        if left and right:
            return f"{left}.{right}"
        return left or right

    if kind in spec.call_kinds:
        fn = ts_obs.child_by_field_name(node, spec.call_func_field)
        return f"{_shape(fn, spec, src_bytes)}(...)"

    if "subscript" in kind or "index" in kind:
        base = node.named_child(0) if node.named_child_count() else None
        prefix = _shape(base, spec, src_bytes) if base else ""
        return f"{prefix}[*]" if prefix else "[*]"

    # composite / unknown — collapse to kind tag so canonicals still align
    # by shape.
    return f"<{kind}>"


def _canonical_stmt(stmt_node, spec: LangSpec, src_bytes: bytes) -> str:
    """One-line canonical form of a statement node.

    For compound statements (if/for/while/with/try/switch) we keep only the
    "head" (the controlling expression) since the bodies are walked
    separately and each emit their own canonicals.
    """
    kind = stmt_node.kind()

    # assignments / declarations
    if kind in spec.assign_kinds:
        # find LHS + RHS via field names (most grammars expose 'left'/'right'
        # or 'value'). Fall back to raw text shape if unknown.
        lhs = (
            ts_obs.child_by_field_name(stmt_node, "left")
            or ts_obs.child_by_field_name(stmt_node, "name")
            or ts_obs.child_by_field_name(stmt_node, "declarator")
        )
        rhs = (
            ts_obs.child_by_field_name(stmt_node, "right")
            or ts_obs.child_by_field_name(stmt_node, "value")
        )
        left_s = _shape(lhs, spec, src_bytes) if lhs is not None else "<lhs>"
        right_s = _shape(rhs, spec, src_bytes) if rhs is not None else "<rhs>"
        return f"{left_s} = {right_s}"

    # expression-statement: shape its inner expression
    if kind == "expression_statement":
        inner = None
        for c in ts_obs.iter_named_children(stmt_node):
            inner = c
            break
        return _shape(inner, spec, src_bytes) if inner is not None else "<empty_expr>"

    # control-flow statements: just the head shape
    if kind in (
        "if_statement", "for_statement", "while_statement", "do_statement",
        "switch_statement", "switch_expression",
        "for_in_statement", "for_each_statement", "foreach_statement",
        "for_range_clause",
    ):
        cond = (
            ts_obs.child_by_field_name(stmt_node, "condition")
            or ts_obs.child_by_field_name(stmt_node, "value")
            or ts_obs.child_by_field_name(stmt_node, "left")
        )
        return f"{kind}({_shape(cond, spec, src_bytes)})"

    # return / throw / yield
    if kind in ("return_statement", "throw_statement", "yield_statement", "break_statement", "continue_statement"):
        inner = None
        for c in ts_obs.iter_named_children(stmt_node):
            inner = c
            break
        if inner is None:
            return kind
        return f"{kind}({_shape(inner, spec, src_bytes)})"

    # try / catch
    if kind in ("try_statement", "try_with_resources_statement", "try_finally_statement"):
        return "try:"

    # defer / using statements
    if kind in spec.defer_kinds:
        inner = None
        for c in ts_obs.iter_named_children(stmt_node):
            inner = c
            break
        return f"defer({_shape(inner, spec, src_bytes)})"

    # fallback: bare kind tag
    return f"<{kind}>"


# ---------------------------------------------------------------------------
# key extraction (strict) + keyword bag (lenient)
# ---------------------------------------------------------------------------

def _obs_stmt_keys(stmt_node, spec: LangSpec, src_bytes: bytes) -> set[str]:
    """Pull string-literal key names from an obs statement.

    Mirrors `score_anchor._obs_stmt_keys`: first positional string-literal
    argument of every obs Call descendant becomes a key. For Go's
    `tracer.Start(ctx, "name")` we use the language-specific span-name arg
    index.
    """
    keys: set[str] = set()
    for n in ts_obs.walk_descendants(stmt_node, named_only=True):
        if n.kind() not in spec.call_kinds:
            continue
        # Rust macros: method is the last segment of the `macro` field.
        if n.kind() == "macro_invocation":
            m_node = ts_obs.child_by_field_name(n, "macro")
            if m_node is None:
                continue
            method = ts_obs.node_text(m_node, src_bytes).rsplit("::", 1)[-1]
        else:
            receiver, method = ts_obs.call_receiver_and_method(n, spec, src_bytes)
            if method is None:
                continue
        args = ts_obs.call_args(n, spec)
        if not args:
            continue
        # Use language's preferred index for tracer-start, else 0.
        idx = 0
        # tracer.Start in Go has signature Start(ctx, name, ...) — name is arg[1]
        if method in ("Start", "start_span", "start_as_current_span"):
            from tools.langspec import LangSpec  # noqa: F401
            # We don't store start-name index on spec generally; default to 0
            # but bump to 1 for Go where ctx is positional.
            if spec.name == "go":
                idx = 1
        if idx >= len(args):
            continue
        s = ts_obs.string_literal_value(args[idx], src_bytes, spec)
        if s:
            keys.add(s)
    return keys


# Stop-word filter mirrors score_anchor._KW_STOP; reuse to keep behaviour
# parallel.
from tools.score_anchor import _tokenize_text as _score_anchor_tokenize  # noqa: E402


def _obs_stmt_keywords(stmt_node, spec: LangSpec, src_bytes: bytes) -> set[str]:
    """Lenient token bag for an obs statement.

    Walks every descendant and harvests:
      * string literal values
      * identifier names
      * member-access RHS names (`field`/`name`/`property`)
    Then tokenises each via score_anchor._tokenize_text (drops obs framework
    stop-words, short tokens, pure-digit tokens).
    """
    out: set[str] = set()
    for n in ts_obs.walk_descendants(stmt_node, named_only=True):
        kind = n.kind()
        # string-literal value
        if kind in spec.string_literal_kinds:
            v = ts_obs.string_literal_value(n, src_bytes, spec)
            if v:
                out |= _score_anchor_tokenize(v)
            continue
        # identifier
        if kind in spec.identifier_kinds:
            out |= _score_anchor_tokenize(ts_obs.node_text(n, src_bytes))
            continue
        # member-access RHS
        if kind in spec.attribute_kinds:
            rhs = (
                ts_obs.child_by_field_name(n, "field")
                or ts_obs.child_by_field_name(n, "property")
                or ts_obs.child_by_field_name(n, "name")
            )
            if rhs is not None:
                out |= _score_anchor_tokenize(ts_obs.node_text(rhs, src_bytes))
            continue
    return out


# ---------------------------------------------------------------------------
# walk: emit ('B'|'O', depth, canonical, keys, keywords) per statement
# ---------------------------------------------------------------------------

def _iter_block_children(block_node):
    """Yield the named-children of a block-ish node, in source order.

    Some grammars (Go) wrap the statements inside a `statement_list` node
    that sits between the `block` and its actual statements; transparently
    descend through that wrapper so callers see real statements.
    """
    out: list = []
    for c in ts_obs.iter_named_children(block_node):
        if c.kind() in ("statement_list",):
            out.extend(ts_obs.iter_named_children(c))
        else:
            out.append(c)
    return out


def _find_block_descendants(stmt_node):
    """Find immediate block-like descendants of a compound statement.

    For an `if_statement` returns its consequence + alternative blocks; for
    `for`/`while`/`do` returns its body block; for `try` returns the body
    and any catch/finally blocks. Generic: walk descendants but stop at the
    first block encountered along each branch, then continue collecting
    siblings.
    """
    blocks: list = []
    # Look at direct named children first.
    stack = list(ts_obs.iter_named_children(stmt_node))
    while stack:
        cur = stack.pop(0)
        if _is_block(cur):
            blocks.append(cur)
            # don't descend into the block itself; caller will walk it
            continue
        # else descend looking for nested blocks (but stay shallow — we want
        # immediate siblings of the head clause, not deeply nested ones)
        for c in ts_obs.iter_named_children(cur):
            stack.append(c)
    return blocks


def _walk(body_children: list, spec: LangSpec, src_bytes: bytes,
          depth: int, out: list) -> None:
    """DFS — emit ('B'|'O', depth, canonical, keys, keywords) per statement.

    body_children: list of statement nodes (named children of a block).
    """
    for stmt in body_children:
        # skip non-statement children (e.g. line comments) if they don't
        # carry meaningful structure. We use a permissive check: anything
        # whose kind ends with "_statement" OR is in assign_kinds counts as
        # a statement. Comments / labels / etc. are skipped.
        kind = stmt.kind()
        is_stmt = (
            kind.endswith("_statement")
            or kind in spec.assign_kinds
            or kind in spec.defer_kinds
            or kind == "expression_statement"
            or kind in (
                "labeled_statement", "labeled_block",
                "local_variable_declaration",
            )
        )
        if not is_stmt:
            continue

        if _is_obs_stmt(stmt, spec, src_bytes):
            out.append((
                "O", depth, _canonical_stmt(stmt, spec, src_bytes),
                _obs_stmt_keys(stmt, spec, src_bytes),
                _obs_stmt_keywords(stmt, spec, src_bytes),
            ))
            continue

        # business statement
        out.append((
            "B", depth, _canonical_stmt(stmt, spec, src_bytes),
            set(), set(),
        ))

        # recurse into any block-shaped child (for/if/try/etc.)
        for block in _find_block_descendants(stmt):
            _walk(_iter_block_children(block), spec, src_bytes, depth + 1, out)


# ---------------------------------------------------------------------------
# top-level collector
# ---------------------------------------------------------------------------

def _function_body_block(fn_node, spec: LangSpec):
    """Return the body-block node of a function definition, or None.

    Tree-sitter exposes the body under various field names (`body`,
    `block`) and as direct children whose kind is in `_BLOCK_KINDS`.
    """
    # try field "body" first
    body = ts_obs.child_by_field_name(fn_node, "body")
    if body is not None:
        if _is_block(body):
            return body
        # Java's method_declaration has body = block; sometimes the block
        # itself is the body. If body is a single statement, treat it as a
        # synthetic block — but for our targets methods always have block bodies.
    # fall back: find first block-kind named descendant
    for c in ts_obs.iter_named_children(fn_node):
        if _is_block(c):
            return c
    # last resort: any descendant block
    for n in ts_obs.walk_descendants(fn_node, named_only=True):
        if _is_block(n):
            return n
    return None


def collect_ts(source: str, function_name: str, language: str) -> FunctionWalk:
    """Walk `function_name` in `source` and return anchors + per-slot obs info.

    Returns an empty walk when the function isn't found or the source can't
    be parsed (mirrors `score_anchor.collect` on parse error).
    """
    spec = require_langspec(language)
    src_bytes = source.encode("utf-8")
    try:
        tree = ts_obs.parse(source, language)
    except Exception:
        return FunctionWalk(
            anchors=[], slot_has_obs=[False],
            slot_keys=[set()], slot_keywords=[set()],
        )

    loc = ts_obs.find_function(tree, language, function_name, src_bytes)
    if loc is None:
        return FunctionWalk(
            anchors=[], slot_has_obs=[False],
            slot_keys=[set()], slot_keywords=[set()],
        )

    body = _function_body_block(loc.node, spec)
    if body is None:
        return FunctionWalk(
            anchors=[], slot_has_obs=[False],
            slot_keys=[set()], slot_keywords=[set()],
        )

    flat: list = []
    _walk(_iter_block_children(body), spec, src_bytes, depth=0, out=flat)

    anchors: list[Anchor] = []
    slots: list[bool] = [False]
    slot_keys: list[set[str]] = [set()]
    slot_keywords: list[set[str]] = [set()]
    for kind, depth, canonical, keys, kws in flat:
        if kind == "O":
            slots[-1] = True
            slot_keys[-1] |= keys
            slot_keywords[-1] |= kws
        else:
            anchors.append(Anchor(canonical=canonical, depth=depth))
            slots.append(False)
            slot_keys.append(set())
            slot_keywords.append(set())
    return FunctionWalk(
        anchors=anchors, slot_has_obs=slots,
        slot_keys=slot_keys, slot_keywords=slot_keywords,
    )
