"""
Tree-sitter primitives shared across the polyglot pipeline.

Everything that needs to walk source ASTs (extract, strip, function_io,
build_siblings) goes through this module. Per-language nuance lives in
`tools.langspec`; this module is language-agnostic in shape but takes a
`LangSpec` to look up node kinds and obs vocabulary.

API summary:
    parse(source, language)              -> Tree
    function_text(source, language, fn)  -> str | None
    function_node(tree, language, fn)    -> Node | None
    walk_function_calls(...)             -> iterator over (call_node, ancestors)
    receiver_kind(name_chain)            -> 'span'|'tracer'|'logger'|'metric'|None
    is_obs_call(call, langspec, src)     -> bool
    is_obs_assignment(assign, ...)       -> bool
    name_chain(receiver_node, src)       -> str (dotted, lowercased)
    string_literal_value(node, src)      -> str | None  (only for true string literals)
    node_text(node, src_bytes)           -> str

Implementation notes:
- This version of tree-sitter (0.25.x) exposes node accessors as METHODS, not
  attributes: `node.kind()`, `node.start_byte()`, `node.child(i)`,
  `node.child_count()`, `node.named_child(i)`, `node.named_child_count()`,
  `node.child_by_field_name("name")`, `node.start_position().row`,
  `node.parent()` (yes — `.parent` is a method too in this version).
  There is NO `node.children` list — iterate with `for i in range(child_count())`.
- `parser.parse(source: str)` is the entry point. It accepts `str`, not bytes.
- All byte ranges are 0-based, line/row numbers are 0-based (we add 1 when
  surfacing to humans).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Optional

from tools.langspec import LangSpec, require as require_langspec


# ---------------------------------------------------------------------------
# parser cache (one Parser per (thread, language); reuse across calls)
# ---------------------------------------------------------------------------
#
# tree-sitter's Parser is a pyo3-backed Rust object marked `unsendable`, which
# means it panics if accessed from a thread other than the one that created
# it. ThreadPoolExecutor workers each need their own parser, so we keep a
# threading.local() cache: first lookup in a thread builds the parser, every
# subsequent lookup in the same thread reuses it.

import threading as _threading

_PARSER_TLS = _threading.local()


def _get_parser(spec: LangSpec):
    cache = getattr(_PARSER_TLS, "cache", None)
    if cache is None:
        cache = {}
        _PARSER_TLS.cache = cache
    key = spec.name
    p = cache.get(key)
    if p is None:
        try:
            from tree_sitter_language_pack import get_parser
        except ImportError as e:  # pragma: no cover
            raise SystemExit(
                "tree_sitter_language_pack not installed. Run:\n"
                "    pip install tree-sitter tree-sitter-language-pack"
            ) from e
        # csharp grammar name matches the alias; everything else uses the spec name.
        p = get_parser(spec.name)
        cache[key] = p
    return p


def clear_parser_cache() -> None:
    """Drop this thread's parser cache before a worker thread exits."""
    cache = getattr(_PARSER_TLS, "cache", None)
    if cache is not None:
        cache.clear()
        delattr(_PARSER_TLS, "cache")


def parse(source: str, language: str):
    """Parse `source` and return a tree-sitter Tree. Source must be `str`."""
    spec = require_langspec(language)
    parser = _get_parser(spec)
    return parser.parse(source)


# ---------------------------------------------------------------------------
# generic node helpers
# ---------------------------------------------------------------------------

def node_text(node, src_bytes: bytes) -> str:
    """Decoded UTF-8 slice of the source backing this node."""
    return src_bytes[node.start_byte():node.end_byte()].decode("utf-8", errors="replace")


def iter_named_children(node) -> Iterator:
    """Yield the named (non-punctuation) children of `node` in order."""
    n = node.named_child_count()
    for i in range(n):
        yield node.named_child(i)


def iter_children(node) -> Iterator:
    """Yield ALL children (including anonymous tokens) in order."""
    n = node.child_count()
    for i in range(n):
        yield node.child(i)


def walk_descendants(node, *, named_only: bool = True) -> Iterator:
    """Depth-first walk; yields every descendant node (and `node` itself first).

    Use `named_only=False` to also see punctuation/operator tokens.
    """
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        children = (
            iter_named_children(cur) if named_only else iter_children(cur)
        )
        # push in reverse so DFS visits in source order
        kids = list(children)
        for c in reversed(kids):
            stack.append(c)


