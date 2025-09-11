from __future__ import annotations

import argparse
import os

from .config import PATHS
from .dataset_builder import run_build
from .pdf_render import ensure_dir


def main() -> None:
    p = argparse.ArgumentParser("exam-dataset")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Build dataset JSONL from original_pdfs")
    b.add_argument("--out", default=os.path.join(PATHS.dataset, "dataset.jsonl"))
    b.add_argument("--no-ocr", action="store_true")
    b.add_argument("--answer-key", help="Path to answer key JSON", default=None)
    b.add_argument("--report", help="Path to HTML report", default=os.path.join(PATHS.reports, "report.html"))

    args = p.parse_args()
    ensure_dir(PATHS.dataset)

    if args.cmd == "build":
        run_build(
            output_jsonl=args.out,
            use_ocr=not args.no_ocr,
            answer_key=args.answer_key,
            report_html=args.report,
        )


if __name__ == "__main__":
    main()
