#!/usr/bin/env python3

"""
CLI utility that strips image answer options from questions that already have text options.

Usage example:

    uv run python scripts/remove_overlapping_option_images.py \
        --input output/dataset_builder/dataset/dataset_full.jsonl \
        --output output/dataset_builder/dataset/dataset_full.no_images.jsonl \
        --subset output/dataset_builder/dataset/dataset_full.corrected_only.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Tuple

LETTERS = ["A", "B", "C", "D", "E"]


def _is_nonempty(value) -> bool:
    """Return True if a field should be considered present/non-empty.

    - Treat non-empty strings as present
    - Treat any non-None, non-empty non-string value as present
    """
    if isinstance(value, str):
        return bool(value.strip())
    return value not in (None, "", [])


def _has_text_option(record: dict) -> bool:
    """True if the record has text for any option letter."""
    for letter in LETTERS:
        if _is_nonempty(record.get(f"sol_{letter}")):
            return True
    return False


def _has_image_option(record: dict) -> bool:
    """True if the record has any image option for any letter."""
    for letter in LETTERS:
        if _is_nonempty(record.get(f"sol_{letter}_image")):
            return True
    return False


def _has_same_letter_overlap(record: dict) -> bool:
    """True if any option letter has both text and image present.

    This is the harmful overlap we want to eliminate without deleting
    image options that have no text fallback for the same letter.
    """
    for letter in LETTERS:
        if _is_nonempty(record.get(f"sol_{letter}")) and _is_nonempty(
            record.get(f"sol_{letter}_image")
        ):
            return True
    return False


def _records_with_overlap(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if _has_same_letter_overlap(data):
                count += 1
    return count


def _iter_records(path: Path) -> Iterable[Tuple[dict, str]]:
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            yield json.loads(line), raw


def _remove_image_options(record: dict) -> bool:
    """Remove image options only where the same-letter text exists.

    This avoids destroying the only representation of an option (image)
    when the corresponding text is missing, while still removing the
    harmful text+image overlap per option letter.
    """
    changed = False
    for letter in LETTERS:
        img_key = f"sol_{letter}_image"
        txt_key = f"sol_{letter}"
        if _is_nonempty(record.get(img_key)) and _is_nonempty(record.get(txt_key)):
            record[img_key] = None
            changed = True
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Remove image-based answer options from questions that already have text-based options."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Source dataset JSONL file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination JSONL for the corrected dataset (defaults to <input>.no_images.jsonl).",
    )
    parser.add_argument(
        "--subset",
        type=Path,
        help="Destination JSONL for corrected-only records (defaults to <input>.corrected_only.jsonl).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow writing to existing output files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_path: Path = args.input
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    output_path: Path = args.output or input_path.with_suffix(".no_images.jsonl")
    subset_path: Path = args.subset or input_path.with_suffix(".corrected_only.jsonl")

    if not args.overwrite:
        for target in (output_path, subset_path):
            if target.exists():
                raise SystemExit(
                    f"Refusing to overwrite existing file: {target} (use --overwrite to allow)."
                )

    before = _records_with_overlap(input_path)
    print(
        f"Records with same-letter text+image overlap before: {before}"
    )

    corrected_count = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subset_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8") as src, \
            output_path.open("w", encoding="utf-8") as dst_all, \
            subset_path.open("w", encoding="utf-8") as dst_subset:
        for raw in src:
            line = raw.strip()
            if not line:
                continue
            record = json.loads(line)
            # Only act when there is same-letter overlap; this gating avoids
            # touching records where images are the only representation for a letter.
            if _has_same_letter_overlap(record):
                if _remove_image_options(record):
                    corrected_count += 1
                    dst_subset.write(json.dumps(record, ensure_ascii=False) + "\n")
            dst_all.write(json.dumps(record, ensure_ascii=False) + "\n")

    after = _records_with_overlap(output_path)
    print(f"Records with same-letter text+image overlap after:  {after}")
    print(f"Records corrected (images removed): {corrected_count}")

    if after != 0:
        print(
            "Warning: Some records still have overlapping text and image options for the same letter."
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