def find_node_by_kind(node, kinds: Iterable[str], *, named_only: bool = True):
    """First descendant whose `.kind()` is in `kinds`, or None."""
    kinds_set = set(kinds)
    for n in walk_descendants(node, named_only=named_only):
        if n.kind() in kinds_set:
            return n
    return None


def child_by_field_name(node, name: str):
    """Safe wrapper — older TS versions may raise, newer return None."""
    try:
        return node.child_by_field_name(name)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# function locator
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FunctionLoc:
    """Resolved location of a target function in a parsed tree."""
    node: object                # the function_definition / function_declaration / method_declaration node
    class_node: Optional[object]  # enclosing class-like node, or None
    start_byte: int
    end_byte: int
    start_row: int              # 0-based
    start_col: int              # 0-based
    name: str                   # plain symbol (last segment of "Class.method")
    class_name: Optional[str]


def _node_symbol_name(node, spec: LangSpec, src_bytes: bytes) -> Optional[str]:
    """Best-effort: extract the symbol name from a fn/class node.

    Per-language quirks:
      - C++ `function_definition` has no `name` field; its declarator is a
        `function_declarator` whose own `declarator` field is the identifier
        (sometimes `qualified_identifier` for `Class::method` definitions).
        We follow the chain until we reach a leaf identifier kind.
      - JS/TS `arrow_function` and `function_expression` are anonymous; the
        callable's effective name is the LHS of the enclosing
        `variable_declarator` (`const foo = (...) => ...`) or
        `assignment_expression` (`module.exports.foo = ...`). We climb
        ancestors until we find such a binder.
    """
    for field_name in spec.fn_name_fields:
        c = child_by_field_name(node, field_name)
        if c is None:
            continue
        # C++ declarator chain: function_declarator -> declarator -> identifier
        if c.kind() in ("function_declarator", "pointer_declarator",
                        "reference_declarator", "parenthesized_declarator"):
            cur = c
            for _ in range(6):  # bounded — declarator nests are shallow
                inner = child_by_field_name(cur, "declarator")
                if inner is None:
                    break
                cur = inner
                if cur.kind() in spec.identifier_kinds:
                    break
            txt = node_text(cur, src_bytes).strip()
            # qualified_identifier like Foo::bar — drop the scope so consumers
            # can match on the bare method name. Class-qualifier matching is
            # handled separately in find_function via the "Class.method" parts.
            if "::" in txt:
                txt = txt.split("::")[-1]
            return txt
        return node_text(c, src_bytes).strip()

    # Anonymous fn-shaped nodes (arrow_function, function_expression): look
    # at the enclosing binder for the effective callable name.
    if node.kind() in ("arrow_function", "function_expression"):
        nm = _binder_name(node, spec, src_bytes)
        if nm is not None:
            return nm

    # Last-resort fallback: first identifier descendant.
    nm_node = find_node_by_kind(node, spec.identifier_kinds, named_only=True)
    if nm_node is not None:
        return node_text(nm_node, src_bytes).strip()
    return None


def _binder_name(node, spec: LangSpec, src_bytes: bytes) -> Optional[str]:
    """For anonymous JS/TS fns: name from the enclosing const/let/assign binder.

    Walks at most ~4 ancestors. Recognised shapes:
      const foo = (...) => ...            (variable_declarator -> name)
      let foo = function(...) { ... }     (variable_declarator -> name)
      foo = (...) => ...                  (assignment_expression -> left)
      module.exports.foo = (...) => ...   (assignment_expression -> left.property)
      { foo: (...) => ... }               (pair / property_assignment -> key)
    """
    p = node.parent()
    hops = 0
    while p is not None and hops < 4:
        k = p.kind()
        if k == "variable_declarator":
            n = child_by_field_name(p, "name")
            if n is not None:
                return node_text(n, src_bytes).strip()
        if k in ("assignment_expression", "augmented_assignment_expression"):
            lhs = child_by_field_name(p, "left")
            if lhs is not None:
                txt = node_text(lhs, src_bytes).strip()
                # take last dotted segment so "module.exports.foo" -> "foo"
                tail = txt.rsplit(".", 1)[-1]
                return tail
        if k == "pair" or k.endswith("property_assignment"):
            n = child_by_field_name(p, "key")
            if n is not None:
                return node_text(n, src_bytes).strip()
        p = p.parent()
        hops += 1
    return None


