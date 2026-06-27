#!/usr/bin/env python3
"""Build the observability-skill regeneration experiment assets.

This tool has two deliberately separate phases:

1. extract: read the existing service contracts and write source-free specs plus
   Copilot SDK prompts under experiments/skill_observability/.
2. materialize: create services_skill/<service>-skill harness skeletons that are
   compatible with _lib/run-common.sh but do not copy business source code.

The generated prompts are allowed to describe architecture, endpoints, schemas,
dependencies, and runtime contracts. They intentionally omit baseline logs and
implementation details so the regeneration agent performs a clean reimplementation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import difflib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SERVICES_ROOT = ROOT / "services"
SKILL_SERVICES_ROOT = ROOT / "services_skill"
EXP_ROOT = ROOT / "experiments" / "skill_observability"
SPECS_ROOT = EXP_ROOT / "specs"
PROMPTS_ROOT = EXP_ROOT / "prompts"
MANIFEST_ROOT = EXP_ROOT / "manifests"
ISOLATED_ROOT = EXP_ROOT / "isolated_workspaces"
NAMESPACE = "vibe-coding"


OBSERVABILITY_SKILL = """1. Discover the operational role.
   Generation mode: identify the service responsibility, endpoints, background
   work, state, dependencies, startup and shutdown behavior, and operational
   boundaries where failures or latency would affect users.
2. Mine or establish observability conventions.
   Generation mode: follow local project conventions if they exist. Otherwise,
   choose simple, idiomatic application-level observability for the selected
   stack, with consistent service, operation, dependency, error, latency, and
   request context fields.
3. Plan diagnostic signals internally.
   Add only signals with clear operational value. Each signal should help an
   operator understand failure, latency, throughput, or an important state
   transition. Prefer dependency boundaries and control-flow boundaries. Avoid
   high-cardinality fields, secrets, credentials, tokens, raw payloads, or PII.
4. Instrument only the target scope.
   Generation mode: include observability inside the generated service's
   handlers, dependency calls, background tasks, startup and shutdown, and error
   handling, without adding unrelated infrastructure or external telemetry
   stacks unless explicitly requested.
5. Self-check internally.
   Generation mode: check that the generated code remains simple, runnable, and
   diagnosable from its own application-level signals during ordinary failures,
   latency, and degraded paths. Remove noisy or duplicate signals.
