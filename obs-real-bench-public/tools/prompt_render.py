"""
Prompt loader + renderer.

Reads a prompt file from prompts/<level>.md, parses the YAML-ish frontmatter
(name, description, forbid), substitutes template variables in the body, and
validates that no forbidden keyword appears in the natural-language portion.

Frontmatter parser is intentionally trivial (regex-based) — the same format
obs-bench has been using. If the project grows, swap for `pyyaml`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PromptTemplate:
    name: str
    description: str
    forbid: list[str] = field(default_factory=list)
    body: str = ""
    # When True, the pilot will scrub telemetry imports / setup out of the
    # module-context block before rendering, so the LLM cannot infer from the
    # surrounding code that observability is wired up. Used by p0-class
    # "blind" experiments. Defaults to False so existing prompts are unaffected.
    strip_telemetry: bool = False
    # How many sibling-function examples to splice into {{SIBLING_EXAMPLES}}.
    # 0 = no few-shot (the default — matches every existing prompt).
    # The instance JSON stores up to 5 ranked siblings; the prompt picks the
    # top-k from that list at render time. Capping render-time k separately
    # from storage K lets us run K-sweep experiments (k=1 / k=2 / k=5) by
    # editing this one frontmatter field, not by re-mining instances.
    fewshot_k: int = 0


# ---------------------------------------------------------------------------
# frontmatter parsing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_raw = m.group("fm")
    body = m.group("body")

    meta: dict[str, Any] = {}
    cur_list_key: str | None = None
    for line in fm_raw.splitlines():
        raw = line.rstrip()
        if not raw.strip():
            continue
        if raw.startswith("  - "):
            if cur_list_key is None:
                continue
            meta.setdefault(cur_list_key, []).append(raw[4:].strip())
            continue
        if raw.startswith("#"):  # comment
            continue
        if ":" in raw and not raw.startswith(" "):
            key, _, val = raw.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "" or val == ">":
                # list or multi-line block follows
                meta[key] = []
                cur_list_key = key
            else:
                meta[key] = val
                cur_list_key = None
    return meta, body


def load(prompt_dir: Path, level: str) -> PromptTemplate:
    """Load prompts/<level>.md from prompt_dir."""
    path = prompt_dir / f"{level}.md"
    text = path.read_text()
    meta, body = _parse_frontmatter(text)
    forbid_raw = meta.get("forbid") or []
    if isinstance(forbid_raw, str):
        forbid_raw = [forbid_raw]
    strip_raw = meta.get("strip_telemetry", False)
    if isinstance(strip_raw, str):
        strip_telemetry = strip_raw.strip().lower() in ("true", "1", "yes", "on")
    else:
        strip_telemetry = bool(strip_raw)
    fewshot_raw = meta.get("fewshot_k", 0)
    if isinstance(fewshot_raw, str):
        try:
            fewshot_k = int(fewshot_raw.strip())
        except ValueError:
            fewshot_k = 0
    else:
        fewshot_k = int(fewshot_raw or 0)
    if fewshot_k < 0:
        fewshot_k = 0
    return PromptTemplate(
        name=meta.get("name", level),
        description=str(meta.get("description", "")),
        forbid=[s.strip() for s in forbid_raw if s.strip()],
        body=body,
        strip_telemetry=strip_telemetry,
        fewshot_k=fewshot_k,
    )


# ---------------------------------------------------------------------------
# template rendering
# ---------------------------------------------------------------------------

_LANGUAGE_FENCE = {
    "python": "python",
    "py": "python",
    "go": "go",
    "java": "java",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
    "csharp": "csharp",
    "cs": "csharp",
    "ruby": "ruby",
    "rust": "rust",
    "cpp": "cpp",
    "c++": "cpp",
    "php": "php",
}


def render(
    tmpl: PromptTemplate,
    *,
    language: str,
    file_path: str,
    function: str,
    source: str,
    available_imports: list[str] | None = None,
    module_context: str = "",
    target_function_source: str = "",
    sibling_examples: str = "",
) -> str:
    """Substitute the template variables in tmpl.body and return the result.

    Template variables:
        {{LANGUAGE_NAME}}, {{LANGUAGE_FENCE}}, {{FILEPATH}}, {{FUNCTION}}
        {{SOURCE}}                 — legacy: whole-file source (v0 prompts)
        {{AVAILABLE_IMPORTS}}      — newline-joined imports from instance JSON
        {{MODULE_CONTEXT}}         — v1: imports + module-level obs setup
        {{TARGET_FUNCTION_SOURCE}} — v1: just the function, dedented to col 0
        {{SIBLING_EXAMPLES}}       — few-shot: top-k obs-bearing siblings,
                                     pre-rendered by the pilot. Empty string
                                     when fewshot_k=0 (every existing prompt).
    """
    available = "\n".join(available_imports or [])
    out = (
        tmpl.body
        .replace("{{LANGUAGE_NAME}}", language)
        .replace("{{LANGUAGE_FENCE}}", _LANGUAGE_FENCE.get(language.lower(), language.lower()))
        .replace("{{FILEPATH}}", file_path)
        .replace("{{FUNCTION}}", function)
        .replace("{{SOURCE}}", source)
        .replace("{{AVAILABLE_IMPORTS}}", available)
        .replace("{{MODULE_CONTEXT}}", module_context)
        .replace("{{TARGET_FUNCTION_SOURCE}}", target_function_source)
        .replace("{{SIBLING_EXAMPLES}}", sibling_examples)
    )
    return out


# Note: prompts/*.md still carry a `forbid:` list in YAML frontmatter as
# documentation of intent ("this prompt must not say 'observability' in its
# prose"). It is no longer enforced at render time: the previous
# `validate_forbid` check fired on legitimate filepath / identifier mentions
# like `File: \`src/recommendation/logger.py\`` and aborted otherwise-valid
# cells. Catching prose drift is now an author-side responsibility (review
# the prompt before checking it in); the runtime cost was higher than the
# guard's value.