def _class_symbol_name(node, spec: LangSpec, src_bytes: bytes) -> Optional[str]:
    """Symbol name on a class-like node. Most grammars expose `name`."""
    c = child_by_field_name(node, "name")
    if c is not None:
        return node_text(c, src_bytes).strip()
    nm = find_node_by_kind(node, spec.identifier_kinds, named_only=True)
    if nm is not None:
        return node_text(nm, src_bytes).strip()
    return None


def find_function(tree, language: str, function: str, src_bytes: bytes) -> Optional[FunctionLoc]:
    """Locate `function` (either "name" or "Class.method") in `tree`.

    Returns None if not found. We accept matches anywhere in the tree (not
    just top-level) to handle nested classes / inner files, but if the input
    is "Class.method" we require the method to live inside a class with that
    name.
    """
    spec = require_langspec(language)
    parts = function.split(".")
    target_name = parts[-1]
    expected_class = parts[-2] if len(parts) >= 2 else None

    root = tree.root_node()

    # walk every named descendant; for each fn-kind node, compare names
    for n in walk_descendants(root, named_only=True):
        if n.kind() not in spec.fn_kinds:
            continue
        nm = _node_symbol_name(n, spec, src_bytes)
        if nm != target_name:
            continue

        # find enclosing class, if any
        cls_node = None
        cls_name = None
        p = n.parent()
        while p is not None:
            if p.kind() in spec.class_kinds:
                cls_node = p
                cls_name = _class_symbol_name(p, spec, src_bytes)
                break
            p = p.parent()

        if expected_class is not None and cls_name != expected_class:
            continue

        sp = n.start_position()
        return FunctionLoc(
            node=n,
            class_node=cls_node,
            start_byte=n.start_byte(),
            end_byte=n.end_byte(),
            start_row=sp.row,
            start_col=sp.column,
            name=target_name,
            class_name=cls_name,
        )
    return None


# ---------------------------------------------------------------------------
# call-shape introspection
# ---------------------------------------------------------------------------

def _selector_chain(node, spec: LangSpec, src_bytes: bytes) -> str:
    """Dotted name chain for a receiver expression, lowercased.

    Examples (Go):
        `tracer`                  -> "tracer"
        `s.tracer`                -> "s.tracer"
        `t[0].tracer`             -> "t[*].tracer"
        `pkg.NewTracer().foo`     -> "pkg.newtracer().foo"  (lowercased)

    Mirrors the Python `_receiver_name_chain` semantics; per-grammar node
    kinds are pulled from the LangSpec.
    """
    if node is None:
        return ""
    kind = node.kind()

    if kind in spec.identifier_kinds:
        return node_text(node, src_bytes).lower()

    if kind in spec.attribute_kinds:
        # Generic shape: a selector/attribute/member_expression has a left
        # operand + a right field. tree-sitter exposes them via field names
        # (`object`/`operand`/`value`) and (`field`/`property`/`name`); we
        # try several to cover Go/Java/TS/JS/C# spellings.
        # `path` covers Rust's scoped_identifier (e.g. `tracing::info`).
        lhs = (
            child_by_field_name(node, "object")
            or child_by_field_name(node, "operand")
            or child_by_field_name(node, "value")
            or child_by_field_name(node, "expression")
            or child_by_field_name(node, "path")
        )
        rhs = (
            child_by_field_name(node, "field")
            or child_by_field_name(node, "property")
            or child_by_field_name(node, "name")
        )
        left = _selector_chain(lhs, spec, src_bytes) if lhs is not None else ""
        right = node_text(rhs, src_bytes).lower() if rhs is not None else ""
        if left and right:
            return f"{left}.{right}"
        return left or right

    # Rust `tracing::info!("...")` etc.: the chain is the macro path.
    if kind == "macro_invocation":
        m = child_by_field_name(node, "macro")
        return _selector_chain(m, spec, src_bytes) if m is not None else ""

    if kind in spec.call_kinds:
        # name chain of a call is the chain of its receiver/function expr
        fn = child_by_field_name(node, spec.call_func_field)
        return _selector_chain(fn, spec, src_bytes)

    # generic subscript-like nodes get collapsed to [*]
    if "subscript" in kind or "index" in kind:
        # try first child as base
        base = node.named_child(0) if node.named_child_count() else None
        prefix = _selector_chain(base, spec, src_bytes) if base else ""
        return f"{prefix}[*]" if prefix else "[*]"

    # Unhandled node kind (function literal, struct expression, type
    # assertion, ...). Returning the raw lowercased text is dangerously
    # permissive: a function literal `func(){ logger.Error(...) }` would
    # tokenise to include 'logger', falsely marking the outer call as obs.
    # Return empty to indicate "no recognisable receiver chain".
    return ""