"""


FAILURE_OR_OBSERVABILITY_RX = re.compile(
    r"(\bF\d{2}\b|\bF\d{2}-|故障|注入|注射|异常|错误|失败|超时|降级|不可用|熔断|重试|"
    r"timeout|timed out|failure|fault|error|exception|unavailable|refused|reset|slow|latency|"
    r"5xx|50[0-9]|502|503|504|log|logs|logged|stdout|stderr|日志|打印)",
    flags=re.I,
)


LANG_LABELS = {
    "python": "Python",
    "go": "Go",
    "typescript": "TypeScript/Node.js",
    "java": "Java",
    "rust": "Rust",
    "kotlin": "Kotlin",
    "csharp": "C#/.NET",
    "ruby": "Ruby",
    "php": "PHP",
    "scala": "Scala",
    "cpp": "C++",
    "elixir": "Elixir",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def service_dirs(limit: int | None = None, names: list[str] | None = None) -> list[Path]:
    if names:
        dirs = [SERVICES_ROOT / name for name in names]
    else:
        dirs = sorted(
            [p for p in SERVICES_ROOT.iterdir() if p.is_dir() and re.match(r"^\d+-", p.name)],
            key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", p.name)],
        )
    if limit is not None:
        dirs = dirs[:limit]
    missing = [str(p) for p in dirs if not p.exists()]
    if missing:
        raise SystemExit(f"missing service dirs: {', '.join(missing)}")
    return dirs


def parse_run_sh(path: Path) -> dict[str, Any]:
    raw = read_text(path)
    def one(name: str, default: str = "") -> str:
        m = re.search(rf'^{name}="([^"]*)"', raw, flags=re.M)
        return m.group(1) if m else default

    faults_match = re.search(r"^FAULTS=\((.*?)\)", raw, flags=re.M | re.S)
    faults = re.findall(r'"([^"]+)"', faults_match.group(1) if faults_match else "")
    return {
        "service_id": one("SERVICE_ID", path.parent.name),
        "app_label": one("APP_LABEL", path.parent.name.split("-", 1)[-1]),
        "language": one("LANG", "unknown"),
        "faults": faults,
        "smoke_path": one("SMOKE_PATH", "/healthz"),
    }


def extract_k8s_contract(path: Path, old_service_id: str, old_app: str) -> dict[str, Any]:
    raw = read_text(path) if path.exists() else ""
    env = []
    for name, value in re.findall(r"name:\s*([^,}\s]+).*?value:\s*\"?([^\"}\n]+)\"?", raw):
        env.append({"name": name.strip(), "value": value.strip()})
    image_match = re.search(r"image:\s*([^\s]+)", raw)
    readiness_match = re.search(r"httpGet:\s*\{\s*path:\s*([^,}]+)", raw)
    return {
        "namespace": NAMESPACE,
        "deployment": old_app,
        "service": old_app,
        "app_label": old_app,
        "image": image_match.group(1) if image_match else f"vibe/{old_service_id}:dev",
        "port": 8080,
        "env": env,
        "readiness_path": readiness_match.group(1).strip() if readiness_match else "/healthz",
    }


def deps_from_contract(k8s: dict[str, Any], spec_text: str) -> list[str]:
    names = {item["name"] for item in k8s.get("env", [])}
    dependency_text = dependency_field(spec_text)
    deps: set[str] = set()
    if "PG_DSN" in names or re.search(r"\b(postgres|postgresql|pg_dsn)\b", dependency_text, flags=re.I):
        deps.add("postgres")
    if any(n.startswith("REDIS_CACHE") for n in names) or re.search(r"\b(redis-cache|cache)\b", dependency_text, flags=re.I):
        deps.add("redis-cache")
    if any(n.startswith("REDIS_STREAM") for n in names) or re.search(r"\b(redis-stream|stream|queue)\b", dependency_text, flags=re.I):
        deps.add("redis-stream")
    if "UPSTREAM_URL" in names or re.search(r"\b(mock-upstream|upstream|external)\b", dependency_text, flags=re.I):
        deps.add("mock-upstream")
    return sorted(deps)


def dependency_field(spec_text: str) -> str:
    rows = []
    for line in spec_text.splitlines():
        m = re.match(r"^\|\s*(?:依赖|Dependencies?)\s*\|\s*([^|]+)\|", line, flags=re.I)
        if m:
            rows.append(m.group(1).strip())
    return "\n".join(rows)


def section(text: str, heading_names: list[str]) -> str:
    alternatives = "|".join(re.escape(h) for h in heading_names)
    m = re.search(rf"^##\s+(?:{alternatives})\s*$\n(?P<body>.*?)(?=^##\s+|\Z)", text, flags=re.M | re.S)
    return m.group("body").strip() if m else ""


def sanitize_behavior(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"^-{3,}\s*$", "", text, flags=re.M)
    # Drop explicit logging conventions; the skill run should invent its own,
    # but preserve behavioral semantics such as status codes and fallback paths.
    text = re.sub(r"[，,;；]?\s*(?:并)?(?:在\s*)?stdout\s*打印\s*`[^`]*`\s*行?", "", text, flags=re.I)
    text = re.sub(r"[，,;；]?\s*(?:and\s+)?(?:log|logs|logged|print|prints|printed)\s+`[^`]*`[^。.;\n]*", "", text, flags=re.I)
    text = re.sub(r"[，,;；]?\s*(?:日志|打印)[^。.;\n]*(?:`[^`]*`)?", "", text)
    text = drop_failure_or_observability_sentences(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text = re.sub(r"\s+([。.;；])", r"\1", text)
    text = re.sub(r"([。.;；]){2,}", r"\1", text)
    text = re.sub(r"^[.。;；\s]+$", "", text).strip()
    return text


def sanitize_architecture_text(text: str) -> str:
    text = sanitize_behavior(text)
    return text if text else ""


def drop_failure_or_observability_sentences(text: str) -> str:
    parts = re.split(r"([。.;；\n])", text)
    kept: list[str] = []
    for i in range(0, len(parts), 2):
        sentence = parts[i].strip()
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        if not sentence:
            continue
        if FAILURE_OR_OBSERVABILITY_RX.search(sentence):
            continue
        kept.append(sentence + (sep if sep != "\n" else "\n"))
    return "".join(kept).strip()


def extract_endpoints(spec_text: str) -> list[str]:
    endpoints: list[str] = []
    body = section(spec_text, ["端点", "Endpoints"])
    fenced = re.search(r"```\s*\n(?P<body>.*?)\n```", body, flags=re.S)
    if fenced:
        for line in fenced.group("body").splitlines():
            line = line.strip()
            if line:
                endpoints.append(sanitize_endpoint_line(line))
    else:
        for line in body.splitlines():
            line = re.sub(r"^[-*]\s*", "", line.strip())
            if re.match(r"`?(GET|POST|PUT|PATCH|DELETE)\s+", line):
                endpoints.append(sanitize_endpoint_line(line.strip("`")))

    return [line for line in endpoints if line]


def sanitize_endpoint_line(line: str) -> str:
    parts = re.split(r"([;；。])", line)
    kept: list[str] = []
    for i in range(0, len(parts), 2):
        part = parts[i].strip()
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        if not part:
            continue
        if FAILURE_OR_OBSERVABILITY_RX.search(part):
            continue
        kept.append(part + sep)
    cleaned = " ".join(kept).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(";；。 ")


def extract_state_contracts(service_dir: Path, spec_text: str) -> dict[str, Any]:
    skip_parts = {"faults", "k8s", "target", "build", "dist", "node_modules", "__pycache__", ".gradle"}
    allowed_suffixes = {".py", ".go", ".java", ".kt", ".kts", ".ts", ".js", ".rs", ".rb", ".php", ".cs", ".scala", ".cpp", ".hpp", ".ex", ".exs", ".sql", ".md"}
    allowed_names = {"pom.xml", "Cargo.toml", "go.mod", "package.json", "composer.json", "Gemfile", "CMakeLists.txt", "mix.exs"}
    scan_files = [
        p for p in service_dir.rglob("*")
        if p.is_file()
        and not any(part in skip_parts for part in p.relative_to(service_dir).parts)
        and (p.suffix in allowed_suffixes or p.name in allowed_names)
    ]
    blob_parts = []
    for path in scan_files:
        if path.stat().st_size <= 256_000:
            text = read_text(path)
            if "\x00" not in text:
                blob_parts.append(text)
    blob = "\n".join(blob_parts)
    create_tables = []
    for raw_sql in extract_create_table_statements(spec_text + "\n" + blob):
        sql = normalize_sql(raw_sql)
        if sql not in create_tables:
            create_tables.append(sql)
    backtick_terms = sorted(set(re.findall(r"`([^`]*(?::|\{)[^`]*)`", spec_text)))
    redis_terms = []
    for term in backtick_terms:
        if "\n" in term or term.startswith("vibe/") or term == "imagePullPolicy: Never":
            continue
        if "::" in term or FAILURE_OR_OBSERVABILITY_RX.search(term):
            continue
        if re.search(r"^[A-Za-z0-9_.-]+:[A-Za-z0-9_{}:.-]+$", term):
            redis_terms.append(term)
    return {
        "postgres_schema_sql": create_tables,
        "named_state_keys_or_streams": redis_terms,
    }


def extract_create_table_statements(text: str) -> list[str]:
    statements: list[str] = []
    pattern = re.compile(r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+[A-Za-z_][A-Za-z0-9_.\"]*\s*\(", flags=re.I)
    for match in pattern.finditer(text):
        start = match.start()
        pos = match.end() - 1
        depth = 0
        end = pos
        while end < len(text):
            char = text[end]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    end += 1
                    if end < len(text) and text[end] == ";":
                        end += 1
                    statements.append(text[start:end])
                    break
            end += 1
    return statements


def normalize_sql(raw: str) -> str:
    sql = raw
    sql = re.sub(r'"\s*\+\s*"', " ", sql)
    sql = re.sub(r'"\s*\+\s*', " ", sql)
    sql = re.sub(r'\s*\+\s*"', " ", sql)
    sql = sql.replace('\\"', '"')
    sql = re.sub(r"\s+", " ", sql).strip()
    sql = re.sub(r'["\']\s*\)\s*;?$', "", sql).strip()
    return sql


def sanitize_dockerfile(raw: str, old_id: str, old_app: str, new_id: str, new_app: str) -> str:
    text = raw.replace(f"vibe/{old_id}:dev", f"vibe/{new_id}:dev")
    text = text.replace(old_id, new_id)
    text = re.sub(rf"\b{re.escape(old_app)}\b", new_app, text)
    text = rewrite_dockerfile_for_src_only(text)
    return text.strip() + "\n"


def rewrite_dockerfile_for_src_only(text: str) -> str:
    replacements = [
        (r"^COPY pom\.xml \.$", "COPY src/pom.xml ."),
        (r"^COPY src/ src/$", "COPY src/src/ src/"),
        (r"^COPY \*\.csproj \.$", "COPY src/*.csproj ."),
        (r"^COPY Cargo\.toml \.$", "COPY src/Cargo.toml ."),
        (r"^COPY package\*\.json \./$", "COPY src/package*.json ./"),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.M)

    # .NET services historically keep Program.cs at service root. In isolated
    # generation, the complete app tree lives under src/.
    if "dotnet restore" in text and "COPY . ." in text:
        text = text.replace("COPY . .", "COPY src/ .")

    # Rust services use Cargo.toml at root plus src/ source tree.
    if "cargo build" in text and "COPY src/ src/" in text:
        text = text.replace("COPY src/ src/", "COPY src/src/ src/")
    return text


def extract_docker_contract(service_dir: Path, old_id: str, old_app: str, new_id: str, new_app: str) -> dict[str, Any]:
    dockerfile = service_dir / "Dockerfile"
    dockerfile_text = sanitize_dockerfile(read_text(dockerfile), old_id, old_app, new_id, new_app) if dockerfile.exists() else ""
    return {
        "build_context_after_import": f"services_skill/{new_id}",
        "image": f"vibe/{new_id}:dev",
        "source_root_visible_to_generator": "src",
        "generator_may_create_or_modify": ["src/**"],
        "generator_must_not_create_or_modify": ["anything outside src/"],
        "validation_command_after_import": f"docker build -t vibe/{new_id}:dev .",
        "dockerfile_used_by_private_harness": dockerfile_text,
    }


def extract_spec(service_dir: Path) -> dict[str, Any]:
    run_info = parse_run_sh(service_dir / "run.sh")
    spec_text = read_text(service_dir / "SPEC.md") if (service_dir / "SPEC.md").exists() else ""
    exercise_text = read_text(service_dir / "exercise.sh") if (service_dir / "exercise.sh").exists() else ""
    k8s = extract_k8s_contract(service_dir / "k8s" / "deployment.yaml", run_info["service_id"], run_info["app_label"])
    summary = spec_text.splitlines()[0].lstrip("# ").strip() if spec_text else run_info["service_id"]
    body_intro = ""
    intro_match = re.search(r"^>\s*(.*?)\n\n", spec_text, flags=re.S | re.M)
    if intro_match:
        body_intro = intro_match.group(1).strip()
    behavior = sanitize_behavior(section(spec_text, ["行为约定", "Behavior", "Behaviour"]))
    service_id = run_info["service_id"]
    skill_service_id = f"{service_id}-skill"
    app_label = run_info["app_label"]
    skill_app_label = f"{app_label}-skill"
    spec = {
        "schema_version": 1,
        "baseline_service": {
            "service_id": service_id,
            "app_label": app_label,
            "language": run_info["language"],
        },
        "skill_service": {
            "service_id": skill_service_id,
            "app_label": skill_app_label,
            "image": f"vibe/{skill_service_id}:dev",
            "target_dir": f"services_skill/{skill_service_id}",
        },
        "summary": summary,
        "responsibility": sanitize_architecture_text(body_intro) or summary,
        "behavior_contract_without_log_style": behavior,
        "language_stack": LANG_LABELS.get(run_info["language"], run_info["language"]),
        "endpoints": extract_endpoints(spec_text),
        "dependencies": deps_from_contract(k8s, spec_text),
        "state_contract": extract_state_contracts(service_dir, spec_text),
        "docker_contract": extract_docker_contract(service_dir, service_id, app_label, skill_service_id, skill_app_label),
        "kubernetes_contract": k8s,
        "faults": run_info["faults"],
        "smoke_path": run_info["smoke_path"],
        "exercise_contract": exercise_text.strip(),
        "generation_constraints": [
            "Generate a fresh implementation from this contract only; do not use or request baseline source code.",
            "Keep API paths, request fields, response fields, dependencies, and database schema compatible with the contract.",
            "Keep the service runnable on port 8080 in the existing kind/Chaos Mesh harness.",
            "Do not copy baseline log messages, prescribed error strings, or fault-handling behavior.",
            "Do not add OpenTelemetry, Prometheus, Jaeger, Grafana, or external telemetry infrastructure.",
        ],
    }
    return spec


def include_observability_skill(args: argparse.Namespace | None = None) -> bool:
    return getattr(args, "prompt_variant", "with-skill") == "with-skill"


def public_generation_spec(spec: dict[str, Any], include_skill: bool = True) -> dict[str, Any]:
    env = []
    for item in spec.get("kubernetes_contract", {}).get("env", []):
        name = item.get("name", "")
        value = item.get("value", "")
        if name == "APP_NAME":
            value = spec["skill_service"]["app_label"]
        env.append({"name": name, "value": value})
    constraints = [
        "Generate a fresh implementation from this contract only.",
        "Keep API paths, request fields, response fields, dependencies, and database schema compatible with the contract.",
        "Keep the service runnable on port 8080 with the listed environment variables and Docker build contract.",
        "Do not copy any pre-existing source code or log wording.",
        "Do not infer or implement hidden evaluation behavior from this contract.",
        "Do not add endpoints, dependencies, persistent state, background workers, or external telemetry infrastructure beyond the contract.",
        "Do not add OpenTelemetry, Prometheus, Jaeger, Grafana, or external telemetry infrastructure.",
        "Create or modify only files under src/; all other files are owned by the private runtime environment.",
    ]
    if include_skill:
        constraints.insert(
            5,
            "The observability skill may only affect application-level diagnostic messages inside the described service shape.",
        )
    return {
        "schema_version": 1,
        "service": {
            "service_id": spec["skill_service"]["service_id"],
            "app_label": spec["skill_service"]["app_label"],
            "image": spec["skill_service"]["image"],
            "target_dir": spec["skill_service"]["target_dir"],
            "port": 8080,
            "language": spec["baseline_service"]["language"],
            "language_stack": spec["language_stack"],
        },
        "responsibility": spec["responsibility"],
        "behavior_contract": spec["behavior_contract_without_log_style"],
        "endpoints": spec["endpoints"],
        "dependencies": spec["dependencies"],
        "state_contract": spec["state_contract"],
        "runtime_env": env,
        "docker_build_contract": spec["docker_contract"],
        "readiness_path": spec.get("kubernetes_contract", {}).get("readiness_path", "/healthz"),
        "generation_constraints": constraints,
    }


def observability_skill_section(include_skill: bool) -> str:
    if not include_skill:
        return ""
    return f"""
