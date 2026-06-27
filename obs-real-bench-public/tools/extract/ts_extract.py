"""
Tree-sitter-based ObsSite extractor (non-Python).

Replicates the SHAPE of `python_extract.py` (same ObsSite schema, same type
labels) using `ts_obs` primitives, so the rest of the pipeline (score_anchor
on Python AST, build_siblings, the result.json schema) doesn't have to learn
new shapes.

What this does:
  - Locates the target function with `ts_obs.find_function`.
  - Walks call expressions inside the function body.
  - Classifies each obs call into one of:
        span_start | span_attribute | span_event | error_record
        log_debug | log_info | log_warn | log_error
        metric_add | metric_observe
  - Emits an ObsSite per matching call.

Key extraction (for `keys`) is BEST-EFFORT and language-shaped:
  - `span.set_attribute("k", v)` style: keys = [first-string-arg]
  - `span.add_event("name", ...)`     : keys = [first-string-arg]
  - `tracer.Start(ctx, "name", ...)`  : keys = [string arg at the position
                                         indicated by langspec.tracer_start_name_arg]
  - Other patterns (logger / metric / bulk-set-attributes): keys = []
  - Per-language nuance (e.g. Java's `setAttribute(AttributeKey, v)` does NOT
    have a string-literal key) is left empty rather than guessed.
"""
from __future__ import annotations

from typing import Optional

from . import ObsSite
from .. import ts_obs
from ..langspec import LangSpec, require as require_langspec


# How to know which arg index of a tracer-start call holds the span name.
# Python's `start_as_current_span("name")`        -> 0
# Go's `tracer.Start(ctx, "name", opts...)`        -> 1
# Java's `tracer.spanBuilder("name").startSpan()`  -> 0  (on spanBuilder, before .startSpan)
# .NET's `source.StartActivity("name")`            -> 0
# This is encoded as a hint per language; default to 0.
_TRACER_NAME_ARG_INDEX = {
    "go": 1,
}


def _short_snippet(text: str, max_len: int = 80) -> str:
    s = " ".join(text.split())
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def _classify(call_kind: str, method: str, spec: LangSpec) -> Optional[str]:
    """Return the ObsSite.type label for an obs call.

    `call_kind` is the receiver kind from `ts_obs.receiver_kind`.
    `method` is the called method name (preserves original case).
    Returns None if the (kind, method) combination is not an obs site.
    """
    if call_kind == "span":
        if method not in spec.span_methods:
            return None
        m = method
        if "Attribute" in m or m.startswith("setAttribute") or m == "SetTag" or m == "AddTag":
            return "span_attribute"
        if "Event" in m or m.endswith("event"):
            return "span_event"
        if "Status" in m or "Error" in m or "Exception" in m or m == "recordException":
            return "error_record"
        # Unknown span method that nevertheless made it into the langspec —
        # bucket as span_attribute (safe-ish default; would only happen if
        # a maintainer adds a new method to the langspec but not here).
        return "span_attribute"

    if call_kind == "tracer":
        if method not in spec.tracer_methods:
            return None
        return "span_start"

    if call_kind == "logger":
        if method not in spec.logger_methods:
            return None
        return spec.log_method_to_type.get(method, "log_info")

    if call_kind == "metric":
        if method not in spec.metric_methods:
            return None
        if method in ("add", "Add", "inc", "Inc"):
            return "metric_add"
        return "metric_observe"

    return None


def _library_for(type_label: str) -> str:
    """Map an ObsSite type to a library bucket. Matches python_extract."""
    if type_label.startswith("log_"):
        # Python emits 'logging' for both stdlib and OTel logger paths; keep
        # the same label here so result.json schemas line up.
        return "logging"
    return "opentelemetry"


def _extract_keys(
    call_node,
    type_label: str,
    spec: LangSpec,
    src_bytes: bytes,
    method: str,
) -> list[str]:
    """Best-effort key extraction; returns empty list if no string-literal key."""
    args = ts_obs.call_args(call_node, spec)
    if not args:
        return []
    if type_label == "span_start":
        idx = _TRACER_NAME_ARG_INDEX.get(spec.name, 0)
        if idx < len(args):
            v = ts_obs.string_literal_value(args[idx], src_bytes, spec)
            return [v] if v else []
        return []
    if type_label == "span_event":
        v = ts_obs.string_literal_value(args[0], src_bytes, spec)
        return [v] if v else []
    if type_label == "span_attribute":
        # Only the Python-style `setAttribute("k", v)` shape has a string-literal key
        # at arg index 0. Go-style `SetAttributes(attribute.String("k", v))` does NOT —
        # the key is buried inside a nested call. We skip nested-call key extraction
        # for now (best-effort).
        v = ts_obs.string_literal_value(args[0], src_bytes, spec)
        return [v] if v else []
    return []


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def extract(source: str, *, language: str, function: Optional[str] = None) -> list[ObsSite]:
    """Extract ObsSites from `source`. Mirrors `python_extract.extract`."""
    spec = require_langspec(language)
    src_bytes = source.encode("utf-8")
    tree = ts_obs.parse(source, language)

    sites: list[ObsSite] = []

    if function is None:
        # walk the whole tree
        root = tree.root_node()
        for call in ts_obs.walk_descendants(root, named_only=True):
            if call.kind() not in spec.call_kinds:
                continue
            _maybe_emit(call, spec, src_bytes, "<module>", sites)
        return sites

    loc = ts_obs.find_function(tree, language, function, src_bytes)
    if loc is None:
        # Stay strict like python_extract — raise so caller knows the target
        # symbol does not exist in this source.
        raise ValueError(f"function not found: {function}")

    for call in ts_obs.walk_function_calls(loc.node, spec):
        _maybe_emit(call, spec, src_bytes, function, sites)
    return sites


def _maybe_emit(call_node, spec: LangSpec, src_bytes: bytes, function_label: str, sites: list[ObsSite]) -> None:
    # Rust macros (`tracing::info!`, `info_span!`, ...) have no receiver/
    # method fields. Use is_obs_call to classify, then derive method from
    # the last segment of the macro path.
    if call_node.kind() == "macro_invocation":
        kind = ts_obs.is_obs_call(call_node, spec, src_bytes)
        if kind is None:
            return
        m_node = ts_obs.child_by_field_name(call_node, "macro")
        if m_node is None:
            return
        method = ts_obs.node_text(m_node, src_bytes).rsplit("::", 1)[-1]
        type_label = _classify(kind, method.lower(), spec)
        if type_label is None:
            return
        sites.append(
            ObsSite(
                type=type_label,
                library=_library_for(type_label),
                function=function_label,
                keys=_extract_keys(call_node, type_label, spec, src_bytes, method),
                snippet=_short_snippet(ts_obs.node_text(call_node, src_bytes)),
            )
        )
        return

    receiver, method = ts_obs.call_receiver_and_method(call_node, spec, src_bytes)
    if receiver is None or method is None:
        return
    chain = ts_obs._selector_chain(receiver, spec, src_bytes)
    kind = ts_obs.receiver_kind(chain)
    if kind is None:
        return
    type_label = _classify(kind, method, spec)
    if type_label is None:
        return
    sites.append(
        ObsSite(
            type=type_label,
            library=_library_for(type_label),
            function=function_label,
            keys=_extract_keys(call_node, type_label, spec, src_bytes, method),
            snippet=_short_snippet(ts_obs.node_text(call_node, src_bytes)),
        )
    )