def receiver_kind(name_chain: str) -> Optional[str]:
    """Classify a dotted lowercased receiver chain.

    Returns 'span' | 'tracer' | 'logger' | 'metric' | None.
    Mirrors `extract/python_extract.py::_receiver_kind` exactly (modulo node
    parsing — input here is a pre-built string).
    """
    name = name_chain or ""
    if not name:
        return None
    # most-specific first
    if "span" in name:
        return "span"
    if "tracer" in name:
        return "tracer"
    if "logger" in name:
        return "logger"
    tokens = name.replace("[*]", "").replace("[]", "").split(".")
    for tok in tokens:
        if tok in ("log", "logging") or tok.endswith("_log"):
            return "logger"
    for kw in ("meter", "counter", "histogram", "gauge", "metric"):
        if kw in name:
            return "metric"
    return None


def call_receiver_and_method(call_node, spec: LangSpec, src_bytes: bytes) -> tuple[Optional[object], Optional[str]]:
    """For a call node, return (receiver_node, method_name) if it's a member-call.

    Returns (None, None) if the call is to a bare function (not a method on a
    receiver). For Java-style `method_invocation`, the method name lives in
    the `name` field and the receiver in `object`; for selector-based grammars
    (Go/TS/JS/C#) the function field of the call holds a member-expression
    whose RHS is the method name.
    """
    fn = child_by_field_name(call_node, spec.call_func_field)

    # Java-style: call node directly exposes name + object
    if fn is None or fn.kind() in spec.identifier_kinds:
        # might be plain identifier (bare call). Check sibling fields.
        nm = child_by_field_name(call_node, "name")
        obj = child_by_field_name(call_node, "object")
        if nm is not None and obj is not None:
            return obj, node_text(nm, src_bytes)
        # not a member call
        return None, None

    if fn.kind() in spec.attribute_kinds:
        lhs = (
            child_by_field_name(fn, "object")
            or child_by_field_name(fn, "operand")
            or child_by_field_name(fn, "value")
            or child_by_field_name(fn, "expression")
        )
        rhs = (
            child_by_field_name(fn, "field")
            or child_by_field_name(fn, "property")
            or child_by_field_name(fn, "name")
        )
        if lhs is not None and rhs is not None:
            return lhs, node_text(rhs, src_bytes)

    return None, None


def is_obs_call(call_node, spec: LangSpec, src_bytes: bytes) -> Optional[str]:
    """If this call is an obs call, return its kind ('span'|'tracer'|'logger'|'metric').

    Else return None. Mirrors `strip/python_strip.py::_is_obs_call` but works
    against tree-sitter nodes for any language present in the LangSpec.
    """
    # Rust macro invocations (`tracing::info!`, `debug!`, `info_span!`, ...).
    # macro_invocation lacks a `function` field, so the generic receiver/
    # method path below cannot classify them. Use the last path segment of
    # the `macro` field directly against the lang's obs-method sets.
    if call_node.kind() == "macro_invocation":
        m = child_by_field_name(call_node, "macro")
        if m is None:
            return None
        last = node_text(m, src_bytes).rsplit("::", 1)[-1].lower()
        if last in spec.logger_methods:
            return "logger"
        if last in spec.tracer_methods:
            return "tracer"
        if last in spec.span_methods:
            return "span"
        if last in spec.metric_methods:
            return "metric"
        return None

    receiver, method = call_receiver_and_method(call_node, spec, src_bytes)
    if receiver is None or method is None:
        return None
    chain = _selector_chain(receiver, spec, src_bytes)
    kind = receiver_kind(chain)
    if kind == "span" and method in spec.span_methods:
        return "span"
    if kind == "tracer" and method in spec.tracer_methods:
        return "tracer"
    if kind == "logger" and method in spec.logger_methods:
        return "logger"
    if kind == "metric" and method in spec.metric_methods:
        return "metric"
    return None


def call_args(call_node, spec: LangSpec) -> list:
    """Return the named-argument children of a call node, in source order."""
    # Rust macro_invocation wraps its args in a `token_tree` child, not in
    # an `arguments` field. Args are the named children of that token_tree.
    if call_node.kind() == "macro_invocation":
        for i in range(call_node.named_child_count()):
            c = call_node.named_child(i)
            if c.kind() == "token_tree":
                return list(iter_named_children(c))
        return []
    args = child_by_field_name(call_node, spec.call_args_field)
    if args is None:
        return []
    return list(iter_named_children(args))


