#!/usr/bin/env python3
import argparse
import csv
import re
from pathlib import Path

DEFAULT_CASES = [
    "payment_failure",
    "recommendation_cache",
    "ad_failure",
    "kafka_queue",
    "payment_unreachable",
    "cart_failure",
    "failed_readiness_probe",
    "llm_inaccurate",
    "llm_rate_limit",
    "product_catalog_failure",
    "loadgen_flood",
]

STRICT_LLM_PATTERNS = {
    "recommendation_cache": re.compile(r"recommendation\s+\|.*cache_failure_enabled:True", re.I),
    "llm_inaccurate": re.compile(r"llm\s+\|.*llm_inaccurate_response:\s*True", re.I),
    "failed_readiness_probe": re.compile(r"cart\s+\|.*Completed health check.*status:\s*NotServing", re.I),
    "llm_rate_limit": re.compile(r"product-reviews\s+\|.*AI assistant rate-limit probe failed", re.I),
}


def read_rows(summary_paths):
    rows = []
    for summary_path in summary_paths:
        with open(summary_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                row["summary_path"] = str(summary_path)
                rows.append(row)
    return rows


def latest_by_case_variant(rows):
    latest = {}
    for row in rows:
        case_name = row["case"]
        variant = row["variant"]
        latest[(case_name, variant)] = row
    return latest


def log_matches(row, pattern):
    log_path = Path(row.get("notes", ""))
    if not log_path.is_file():
        return False
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(pattern.search(text))


def pct(numerator, denominator):
    return 100.0 * numerator / denominator if denominator else 0.0


def main():
    parser = argparse.ArgumentParser(
        description="Summarize OTel fault-log experiments into paper observability rates."
    )
    parser.add_argument("summary", nargs="+", type=Path, help="summary.tsv files to combine")
    parser.add_argument("--cases", nargs="*", default=DEFAULT_CASES, help="case denominator/order")
    args = parser.parse_args()

    rows = latest_by_case_variant(read_rows(args.summary))
    cases = args.cases

    original_success = []
    strict_llm_success = []

    print("case\toriginal_system\tllm_strict")
    for case_name in cases:
        original_row = rows.get((case_name, "original"))
        llm_row = rows.get((case_name, "llm"))

        original_ok = bool(original_row and original_row.get("status") == "evidence_found")
        strict_pattern = STRICT_LLM_PATTERNS.get(case_name)
        strict_llm_ok = bool(llm_row and strict_pattern and log_matches(llm_row, strict_pattern))

        if original_ok:
            original_success.append(case_name)
        if strict_llm_ok:
            strict_llm_success.append(case_name)

        print(
            f"{case_name}\t"
            f"{'yes' if original_ok else 'no'}\t"
            f"{'yes' if strict_llm_ok else 'no'}"
        )

    denominator = len(cases)
    print()
    print(
        f"Original repo system-level observability: "
        f"{len(original_success)}/{denominator} = {pct(len(original_success), denominator):.1f}%"
    )
    print(
        f"LLM snippet-attributable observability: "
        f"{len(strict_llm_success)}/{denominator} = {pct(len(strict_llm_success), denominator):.1f}%"
    )


if __name__ == "__main__":
    main()