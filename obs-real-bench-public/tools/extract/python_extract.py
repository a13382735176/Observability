"""
Python ObsSite extractor (stdlib ast-based).

Walks a parsed module and reports every observability call site found inside
the requested target function. The output schema lives in
extract/__init__.py (ObsSite).

Heuristic, not exhaustive — works on idiomatic OTel-demo / OTel-Python code:

    span_start         `with tracer.start_as_current_span(name):`
                       or `tracer.start_span(name)`
    span_attribute     `<span>.set_attribute(key, value)`
    span_event         `<span>.add_event(name, ...)`
    error_record       `<span>.record_exception(...)`
                       or `<span>.set_status(...)`  (any status)
    log_*              `<logger>.info|debug|warning|warn|error|exception|critical(...)`
    metric_add         `<counter>.add(...)`
    metric_observe     `<histogram>.record(...)` / `<gauge>.observe(...)`

A receiver is treated as observability when:
    - it is a Name whose lowercase form contains 'span', 'tracer', 'logger',
      'log' (alone or as token suffix `*_log`), 'logging' (the stdlib module),
      'meter', 'counter', 'histogram', 'gauge', or 'metric'
    - OR it is a Subscript whose value-name contains those words
      (e.g. `rec_svc_metrics["counter_x"].add(...)`)
"""
from __future__ import annotations

import ast
from typing import Optional

from . import ObsSite


_SPAN_RECEIVER_KEYWORDS = ("span",)
_TRACER_RECEIVER_KEYWORDS = ("tracer",)
# Documented set of *token-level* logger names. `_receiver_kind` also accepts
# any token ending in `_log` (covers `audit_log`, `event_log`, etc.) and the
# substring 'logger' for compound names like `app.logger`, `_logger`,
# `loguru.logger`, `structlog.get_logger`.
_LOGGER_RECEIVER_TOKENS = ("log", "logger", "logging")
_METRIC_RECEIVER_KEYWORDS = ("meter", "counter", "histogram", "gauge", "metric")

