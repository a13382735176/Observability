#!/usr/bin/env python3
"""
vibe_coding judge — log-window fault detector.

Usage:
    judge.py <fault_run_dir> [--oracle path] [--mode MODE]
    judge.py <run_dir> [--oracle path] [--mode MODE]  # batch: all faults under it

Modes:
    current        Existing behavior. Uses generic + per-fault matchers.
    strict         Application-oriented. Drops [access] lines and excludes
                   generic-http-5xx matcher.
    fault-specific Strongest anti-inflation mode. Drops [access] lines and
                   uses ONLY per-fault matchers.

Each <fault_run_dir> must contain a meta.json (written by run.sh::inject).
Writes verdict.json next to it. For a parent run_dir, writes summary.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:
    print("[judge] error: PyYAML required. pip install pyyaml", file=sys.stderr)
    sys.exit(2)


HERE = Path(__file__).resolve().parent
DEFAULT_ORACLE = HERE / "oracle.yaml"


@dataclass
class Meta:
    service: str
    fault_id: str
    namespace: str
    app_label: str
    t_start: str
    t_end: str
    duration_s: int
    buffer_s: int

    @classmethod
    def load(cls, p: Path) -> "Meta":
        with p.open() as f:
            d = json.load(f)
        return cls(
            service=d["service"],
            fault_id=d["fault_id"],
            namespace=d["namespace"],
            app_label=d["app_label"],
            t_start=d["t_start"],
            t_end=d["t_end"],
            duration_s=int(d["duration_s"]),
            buffer_s=int(d["buffer_s"]),
        )


def kubectl(*args: str, check: bool = True) -> str:
    cp = subprocess.run(["kubectl", *args], capture_output=True, text=True)
    if check and cp.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)} failed: {cp.stderr}")
    return cp.stdout


def parse_iso(s: str) -> datetime:
    # accept both "...Z" and "...+00:00"
    s = s.replace("Z", "+00:00")
    # kubectl --timestamps uses nanosecond precision (9-digit fraction).
    # Python's fromisoformat only supports up to microseconds (6 digits).
    # Truncate the fractional part to 6 digits before parsing.
    if "." in s:
        dot = s.index(".")
        plus = s.index("+", dot)
        frac = s[dot + 1 : plus]
        s = s[:dot + 1] + frac[:6].ljust(6, "0") + s[plus:]
    return datetime.fromisoformat(s)


def get_pod_logs(ns: str, app: str, since: str) -> str:
    # --all-containers so multi-container pods are captured.
    # --prefix annotates each line with pod/container, useful for debug.
    # --timestamps puts the k8s-side RFC3339 timestamp at the start of each line.
    out = subprocess.run(
        [
            "kubectl", "-n", ns,
            "logs", "-l", f"app={app}",
            "--all-containers=true",
            "--timestamps=true",
            "--prefix=true",
            f"--since-time={since}",
            "--tail=-1",
        ],
        capture_output=True, text=True,
    )
    # Don't raise on non-zero — sometimes the pod is mid-restart.
    return out.stdout + out.stderr


def get_pod_restart_counts(ns: str, app: str) -> dict[str, int]:
    raw = kubectl("-n", ns, "get", "pods", "-l", f"app={app}", "-o", "json", check=False)
    if not raw.strip():
        return {}
    j = json.loads(raw)
    result: dict[str, int] = {}
    for item in j.get("items", []):
        name = item["metadata"]["name"]
        total = 0
        for cs in item.get("status", {}).get("containerStatuses", []):
            total += int(cs.get("restartCount", 0))
        result[name] = total
    return result


def lines_in_window(raw_logs: str, t_start: datetime, t_end: datetime) -> list[str]:
    """Filter `kubectl logs --timestamps` output to lines whose own timestamp is in [t_start, t_end].

    kubectl --prefix prepends `[pod/<name> <container>]` then ts. With --timestamps,
    the first whitespace-separated token *after* the prefix is the RFC3339 ts.
    """
    out = []
    for line in raw_logs.splitlines():
        # Skip empty
        if not line.strip():
            continue
        # Strip optional `[pod/foo container]` prefix
        body = line
        if body.startswith("[pod/"):
            close = body.find("]")
            if close > 0:
                body = body[close + 1 :].lstrip()
        # First token should be the timestamp
        parts = body.split(maxsplit=1)
        if not parts:
            continue
        ts_tok = parts[0]
        try:
            ts = parse_iso(ts_tok)
        except ValueError:
            # Some lines (esp. stderr) may not have timestamps if kubectl gave up;
            # keep them only if we have NO ts info at all — safer to include.
            out.append(line)
            continue
        if t_start <= ts <= t_end:
            out.append(line)
    return out


def apply_matchers(
    lines: list[str], matchers: list[dict[str, str]], max_samples: int = 3
) -> list[dict[str, Any]]:
    results = []
    for m in matchers:
        rx = re.compile(m["regex"])
        hits = 0
        samples: list[str] = []
        for line in lines:
            if rx.search(line):
                hits += 1
                if len(samples) < max_samples:
                    samples.append(line[:300])
        results.append({"name": m["name"], "hits": hits, "samples": samples})
    return results


def build_noise_filter(oracle: dict[str, Any]):
    """Compile framework_noise patterns from oracle into a single callable."""
    patterns = oracle.get("framework_noise", [])
    rxs = [re.compile(p) for p in patterns]

    def is_noise(line: str) -> bool:
        return any(rx.search(line) for rx in rxs)

    return is_noise


def select_matchers(oracle: dict[str, Any], fault_id: str, mode: str) -> list[dict[str, str]]:
    fault_matchers = list(oracle.get("faults", {}).get(fault_id, []))
    generic = list(oracle.get("generic", []))

    if mode == "current":
        return generic + fault_matchers
    if mode == "strict":
        generic = [m for m in generic if m.get("name") != "generic-http-5xx"]
        return generic + fault_matchers
    if mode == "fault-specific":
        return fault_matchers
    raise ValueError(f"unknown mode: {mode}")


def maybe_strip_access_lines(lines: list[str], mode: str) -> tuple[list[str], int]:
    if mode not in {"strict", "fault-specific"}:
        return lines, 0
    kept = [line for line in lines if not line.lstrip().startswith("[access] ")]
    return kept, len(lines) - len(kept)


def judge_one(fault_dir: Path, oracle: dict[str, Any], mode: str, offline: bool = False) -> dict[str, Any]:
    meta_p = fault_dir / "meta.json"
    if not meta_p.exists():
        raise FileNotFoundError(f"missing meta.json in {fault_dir}")
    meta = Meta.load(meta_p)

    t_start = parse_iso(meta.t_start)
    t_end = parse_iso(meta.t_end)

    # 1. Pull logs since t_start.
    # Prefer a pre-saved snapshot (written by run.sh before any pod restart)
    # so logs from a pod that was later replaced are not lost.
    snapshot_p = fault_dir / "logs_snapshot.txt"
    if snapshot_p.exists() and snapshot_p.stat().st_size > 0:
        raw = snapshot_p.read_text()
    else:
        raw = get_pod_logs(meta.namespace, meta.app_label, meta.t_start)
    (fault_dir / "logs.txt").write_text(raw)

    # 2. Filter to [t_start, t_end].
    win_lines = lines_in_window(raw, t_start, t_end)
    (fault_dir / "logs.window.txt").write_text("\n".join(win_lines))

    # 2.5 Strip framework/library log lines so that caught=True reflects
    #     application-level observability only (not automatic library output).
    is_noise = build_noise_filter(oracle)
    app_lines = [l for l in win_lines if not is_noise(l)]
    n_noise_removed = len(win_lines) - len(app_lines)

    # 2.6 Optional strict filtering: remove synthetic access rows used for load probing.
    app_lines, n_access_removed = maybe_strip_access_lines(app_lines, mode)

    # 3. Apply matchers based on scoring mode.
    matchers = select_matchers(oracle, meta.fault_id, mode)
    matcher_results = apply_matchers(app_lines, matchers)
    any_hit = any(r["hits"] > 0 for r in matcher_results)

    # 4. F01 also checked via restartCount (read from pre-recorded baseline if present).
    restart_evidence = None
    restart_counts = {} if offline else get_pod_restart_counts(meta.namespace, meta.app_label)
    if meta.fault_id == "F01-pod-kill" and not offline:
        # Compare to baseline captured at inject time, if present.
        baseline_p = fault_dir / "pod_restarts_baseline.json"
        if baseline_p.exists():
            base = json.loads(baseline_p.read_text())
            # Any pod present in both with higher count, OR any new pod, counts.
            new_pods = set(restart_counts) - set(base)
            higher = {
                k: (base.get(k, 0), restart_counts[k])
                for k in restart_counts
                if k in base and restart_counts[k] > base[k]
            }
            if new_pods or higher:
                restart_evidence = {"new_pods": list(new_pods), "increased": higher}
        else:
            # No baseline — any non-zero restart counts as evidence.
            nz = {k: v for k, v in restart_counts.items() if v > 0}
            if nz:
                restart_evidence = {"any_restart_count_nonzero": nz}

    caught = any_hit or restart_evidence is not None

    verdict = {
        "service": meta.service,
        "fault_id": meta.fault_id,
        "judge_mode": mode,
        "caught": caught,
        "verdict_reason": (
            "matcher" if any_hit else "pod_restart" if restart_evidence else "no_signal"
        ),
        "matchers": matcher_results,
        "n_matchers_used": len(matchers),
        "n_log_lines_total": len(raw.splitlines()),
        "n_log_lines_in_window": len(win_lines),
        "n_framework_lines_removed": n_noise_removed,
        "n_access_lines_removed": n_access_removed,
        "n_app_lines_in_window": len(app_lines),
        "pod_restart_counts_now": restart_counts,
        "pod_restart_evidence": restart_evidence,
        "window": {"t_start": meta.t_start, "t_end": meta.t_end},
    }
    (fault_dir / "verdict.json").write_text(json.dumps(verdict, indent=2))
    return verdict


def judge_batch(run_dir: Path, oracle: dict[str, Any], mode: str, offline: bool = False) -> dict[str, Any]:
    fault_dirs = sorted(
        p for p in run_dir.iterdir() if p.is_dir() and (p / "meta.json").exists()
    )
    if not fault_dirs:
        raise RuntimeError(f"no fault dirs (with meta.json) under {run_dir}")
    results = []
    for fd in fault_dirs:
        try:
            v = judge_one(fd, oracle, mode, offline=offline)
        except Exception as e:
            v = {"fault_id": fd.name, "error": str(e), "caught": False}
        results.append(v)
    summary = {
        "run_dir": str(run_dir),
        "judge_mode": mode,
        "n_faults": len(results),
        "n_caught": sum(1 for v in results if v.get("caught")),
        "results": results,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", help="fault dir (has meta.json) OR parent run dir")
    ap.add_argument("--oracle", default=str(DEFAULT_ORACLE))
    ap.add_argument(
        "--mode",
        choices=["current", "strict", "fault-specific"],
        default=os.environ.get("JUDGE_MODE", "current"),
        help="Scoring mode (default: env JUDGE_MODE or 'current').",
    )
    ap.add_argument(
        "--offline",
        action="store_true",
        help="Use saved run artifacts only; do not query kubectl for current pod state.",
    )
    args = ap.parse_args()

    with open(args.oracle) as f:
        oracle = yaml.safe_load(f)

    p = Path(args.run_dir).resolve()
    if not p.is_dir():
        print(f"error: not a directory: {p}", file=sys.stderr)
        return 2

    if (p / "meta.json").exists():
        v = judge_one(p, oracle, args.mode, offline=args.offline)
        print(json.dumps(v, indent=2))
        return 0 if v["caught"] else 1
    else:
        s = judge_batch(p, oracle, args.mode, offline=args.offline)
        print(f"caught {s['n_caught']}/{s['n_faults']}")
        for v in s["results"]:
            mark = "OK " if v.get("caught") else "MISS"
            print(f"  [{mark}] {v.get('fault_id'):24s} reason={v.get('verdict_reason', '?')}")
        return 0 if s["n_caught"] == s["n_faults"] else 1


if __name__ == "__main__":
    sys.exit(main())
