#!/usr/bin/env python3
"""Run obs-real pilot for instances matching a prefix.

This is a thin wrapper over tools.pilot.run_one so we can run only one repo
slice (for example `otel-demo__`) with high concurrency.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

# Allow direct execution: `python tools/pilot_prefix.py`
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from tools import llm_client
from tools.pilot import INSTANCES_DIR, RESULTS_DIR, run_one


def _list_prefixed_instances(prefix: str) -> list[str]:
    ids: list[str] = []
    for p in sorted(INSTANCES_DIR.glob(f"{prefix}*.json")):
        if p.name.startswith("_"):
            continue
        try:
            doc = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if doc.get("_runnable") is False:
            continue
        ids.append(p.stem)
    return ids


def _build_summary_from_disk(run_id: str, model: str) -> list[dict]:
    run_dir = RESULTS_DIR / run_id
    rows: list[dict] = []
    for result_path in sorted(run_dir.glob(f"*/*/{model}/result.json")):
        try:
            data = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        score_block = data.get("score") or {}
        anchor_block = data.get("anchor_score") or {}
        row: dict = {
            "instance": data.get("instance_id", ""),
            "prompt": data.get("prompt_level", ""),
            "model": data.get("model", model),
            "backend": data.get("backend", "api"),
            "agent": data.get("agent"),
            "agentic": data.get("agentic", False),
            "agent_workspace": data.get("agent_workspace"),
            **score_block,
            "elapsed_s": data.get("elapsed_s", 0.0),
        }
        if anchor_block:
            row.update(
                {
                    "pos_precision": anchor_block.get("precision"),
                    "pos_recall": anchor_block.get("recall"),
                    "pos_f1": anchor_block.get("f1"),
                    "key_precision": anchor_block.get("key_precision"),
                    "key_recall": anchor_block.get("key_recall"),
                    "key_f1": anchor_block.get("key_f1"),
                    "key_n_comparable_buckets": anchor_block.get("key_n_comparable_buckets"),
                    "key_bag_precision": anchor_block.get("key_bag_precision"),
                    "key_bag_recall": anchor_block.get("key_bag_recall"),
                    "key_bag_f1": anchor_block.get("key_bag_f1"),
                    "key_bag_n_comparable_buckets": anchor_block.get(
                        "key_bag_n_comparable_buckets"
                    ),
                    "n_anchors_gt": anchor_block.get("n_anchors_gt"),
                    "n_anchors_llm": anchor_block.get("n_anchors_llm"),
                    "n_anchors_aligned": anchor_block.get("n_anchors_aligned"),
                }
            )
        rows.append(row)
    rows.sort(key=lambda d: (d["instance"], d["prompt"]))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Run pilot for instances matching a prefix.")
    ap.add_argument("--prefix", required=True, help="Instance id prefix, e.g. otel-demo__")
    ap.add_argument(
        "--prompts",
        default="p_blind,p1_obs_hinted,p_fewshot",
        help="Comma-separated prompt levels.",
    )
    ap.add_argument("--model", default=llm_client.DEFAULT_MODEL, help="Model id or alias.")
    ap.add_argument(
        "--backend",
        default=llm_client.DEFAULT_BACKEND,
        help="LLM backend: api (Azure OpenAI helper) or agent (Copilot SDK).",
    )
    ap.add_argument(
        "--agent",
        help="Optional Copilot custom agent name (used only when --backend agent).",
    )
    ap.add_argument(
        "--agentic",
        action="store_true",
        help="Enable agentic mode: allow repo-aware planning/search before final answer (agent backend only).",
    )
    ap.add_argument(
        "--agent-workspace",
        help=(
            "Override working directory exposed to Copilot agent tools "
            "(agent backend only). By default, each instance uses its own "
            "source repo path from instances/function/*.json (repo.local_path)."
        ),
    )
    ap.add_argument("--run-id", required=True, help="results/<run-id>/")
    ap.add_argument("--workers", type=int, default=128, help="Parallel workers.")
    ap.add_argument("--skip-existing", action="store_true", help="Skip existing result cells.")
    ap.add_argument("--dry-run", action="store_true", help="Skip LLM calls.")
    args = ap.parse_args()

    if args.workers < 1:
        ap.error("--workers must be >= 1")
    try:
        backend = llm_client.resolve_backend(args.backend)
    except ValueError as e:
        ap.error(str(e))

    if backend != "agent" and (args.agent or args.agentic or args.agent_workspace):
        print(
            "[pilot-prefix] warning: --agent/--agentic/--agent-workspace are ignored when backend != agent"
        )

    prompts = [p.strip() for p in args.prompts.split(",") if p.strip()]
    ids = _list_prefixed_instances(args.prefix)
    if not ids:
        raise SystemExit(f"No runnable instances found for prefix={args.prefix!r} under {INSTANCES_DIR}")

    work = [(inst, pr) for inst in ids for pr in prompts]
    if args.skip_existing:
        kept: list[tuple[str, str]] = []
        skipped = 0
        for inst, pr in work:
            rp = RESULTS_DIR / args.run_id / inst / pr / args.model / "result.json"
            if rp.exists():
                skipped += 1
                continue
            kept.append((inst, pr))
        work = kept
        print(f"[pilot-prefix] skip-existing: skipped={skipped}")

    total = len(work)
    print(
        f"[pilot-prefix] prefix={args.prefix} instances={len(ids)} prompts={len(prompts)} "
        f"cells={total} workers={args.workers} model={args.model} "
        f"backend={backend} run_id={args.run_id} agentic={args.agentic}"
    )

    if total == 0:
        rows = _build_summary_from_disk(args.run_id, args.model)
        out = RESULTS_DIR / args.run_id / "summary.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, indent=2) + "\n")
        print(f"[pilot-prefix] no new cells; refreshed summary -> {out}")
        return 0

    if not args.dry_run:
        t0 = time.time()
        if backend == "api":
            print("[pilot-prefix] prewarming API client...")
        else:
            print("[pilot-prefix] prewarming Agent backend...")
        llm_client.prewarm(backend=backend)
        print(f"[pilot-prefix] prewarm done in {time.time() - t0:.1f}s")

    done = 0
    failed = 0
    t_start = time.time()

    def _run_cell(inst: str, prompt: str):
        try:
            r = run_one(
                inst,
                prompt,
                args.model,
                backend=backend,
                agent=args.agent,
                agentic=args.agentic,
                agent_workspace=args.agent_workspace,
                dry_run=args.dry_run,
                run_id=args.run_id,
            )
            return inst, prompt, r, None
        except BaseException:
            return inst, prompt, None, traceback.format_exc()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        fut_map = {ex.submit(_run_cell, inst, pr): (inst, pr) for inst, pr in work}
        for fut in as_completed(fut_map):
            done += 1
            inst, pr, r, err = fut.result()
            if err is not None:
                failed += 1
                print(f"[{done}/{total}] FAIL {inst} | {pr}\n{err}")
            else:
                if r is None:
                    print(f"[{done}/{total}] DRY-RUN {inst} | {pr}")
                else:
                    pos_f1 = r.anchor_score.get("f1") if r.anchor_score else None
                    key_bag_f1 = r.anchor_score.get("key_bag_f1") if r.anchor_score else None
                    print(
                        f"[{done}/{total}] DONE {inst} | {pr} "
                        f"n_gt={r.score.get('n_gt')} n_llm={r.score.get('n_llm')} "
                        f"OldF1={r.score.get('f1')} PosF1={pos_f1} KeyBagF1={key_bag_f1} "
                        f"({r.elapsed_s}s)"
                    )

    rows = _build_summary_from_disk(args.run_id, args.model)
    out = RESULTS_DIR / args.run_id / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2) + "\n")

    elapsed = time.time() - t_start
    print(
        f"[pilot-prefix] completed: done={done} failed={failed} elapsed={elapsed:.1f}s "
        f"summary_rows={len(rows)} -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