## Observability Engineering Skill

Apply this skill internally while generating the service. Do not output your plan.

{OBSERVABILITY_SKILL}
"""


def prompt_for(spec: dict[str, Any], include_skill: bool = True) -> str:
    public_spec = public_generation_spec(spec, include_skill=include_skill)
    return f"""# Generate {spec['skill_service']['service_id']}

You are generating a fresh microservice from a source-free service contract.
Use only the contract below. Do not inspect any prior implementation or hidden
test harness files.

## Target

- Directory: `{spec['skill_service']['target_dir']}`
- Service ID: `{spec['skill_service']['service_id']}`
- Kubernetes app label: `{spec['skill_service']['app_label']}`
- Image: `{spec['skill_service']['image']}`
- Language/stack: {spec['language_stack']}
- Port: 8080

## Invariants

- Keep the HTTP API paths and request/response field names compatible.
- Keep database table structure compatible.
- Keep dependency usage compatible: {', '.join(spec['dependencies']) or 'none'}.
- Keep the service runnable on port 8080 with the listed environment variables.
- Logs and internal implementation are free to differ from the baseline.

## Service Contract

```json
{json.dumps(public_spec, ensure_ascii=False, indent=2)}
```
{observability_skill_section(include_skill)}

## Output Contract

Create or update only files under `{spec['skill_service']['target_dir']}`.
Produce a complete runnable service implementation. Do not inspect or reference
`services/{spec['baseline_service']['service_id']}` or hidden experiment harness files.
"""


def extract(args: argparse.Namespace) -> None:
    SPECS_ROOT.mkdir(parents=True, exist_ok=True)
    PROMPTS_ROOT.mkdir(parents=True, exist_ok=True)
    specs = []
    for service_dir in service_dirs(args.limit, args.services):
        spec = extract_spec(service_dir)
        specs.append(spec)
        write_json(SPECS_ROOT / f"{spec['baseline_service']['service_id']}.json", spec)
        (PROMPTS_ROOT / f"{spec['skill_service']['service_id']}.md").write_text(
            prompt_for(spec, include_skill=include_observability_skill(args)),
            encoding="utf-8",
        )
    manifest = {
        "schema_version": 1,
        "prompt_variant": args.prompt_variant,
        "count": len(specs),
        "specs": [f"specs/{s['baseline_service']['service_id']}.json" for s in specs],
        "prompts": [f"prompts/{s['skill_service']['service_id']}.md" for s in specs],
    }
    write_json(MANIFEST_ROOT / "skill_observability_manifest.json", manifest)
    print(f"wrote {len(specs)} specs and prompts under {EXP_ROOT}")


def render_run_sh(spec: dict[str, Any]) -> str:
    smoke = spec.get("smoke_path", "/healthz")
    smoke_line = f'SMOKE_PATH="{smoke}"' if smoke else ""
    return f'''#!/usr/bin/env bash
# Auto-generated skill-experiment wrapper. Actual logic in _lib/run-common.sh.
HERE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
SERVICE_ID="{spec['skill_service']['service_id']}"
APP_LABEL="{spec['skill_service']['app_label']}"
LANG="{spec['baseline_service']['language']}"
{smoke_line}
source "$HERE/../../_lib/run-common.sh"
main_dispatch "$@"
'''


def rewrite_text_for_skill(text: str, spec: dict[str, Any]) -> str:
    old_id = spec["baseline_service"]["service_id"]
    old_app = spec["baseline_service"]["app_label"]
    new_id = spec["skill_service"]["service_id"]
    new_app = spec["skill_service"]["app_label"]
    placeholders = {
        "@@SKILL_IMAGE@@": f"vibe/{new_id}:dev",
        "@@SKILL_SERVICE_ID@@": new_id,
        "@@SKILL_APP_LABEL@@": new_app,
    }
    text = text.replace(f"vibe/{old_id}:dev", "@@SKILL_IMAGE@@")
    text = text.replace(old_id, "@@SKILL_SERVICE_ID@@")
    text = re.sub(rf"\b{re.escape(old_app)}\b", "@@SKILL_APP_LABEL@@", text)
    for placeholder, value in placeholders.items():
        text = text.replace(placeholder, value)
    return text


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def materialize(args: argparse.Namespace) -> None:
    specs = []
    if args.services:
        names = args.services
        for name in names:
            base = name.removesuffix("-skill")
            path = SPECS_ROOT / f"{base}.json"
            if not path.exists():
                raise SystemExit(f"missing spec {path}; run extract first")
            specs.append(json.loads(read_text(path)))
    else:
        paths = sorted(SPECS_ROOT.glob("*.json"))
        if args.limit is not None:
            paths = paths[: args.limit]
        specs = [json.loads(read_text(path)) for path in paths]

    total = len(specs)
    for index, spec in enumerate(specs, start=1):
        baseline_dir = SERVICES_ROOT / spec["baseline_service"]["service_id"]
        target_dir = ROOT / spec["skill_service"]["target_dir"]
        if index == 1 or index == total or index % 10 == 0:
            print(f"materialize [{index}/{total}] {spec['skill_service']['service_id']}", flush=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        run_sh = target_dir / "run.sh"
        run_sh.write_text(render_run_sh(spec), encoding="utf-8")
        run_sh.chmod(run_sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        k8s_src = baseline_dir / "k8s" / "deployment.yaml"
        k8s_dst = target_dir / "k8s" / "deployment.yaml"
        if k8s_src.exists():
            k8s_dst.parent.mkdir(parents=True, exist_ok=True)
            k8s_dst.write_text(rewrite_text_for_skill(read_text(k8s_src), spec), encoding="utf-8")

        faults_dst = target_dir / "faults"
        faults_dst.mkdir(exist_ok=True)
        for fault_src in sorted((baseline_dir / "faults").glob("*.yaml")):
            (faults_dst / fault_src.name).write_text(rewrite_text_for_skill(read_text(fault_src), spec), encoding="utf-8")

        docker_src = baseline_dir / "Dockerfile"
        if docker_src.exists():
            docker_text = sanitize_dockerfile(
                read_text(docker_src),
                spec["baseline_service"]["service_id"],
                spec["baseline_service"]["app_label"],
                spec["skill_service"]["service_id"],
                spec["skill_service"]["app_label"],
            )
            (target_dir / "Dockerfile").write_text(docker_text, encoding="utf-8")

        exercise_src = baseline_dir / "exercise.sh"
        if exercise_src.exists():
            copy_if_exists(exercise_src, target_dir / "exercise.sh")
            exercise_dst = target_dir / "exercise.sh"
            exercise_dst.chmod(exercise_dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        (target_dir / "PROMPT.md").write_text(
            prompt_for(spec, include_skill=include_observability_skill(args)),
            encoding="utf-8",
        )
        (target_dir / "CONTRACT.json").write_text(
            json.dumps(public_generation_spec(spec, include_skill=include_observability_skill(args)), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        src_dir = target_dir / "src"
        src_dir.mkdir(exist_ok=True)
        readme = target_dir / "README.md"
        readme.write_text(
            f"# {spec['skill_service']['service_id']}\n\n"
            "Skill-regeneration skeleton. Fill this directory with a fresh implementation using PROMPT.md.\n"
            "The harness files are compatible with the baseline fault-injection runner.\n",
            encoding="utf-8",
        )
    print(f"materialized {len(specs)} skill service skeletons under {SKILL_SERVICES_ROOT}")


def load_specs_for_args(args: argparse.Namespace) -> list[dict[str, Any]]:
    specs = []
    if args.services:
        for name in args.services:
            base = name.removesuffix("-skill")
            path = SPECS_ROOT / f"{base}.json"
            if not path.exists():
                raise SystemExit(f"missing spec {path}; run extract first")
            specs.append(json.loads(read_text(path)))
    else:
        paths = sorted(SPECS_ROOT.glob("*.json"))
        if args.limit is not None:
            paths = paths[: args.limit]
        specs = [json.loads(read_text(path)) for path in paths]
    return specs


def prepare_workspace(args: argparse.Namespace) -> None:
    specs = load_specs_for_args(args)
    ISOLATED_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_items = []
    for spec in specs:
        service_id = spec["skill_service"]["service_id"]
        workspace = ISOLATED_ROOT / service_id
        if workspace.exists():
            shutil.rmtree(workspace)
        (workspace / "src").mkdir(parents=True)

        public_spec = public_generation_spec(spec, include_skill=include_observability_skill(args))
        (workspace / "CONTRACT.json").write_text(json.dumps(public_spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (workspace / "PROMPT.md").write_text(
            isolated_prompt_for(spec, include_skill=include_observability_skill(args)),
            encoding="utf-8",
        )
        (workspace / "DOCKER_CONTRACT.md").write_text(docker_contract_markdown(spec), encoding="utf-8")
        (workspace / "README.md").write_text(
            f"# {service_id} isolated generation workspace\n\n"
            "Only public service-contract files are present here. Write generated implementation files under `src/`.\n"
            "Use `DOCKER_CONTRACT.md` to understand the private harness Docker build expectation.\n",
            encoding="utf-8",
        )
        manifest_items.append({
            "service_id": service_id,
            "baseline_service_id": spec["baseline_service"]["service_id"],
            "workspace": str(workspace.relative_to(ROOT)),
            "prompt": str((workspace / "PROMPT.md").relative_to(ROOT)),
            "import_to": spec["skill_service"]["target_dir"] + "/src",
        })
    write_json(MANIFEST_ROOT / "isolated_workspaces.json", {"count": len(manifest_items), "items": manifest_items})
    print(f"prepared {len(specs)} isolated workspaces under {ISOLATED_ROOT}")


def isolated_prompt_for(spec: dict[str, Any], include_skill: bool = True) -> str:
    service_id = spec["skill_service"]["service_id"]
    return f"""# Generate {service_id}

