"""
obs-site classification module.

Defines the language-agnostic ObsSite schema and dispatcher. Per-language
extractors live in sibling modules (python_extract.py for now;
go_extract.py / java_extract.py to follow, likely backed by tree-sitter).

ObsSite categorisation (kept deliberately small — start broad, refine after
the hand-pilot):

    span_start         tracer.start_*span* / @tracer.start_as_current_span
    span_attribute     span.set_attribute(...)
    span_event         span.add_event(...)
    error_record       span.record_exception / span.set_status(ERROR, ...)
    log_info           logger.info(...) and equivalents
    log_warn           logger.warn / logger.warning(...)
    log_error          logger.error / logger.exception / logger.critical(...)
    metric_add         counter.add(...) / counter.inc()
    metric_observe     histogram.record(...) / gauge.observe(...)

The 'library' field is best-effort: 'opentelemetry' for OTel SDK calls,
'logging' for stdlib logging, vendor names for others.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ObsSite:
    type: str
    library: str
    function: str           # enclosing function (may be "Class.method")
    keys: list[str] = field(default_factory=list)
    # 'snippet' is a short textual fingerprint, useful for human review and as
    # a tie-breaker in matching. It is NOT used in the primary match score.
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract(source: str, *, language: str, function: str | None = None) -> list[ObsSite]:
    """Dispatch to the per-language extractor.

    Parameters
    ----------
    source : str
        Source code of the file (or a fragment).
    language : str
        Language tag. Currently only "python" is supported.
    function : str | None
        Restrict to ObsSites whose enclosing function matches this name.
        Accepts either "free_function" or "ClassName.method". If None,
        all ObsSites in the source are returned.
    """
    lang = language.lower()
    if lang in ("python", "py"):
        from . import python_extract
        return python_extract.extract(source, function=function)
    # all other languages route through the shared tree-sitter extractor;
    # per-language nuance lives in tools.langspec
    from ..langspec import get as get_langspec
    if get_langspec(lang) is not None:
        from . import ts_extract
        return ts_extract.extract(source, language=lang, function=function)
    raise ValueError(
        f"extract: language={language!r} not implemented yet. "
        "Add a tools.langspec entry."
    )