_LOG_METHOD_TO_TYPE = {
    "debug": "log_debug",
    "info": "log_info",
    "warning": "log_warn",
    "warn": "log_warn",
    "error": "log_error",
    "exception": "log_error",
    "critical": "log_error",
    "fatal": "log_error",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _receiver_name_chain(node: ast.AST) -> str:
    """Return a dotted lowercase representation of a receiver expression.

    For `rec_svc_metrics["x"]` returns 'rec_svc_metrics[]'.
    For `self.tracer` returns 'self.tracer'.
    For `tracer` returns 'tracer'.
    For unsupported shapes returns ''.
    """
    if isinstance(node, ast.Name):
        return node.id.lower()
    if isinstance(node, ast.Attribute):
        prefix = _receiver_name_chain(node.value)
        return f"{prefix}.{node.attr.lower()}" if prefix else node.attr.lower()
    if isinstance(node, ast.Subscript):
        prefix = _receiver_name_chain(node.value)
        return f"{prefix}[]" if prefix else "[]"
    if isinstance(node, ast.Call):
        return _receiver_name_chain(node.func)
    return ""


def _receiver_kind(receiver: ast.AST) -> Optional[str]:
    """Classify a receiver node as 'span' / 'tracer' / 'logger' / 'metric'."""
    name = _receiver_name_chain(receiver)
    if not name:
        return None
    # check most specific first
    for kw in _SPAN_RECEIVER_KEYWORDS:
        if kw in name:
            return "span"
    for kw in _TRACER_RECEIVER_KEYWORDS:
        if kw in name:
            return "tracer"
    # 'logger' substring catches any of: `logger`, `app.logger`, `_logger`,
    # `my_logger`, `loguru.logger`, `structlog.get_logger()`, `getLogger()`.
    # Goes BEFORE the 'log' token check so it wins over the (rarer) 'log'
    # exact-token rule below.
    if "logger" in name:
        return "logger"
    # Token-level match for `log`-flavoured receivers. Use token equality
    # (or _log suffix) to avoid over-matching on `login`, `blog`, `dialog`,
    # `analog`, `prologue`, etc. Accept:
    #   - bare token `log`          (e.g. `self.log.info(...)`)
    #   - bare token `logging`      (stdlib module: `logging.warning(...)`)
    #   - any token ending in `_log` (e.g. `audit_log`, `event_log`, `_log`)
    # The method-name filter (must be debug/info/warn/error/exception/etc.)
    # downstream prevents false positives on non-logger receivers that happen
    # to share these token shapes.
    tokens = name.replace("[]", "").split(".")
    for tok in tokens:
        if tok in _LOGGER_RECEIVER_TOKENS or tok.endswith("_log"):
            return "logger"
    for kw in _METRIC_RECEIVER_KEYWORDS:
        if kw in name:
            return "metric"
    return None


def _string_arg(node: ast.AST) -> Optional[str]:
    """If node is a Constant string, return its value, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _snippet(node: ast.AST, max_len: int = 80) -> str:
    try:
        s = ast.unparse(node)
    except Exception:
        s = ""
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


# ---------------------------------------------------------------------------
# function locator
# ---------------------------------------------------------------------------

def _find_function(tree: ast.Module, target: str) -> ast.AST:
    """Resolve 'Class.method' or 'free_function' to its AST node."""
    if "." in target:
        class_name, method_name = target.split(".", 1)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if (
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == method_name
                    ):
                        return item
        raise ValueError(f"function not found: {target}")
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == target
        ):
            return node
    raise ValueError(f"function not found: {target}")


# ---------------------------------------------------------------------------
# core visitor
# ---------------------------------------------------------------------------

class _SiteCollector(ast.NodeVisitor):
    def __init__(self, function_label: str) -> None:
        self.sites: list[ObsSite] = []
        self.function_label = function_label

    # ----- span_start via `with tracer.start_as_current_span(...)` -----
    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            ctx = item.context_expr
            if isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Attribute):
                if _receiver_kind(ctx.func.value) == "tracer" and (
                    ctx.func.attr.startswith("start_") or ctx.func.attr == "start_span"
                ):
                    name_arg = ctx.args[0] if ctx.args else None
                    self.sites.append(
                        ObsSite(
                            type="span_start",
                            library="opentelemetry",
                            function=self.function_label,
                            keys=[_string_arg(name_arg) or ""],
                            snippet=_snippet(ctx),
                        )
                    )
        # IMPORTANT: walk only the body, NOT the items, otherwise
        # `tracer.start_as_current_span(...)` gets double-counted by visit_Call.
        for stmt in node.body:
            self.visit(stmt)

    # ----- everything else expressed as Call -----
    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            kind = _receiver_kind(node.func.value)
            method = node.func.attr

            # span methods
            if kind == "span":
                if method == "set_attribute":
                    key = _string_arg(node.args[0]) if node.args else None
                    self.sites.append(
                        ObsSite(
                            type="span_attribute",
                            library="opentelemetry",
                            function=self.function_label,
                            keys=[key] if key else [],
                            snippet=_snippet(node),
                        )
                    )
                elif method == "set_attributes":
                    # bulk: dict literal -> keys
                    keys: list[str] = []
                    if node.args and isinstance(node.args[0], ast.Dict):
                        for k in node.args[0].keys:
                            sk = _string_arg(k) if k is not None else None
                            if sk:
                                keys.append(sk)
                    self.sites.append(
                        ObsSite(
                            type="span_attribute",
                            library="opentelemetry",
                            function=self.function_label,
                            keys=keys,
                            snippet=_snippet(node),
                        )
                    )
                elif method == "add_event":
                    name = _string_arg(node.args[0]) if node.args else None
                    self.sites.append(
                        ObsSite(
                            type="span_event",
                            library="opentelemetry",
                            function=self.function_label,
                            keys=[name] if name else [],
                            snippet=_snippet(node),
                        )
                    )
                elif method in ("record_exception", "set_status"):
                    self.sites.append(
                        ObsSite(
                            type="error_record",
                            library="opentelemetry",
                            function=self.function_label,
                            keys=[],
                            snippet=_snippet(node),
                        )
                    )

            # tracer.start_span() outside of a `with`
            elif kind == "tracer" and method in ("start_span", "start_as_current_span"):
                # Caught above in visit_With if used as ctx manager. This branch
                # handles the imperative form.
                name = _string_arg(node.args[0]) if node.args else None
                self.sites.append(
                    ObsSite(
                        type="span_start",
                        library="opentelemetry",
                        function=self.function_label,
                        keys=[name] if name else [],
                        snippet=_snippet(node),
                    )
                )

            # logger methods
            elif kind == "logger":
                if method in _LOG_METHOD_TO_TYPE:
                    self.sites.append(
                        ObsSite(
                            type=_LOG_METHOD_TO_TYPE[method],
                            library="logging",
                            function=self.function_label,
                            keys=[],
                            snippet=_snippet(node),
                        )
                    )

            # metric methods
            elif kind == "metric":
                if method in ("add", "inc"):
                    self.sites.append(
                        ObsSite(
                            type="metric_add",
                            library="opentelemetry",
                            function=self.function_label,
                            keys=[],
                            snippet=_snippet(node),
                        )
                    )
                elif method in ("record", "observe"):
                    self.sites.append(
                        ObsSite(
                            type="metric_observe",
                            library="opentelemetry",
                            function=self.function_label,
                            keys=[],
                            snippet=_snippet(node),
                        )
                    )

        self.generic_visit(node)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def extract(source: str, *, function: str | None = None) -> list[ObsSite]:
    tree = ast.parse(source)
    if function is None:
        collector = _SiteCollector(function_label="<module>")
        collector.visit(tree)
        return collector.sites
    fn_node = _find_function(tree, function)
    collector = _SiteCollector(function_label=function)
    collector.visit(fn_node)
    return collector.sites