def string_literal_value(node, src_bytes: bytes, spec: LangSpec) -> Optional[str]:
    """If `node` is a string-literal kind, return its decoded VALUE (without quotes).

    Returns None for non-literals (variables, templates with interpolation, etc.).
    For template strings, only return value if there are no interpolations.
    """
    if node is None:
        return None
    if node.kind() not in spec.string_literal_kinds:
        return None
    raw = node_text(node, src_bytes)
    # interpolation in template strings -> bail
    if "template" in node.kind() and "${" in raw:
        return None
    # strip surrounding quotes (handles `"x"`, `'x'`, and Go's `` `x` ``)
    if len(raw) >= 2 and raw[0] in ('"', "'", "`") and raw[-1] == raw[0]:
        return raw[1:-1]
    return raw


def _name_tokens(name_chain: str) -> set[str]:
    """Tokenise a name-chain string the same way Python's `_name_tokens` does.

    Used for the helper-wrapped obs heuristic (any call whose name chain has
    a token intersecting the obs lexicon).
    """
    if not name_chain:
        return set()
    s = name_chain
    for sep in (".", "[", "]", "*", "(", ")", " ", "\t"):
        s = s.replace(sep, "_")
    return {t for t in s.split("_") if t}


def is_helper_obs_call(call_node, spec: LangSpec, src_bytes: bytes) -> bool:
    """Helper-wrapped obs heuristic — any Call whose name-chain tokens
    intersect the obs lexicon. Used by score_anchor / mine, NOT extract.
    """
    chain = _selector_chain(call_node, spec, src_bytes)
    return bool(_name_tokens(chain) & spec.obs_word_tokens)


def is_obs_assignment(assign_node, spec: LangSpec, src_bytes: bytes) -> bool:
    """`x = tracer.Tracer("name")` / `c := meter.NewCounter(...)` etc.

    Two routes:
      (a) LHS variable name is itself an obs token (span / tracer / logger /
          meter / counter / histogram / instr / telemetry / otel ...).
          The LHS check fires for the typical Go idiom
          ``span := trace.SpanFromContext(ctx)`` or Java
          ``Span span = Span.current();``. Implemented language-agnostically
          by splitting the node text on the first ``=`` and tokenising the
          left half — works for ``:=``, ``=``, type-prefixed declarations.
      (b) RHS is a Call whose method starts with one of
          ``setup_method_prefixes`` AND receiver_kind is tracer/metric.
    """
    text = node_text(assign_node, src_bytes)
    # ---- route (a): LHS naming via text split --------------------------------
    eq_idx = text.find("=")
    if eq_idx > 0:
        lhs_text = text[:eq_idx]
        # strip a trailing ':' from := for Go (split on '=' leaves the colon)
        lhs_text = lhs_text.rstrip(":")
        if _name_tokens(lhs_text) & spec.obs_word_tokens:
            # confirm RHS contains a Call expression (cheap heuristic)
            rhs_text = text[eq_idx + 1:]
            if "(" in rhs_text:  # any call
                return True

    # ---- route (b): setup-prefix on RHS receiver -----------------------------
    rhs = (
        child_by_field_name(assign_node, "value")
        or child_by_field_name(assign_node, "right")
    )
    if rhs is None:
        # walk descendants to find first call
        for n in walk_descendants(assign_node, named_only=True):
            if n.kind() in spec.call_kinds:
                rhs = n
                break
    if rhs is None or rhs.kind() not in spec.call_kinds:
        return False

    receiver, method = call_receiver_and_method(rhs, spec, src_bytes)
    if receiver is None or method is None:
        return False
    if not any(method.startswith(p) for p in spec.setup_method_prefixes):
        return False
    chain = _selector_chain(receiver, spec, src_bytes)
    kind = receiver_kind(chain)
    if kind in ("tracer", "metric"):
        return True
    # plain module-level: trace.NewTracer / metrics.NewMeter etc.
    tokens = _name_tokens(chain)
    if tokens & {"trace", "traces", "metrics", "metric", "tracer", "meter"}:
        return True
    return False


def walk_function_calls(fn_node, spec: LangSpec) -> Iterator:
    """Yield every call-expression descendant of `fn_node`, in source order."""
    for n in walk_descendants(fn_node, named_only=True):
        if n.kind() in spec.call_kinds:
            yield n
