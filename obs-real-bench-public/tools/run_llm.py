"""
obs-real-bench: LLM runner.

For each instance:

    1. Load instance JSON.
    2. Re-materialise the *stripped* source by applying obs_patch to the
       ground_truth file at base_commit.
    3. Load prompts/<prompt_level>.md, render template variables.
    4. Validate the rendered prompt against the prompt's `forbid:` list.
    5. Call the model via tools.llm_client (TODO: reuse the Azure OpenAI
       client wiring from obs-bench/tools/run_llm_completion.py).
    6. Save result to results/<run_id>/<instance_id>.json.

Skeleton only. LLM call site is a placeholder.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTANCES = ROOT / "instances"
PROMPTS = ROOT / "prompts"
RESULTS = ROOT / "results"
REPOS = ROOT / "repos"


@dataclass
class PromptTemplate:
    name: str
    forbid: list[str]
    body: str


def load_prompt(level: str) -> PromptTemplate:
    """Load prompts/<level>.md and split frontmatter from body.

    TODO: real YAML frontmatter parsing (the existing obs-bench
    tools/run_llm_completion.py already has a parser — copy it over once
    we wire the runner up).
    """
    raise NotImplementedError("load_prompt: frontmatter parser not yet wired in")


def materialise_stripped(instance: dict) -> dict[str, str]:
    """Apply obs_patch to base_commit files -> return {path: stripped_source}.

    TODO: use `git apply --reverse` or `python-patch-ng` over a checkout of
    repos/<repo>@<base_commit>. For the hand-pilot, the stripped source can
    be carried inline in the instance JSON (skip the patch dance).
    """
    raise NotImplementedError("materialise_stripped: patch application not implemented")


def validate_prompt(rendered: str, forbid: list[str]) -> None:
    """Abort if any forbidden substring appears OUTSIDE the source-code block.

    Matches obs-bench/tools/run_llm_completion.py's safety check.
    """
    # Strip out fenced code blocks before checking the natural-language part.
    in_fence = False
    natural_lines: list[str] = []
    for line in rendered.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            natural_lines.append(line)
    natural = "\n".join(natural_lines).lower()
    for kw in forbid:
        if kw.lower() in natural:
            raise SystemExit(
                f"[abort] forbidden keyword {kw!r} found in rendered prompt. "
                "Refusing to send to the LLM."
            )


def call_llm(rendered_prompt: str, model: str) -> str:
    """Call the configured LLM endpoint and return the raw response text.

    TODO: reuse obs-bench/tools/run_llm_completion.py's Azure OpenAI wiring.
    """
    raise NotImplementedError("call_llm: client wiring not yet copied from obs-bench")


def run_one(instance_path: Path, model: str, out_dir: Path) -> None:
    instance = json.loads(instance_path.read_text())
    prompt = load_prompt(instance["task"]["prompt_level"])
    stripped = materialise_stripped(instance)

    # naive template render — a real one will honour {{LANGUAGE_NAME}}, etc.
    primary = list(stripped.items())[0]
    rendered = (
        prompt.body
        .replace("{{LANGUAGE_NAME}}", instance["target"]["language"])
        .replace("{{LANGUAGE_FENCE}}", instance["target"]["language"])
        .replace("{{FILEPATH}}", primary[0])
        .replace("{{FUNCTION}}", instance["target"].get("function") or "")
        .replace("{{SOURCE}}", primary[1])
        .replace(
            "{{AVAILABLE_IMPORTS}}",
            "\n".join(instance["task"].get("available_imports", [])),
        )
    )
    validate_prompt(rendered, prompt.forbid)

    response = call_llm(rendered, model)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{instance['instance_id']}.json").write_text(
        json.dumps(
            {
                "instance_id": instance["instance_id"],
                "model": model,
                "prompt_level": instance["task"]["prompt_level"],
                "response": response,
            },
            indent=2,
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an LLM over obs-real-bench instances.")
    parser.add_argument("--tier", choices=["function", "file", "system"], required=True)
    parser.add_argument("--model", required=True, help="Model id, passed to call_llm().")
    parser.add_argument(
        "--instance",
        help="Run a single instance by id. If omitted, run all instances in the tier.",
    )
    parser.add_argument(
        "--run-id",
        default="adhoc",
        help="Logical run id (becomes results/<run_id>/).",
    )
    args = parser.parse_args()

    instances_dir = INSTANCES / args.tier
    if args.instance:
        paths = [instances_dir / f"{args.instance}.json"]
    else:
        paths = sorted(p for p in instances_dir.glob("*.json") if not p.name.startswith("_"))

    out_dir = RESULTS / args.run_id / args.tier / args.model
    for p in paths:
        try:
            run_one(p, args.model, out_dir)
        except NotImplementedError as e:
            sys.stderr.write(f"[skip] {p.name}: {e}\n")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