You are in an isolated generation workspace. The only service information you may
use is `CONTRACT.json` in this directory and the instructions in this prompt.

Write a fresh implementation under `src/` only. Do not create files outside
`src/`. Do not inspect or request any external repository path.

You MUST use file-editing tools to create the implementation files under `src/`.
Do not answer with code fences instead of writing files. A final text summary is
not sufficient unless the files have been created in `src/`.

The service must be runnable by the existing experiment harness after `src/` is
copied back to the private benchmark directory. Keep all API paths,
request/response fields, dependency usage, database/state contract, and port 8080
compatible with `CONTRACT.json`. Use `DOCKER_CONTRACT.md` and the
`docker_build_contract` section of `CONTRACT.json` to choose the correct files
inside `src/` so the private Docker build succeeds after import.

## Public Contract

```json
{json.dumps(public_generation_spec(spec, include_skill=include_skill), ensure_ascii=False, indent=2)}
```
{observability_skill_section(include_skill)}

## Output Contract

Create source/build files only under `src/`. Do not write outside `src/`.
Do not create files outside `src/`.
Your final response should be a short summary of files created; the actual source
code must be present on disk under `src/`.
"""


def docker_contract_markdown(spec: dict[str, Any]) -> str:
    contract = spec["docker_contract"]
    return f"""# Docker Build Contract

