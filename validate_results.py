"""
Validate extracted answer key JSON files at a high level without manual review.

This tool scans all JSON files in a directory (default: "answer_keys") and
reports consistency and anomaly signals across years and grade groups.

It is complementary to the extractor's per-page debug overlays. Use this when
you want a quick confidence pass across the entire dataset.

Examples
--------
Run with the project environment managed by uv:

    uv run python validate_results.py

    uv run python validate_results.py answer_keys

Outputs
-------
Summaries for counts per grade group across years, script-generated warnings
embedded in the files, and a compact anomaly list for quick triage.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _fmt_list(xs: Iterable[Any], limit: int = 6) -> str:
    vals = list(xs)
    head = ", ".join(str(x) for x in vals[:limit])
    if len(vals) > limit:
        return f"[{head}, ...]"
    return f"[{head}]"


def validate_dir(keys_dir: Path) -> int:
    """
    Validate a directory of extracted answer key JSON files.

    Parameters
    ----------
    keys_dir : Path
        Directory that contains per-year JSON files produced by the extractor.

    Returns
    -------
    int
        Exit status code. Zero when the directory is readable and at least one
        JSON is processed; non-zero on structural errors or empty sets.
    """
    if not keys_dir.exists() or not keys_dir.is_dir():
        print(f"Error: directory not found: {keys_dir}")
        return 2

    files: List[Path] = sorted([p for p in keys_dir.glob("*.json") if p.is_file()])
    if not files:
        print(f"Error: no JSON files found in {keys_dir}")
        return 2

    counts_by_group: Dict[str, Dict[int, int]] = defaultdict(dict)
    missing_by_group_year: Dict[Tuple[str, int], List[str]] = defaultdict(list)
    warnings_by_year: Dict[int, List[str]] = defaultdict(list)
    validation_warnings_by_year: Dict[int, List[str]] = defaultdict(list)
    schemes_by_group: Dict[str, Dict[int, str]] = defaultdict(dict)
    processed = 0

    for path in files:
        try:
            data = _load_json(path)
        except Exception as e:
            print(f"Error: failed to read {path.name}: {e}")
            continue

        year_raw = data.get("year")
        if not isinstance(year_raw, int):
            print(f"Warning: {path.name} missing or invalid 'year'")
            continue
        year = int(year_raw)
        processed += 1

        if isinstance(data.get("warnings"), list):
            warnings_by_year[year].extend(list(data["warnings"]))
        if isinstance(data.get("validation_warnings"), list):
            validation_warnings_by_year[year].extend(list(data["validation_warnings"]))

        gg = data.get("grade_groups") or {}
        if not isinstance(gg, dict):
            print(f"Warning: {path.name} has non-dict 'grade_groups'")
            continue

        for group, payload in gg.items():
            if not isinstance(payload, dict):
                continue
            counts = int(payload.get("counts", 0))
            counts_by_group[group][year] = counts

            scheme = payload.get("scheme")
            if isinstance(scheme, str):
                schemes_by_group[group][year] = scheme

            missing = payload.get("missing_answers") or []
            if isinstance(missing, list):
                missing_by_group_year[(group, year)].extend([str(x) for x in missing])

    print(f"--- Validation Summary for {keys_dir.resolve()} ---\n")

    print("1) Counts per grade group across years:")
    for group in sorted(counts_by_group.keys()):
        year_counts = counts_by_group[group]
        uniq_counts = sorted(set(year_counts.values()))
        status = "OK"
        if len(uniq_counts) > 1:
            status = "INCONSISTENT"
        elif not uniq_counts or uniq_counts[0] not in {24, 30}:
            status = "UNUSUAL"
        yrs = sorted(year_counts.keys())
        print(
            f"  - {group:<5} counts {uniq_counts} across years {_fmt_list(yrs)} -> {status}"
        )

    print("\n2) Detected schemes per group (abc vs numeric):")
    for group in sorted(schemes_by_group.keys()):
        schemes = schemes_by_group[group]
        variations = sorted(set(schemes.values()))
        status = "OK"
        if len(variations) > 1:
            status = "MIXED"
        print(f"  - {group:<5} {variations} -> {status}")

    print("\n3) Years with extractor warnings:")
    if not warnings_by_year:
        print("  - none")
    else:
        for y in sorted(warnings_by_year.keys()):
            print(f"  - {y}: {_fmt_list(warnings_by_year[y])}")

    print("\n4) Years with validation warnings:")
    if not validation_warnings_by_year:
        print("  - none")
    else:
        for y in sorted(validation_warnings_by_year.keys()):
            print(f"  - {y}: {_fmt_list(validation_warnings_by_year[y])}")

    print("\n5) Missing answers by group/year (non-empty only):")
    any_missing = False
    for (group, year), missing in sorted(missing_by_group_year.items()):
        if not missing:
            continue
        any_missing = True
        print(f"  - {year} {group}: {_fmt_list(sorted(set(missing)))}")
    if not any_missing:
        print("  - none")

    if processed == 0:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Validate extracted answer key JSONs across years and groups."
    )
    p.add_argument(
        "keys_dir",
        nargs="?",
        default="answer_keys",
        help="Directory containing per-year JSON files",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return validate_dir(Path(args.keys_dir))


if __name__ == "__main__":
    raise SystemExit(main())
