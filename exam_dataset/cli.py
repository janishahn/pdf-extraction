from __future__ import annotations

import argparse
import os

from .config import PATHS
from .dataset_builder import run_build
from .pdf_render import ensure_dir

# Load .env if present so OCR API keys are available via env vars
try:
    from dotenv import load_dotenv, find_dotenv  # type: ignore

    load_dotenv(find_dotenv(), override=False)
except Exception:
    # python-dotenv is optional at runtime; the OCR module also attempts loading.
    pass


def main() -> None:
    parser = argparse.ArgumentParser("exam-dataset")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Build dataset JSONL from original_pdfs")
    b.add_argument("--out", default=os.path.join(PATHS.dataset, "dataset.jsonl"))
    b.add_argument("--no-ocr", action="store_true")
    b.add_argument("--answer-key", help="Path to answer key JSON", default=None)
    b.add_argument(
        "--answer-dir",
        help="Directory with per-year answer key JSONs (e.g., 'answer_keys')",
        default=None,
    )
    b.add_argument("--report", help="Path to HTML report", default=os.path.join(PATHS.reports, "report.html"))
    b.add_argument("--ocr-batch-size", type=int, default=5, help="Max concurrent OCR requests per exam (default: 5)")

    m = sub.add_parser("answers-merge", help="Merge per-year answer keys into a combined JSON mapping exam->problem->answer")
    m.add_argument("--keys-dir", default=os.path.join(os.getcwd(), "answer_keys"))
    m.add_argument("--out", default=os.path.join(PATHS.dataset, "combined_answers.json"))

    pk = sub.add_parser("pack", help="Pack a JSONL dataset into a Parquet file with embedded images")
    pk.add_argument("--jsonl", default=os.path.join(PATHS.dataset, "dataset.jsonl"))
    pk.add_argument("--out", default=os.path.join(PATHS.dataset, "dataset.parquet"))
    pk.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()
    ensure_dir(PATHS.dataset)

    if args.cmd == "build":
        run_build(
            output_jsonl=args.out,
            use_ocr=not args.no_ocr,
            answer_key=args.answer_key,
            report_html=args.report,
            answer_dir=args.answer_dir,
            ocr_batch_size=args.ocr_batch_size,
        )
    elif args.cmd == "answers-merge":
        from .answer_key_loader import build_answer_map_from_year_files
        import json as _json

        ensure_dir(os.path.dirname(args.out))
        m = build_answer_map_from_year_files(args.keys_dir, PATHS.original_pdfs)
        nested: dict[str, dict[str, str]] = {}
        for (exam_id, pn), ans in m.items():
            nested.setdefault(exam_id, {})[pn] = ans
        with open(args.out, "w", encoding="utf-8") as f:
            _json.dump(nested, f, ensure_ascii=False, indent=2)
        print(f"Wrote combined answers to {args.out}")
    elif args.cmd == "pack":
        from .pack import pack_jsonl_to_parquet
        pack_jsonl_to_parquet(args.jsonl, args.out, args.limit)
        print(f"Packed {args.jsonl} -> {args.out}")


if __name__ == "__main__":
    main()