The generation agent may create or modify only files under `src/`.

After generation, the private experiment pipeline will copy `src/` back into
`{contract['build_context_after_import']}` and run:

```bash
{contract['validation_command_after_import']}
```

The Dockerfile below is shown only so generated `src/` files match the expected
layout. Do not create or modify a Dockerfile.

```dockerfile
{contract['dockerfile_used_by_private_harness']}```
"""


def import_generated(args: argparse.Namespace) -> None:
    specs = load_specs_for_args(args)
    for spec in specs:
        service_id = spec["skill_service"]["service_id"]
        workspace_src = ISOLATED_ROOT / service_id / "src"
        target_src = ROOT / spec["skill_service"]["target_dir"] / "src"
        if not workspace_src.exists():
            raise SystemExit(f"missing generated src {workspace_src}; run prepare-workspace and SDK generation first")
        if target_src.exists():
            shutil.rmtree(target_src)
        shutil.copytree(workspace_src, target_src)
    print(f"imported generated src for {len(specs)} services into {SKILL_SERVICES_ROOT}")


def strip_faults(args: argparse.Namespace) -> None:
    specs = load_specs_for_args(args)
    removed = []
    for spec in specs:
        target_dir = ROOT / spec["skill_service"]["target_dir"]
        run_sh = target_dir / "run.sh"
        if run_sh.exists():
            run_sh.write_text(render_run_sh(spec), encoding="utf-8")
            run_sh.chmod(run_sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        faults_dir = target_dir / "faults"
        if faults_dir.exists():
            shutil.rmtree(faults_dir)
            removed.append(str(faults_dir.relative_to(ROOT)))
    write_json(
        MANIFEST_ROOT / "services_skill_faults_stripped.json",
        {"count": len(removed), "removed": removed},
    )
    print(f"stripped faults from {len(removed)} services_skill entries")


def restore_faults(args: argparse.Namespace) -> None:
    specs = load_specs_for_args(args)
    restored = []
    for spec in specs:
        baseline_dir = SERVICES_ROOT / spec["baseline_service"]["service_id"]
        target_dir = ROOT / spec["skill_service"]["target_dir"]
        run_sh = target_dir / "run.sh"
        if run_sh.exists():
            run_sh.write_text(render_run_sh(spec), encoding="utf-8")
            run_sh.chmod(run_sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        faults_src = baseline_dir / "faults"
        faults_dst = target_dir / "faults"
        if faults_dst.exists():
            shutil.rmtree(faults_dst)
        faults_dst.mkdir(parents=True, exist_ok=True)
        for fault_src in sorted(faults_src.glob("*.yaml")):
            (faults_dst / fault_src.name).write_text(
                rewrite_text_for_skill(read_text(fault_src), spec),
                encoding="utf-8",
            )
        restored.append(str(faults_dst.relative_to(ROOT)))
    write_json(
        MANIFEST_ROOT / "services_skill_faults_restored.json",
        {"count": len(restored), "restored": restored},
    )
    print(f"restored faults into {len(restored)} services_skill entries")


def show_prompt_variants(args: argparse.Namespace) -> None:
    specs = load_specs_for_args(args)
    for spec in specs:
        service_id = spec["skill_service"]["service_id"]
        with_skill = prompt_for(spec, include_skill=True).splitlines()
        no_skill = prompt_for(spec, include_skill=False).splitlines()
        print(f"===== {service_id} with-skill vs no-skill prompt diff =====")
        for line in difflib.unified_diff(
            no_skill,
            with_skill,
            fromfile=f"{service_id}.no-skill.md",
            tofile=f"{service_id}.with-skill.md",
            lineterm="",
        ):
            print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_extract = sub.add_parser("extract", help="write source-free specs and Copilot prompts")
    p_extract.add_argument("--limit", type=int)
    p_extract.add_argument("--services", nargs="*")
    p_extract.add_argument("--prompt-variant", choices=["with-skill", "no-skill"], default="with-skill")
    p_extract.set_defaults(func=extract)

    p_materialize = sub.add_parser("materialize", help="create services_skill skeletons from specs")
    p_materialize.add_argument("--limit", type=int)
    p_materialize.add_argument("--services", nargs="*")
    p_materialize.add_argument("--prompt-variant", choices=["with-skill", "no-skill"], default="with-skill")
    p_materialize.set_defaults(func=materialize)

    p_prepare = sub.add_parser("prepare-workspace", help="create isolated SDK generation workspaces")
    p_prepare.add_argument("--limit", type=int)
    p_prepare.add_argument("--services", nargs="*")
    p_prepare.add_argument("--prompt-variant", choices=["with-skill", "no-skill"], default="with-skill")
    p_prepare.set_defaults(func=prepare_workspace)

    p_import = sub.add_parser("import-generated", help="copy isolated workspace src/ back into services_skill")
    p_import.add_argument("--limit", type=int)
    p_import.add_argument("--services", nargs="*")
    p_import.set_defaults(func=import_generated)

    p_strip = sub.add_parser("strip-faults", help="remove private fault manifests from services_skill before SDK generation")
    p_strip.add_argument("--limit", type=int)
    p_strip.add_argument("--services", nargs="*")
    p_strip.set_defaults(func=strip_faults)

    p_restore = sub.add_parser("restore-faults", help="copy original service fault manifests back into services_skill for evaluation")
    p_restore.add_argument("--limit", type=int)
    p_restore.add_argument("--services", nargs="*")
    p_restore.set_defaults(func=restore_faults)

    p_diff = sub.add_parser("diff-prompts", help="show with-skill vs no-skill prompt diff")
    p_diff.add_argument("--limit", type=int)
    p_diff.add_argument("--services", nargs="*")
    p_diff.set_defaults(func=show_prompt_variants)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()