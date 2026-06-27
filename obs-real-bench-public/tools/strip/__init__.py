"""
obs-stripping module.

Removes observability calls from source code while preserving everything
else. Per-language strippers live in sibling modules.

Function-level contract (what we strip TODAY):
    Only statements INSIDE the named target function are altered. Module
    imports, module-level globals, and other functions are untouched. This
    matches the realistic "instrument this function in an existing project"
    scenario.

File-level contract (planned, NOT YET implemented):
    Strip module-level tracer/meter/logger provider setup as well as
    in-function calls.
"""
from __future__ import annotations


def strip(source: str, *, language: str, function: str) -> str:
    """Dispatch to the per-language stripper.

    Returns the source with obs calls inside the named function removed.
    """
    lang = language.lower()
    if lang in ("python", "py"):
        from . import python_strip
        return python_strip.strip(source, function=function)
    from ..langspec import get as get_langspec
    if get_langspec(lang) is not None:
        from . import ts_strip
        return ts_strip.strip(source, language=lang, function=function)
    raise ValueError(
        f"strip: language={language!r} not implemented yet. "
        "Add a tools.langspec entry."
    )
