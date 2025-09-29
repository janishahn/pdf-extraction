from __future__ import annotations

import argparse
import os

from .config import PATHS
from .dataset_builder import run_build
from .pdf_render import ensure_dir
from .edits import apply_file

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

    rv = sub.add_parser("review", help="Run the FastAPI review server")
    rv.add_argument("--jsonl", default=os.path.join(PATHS.dataset, "dataset.jsonl"))
    rv.add_argument("--edits", default=None)
    rv.add_argument("--host", default="127.0.0.1")
    rv.add_argument("--port", type=int, default=8000)
    rv.add_argument("--open-browser", action="store_true")

    ae = sub.add_parser("apply-edits", help="Merge edits overlay into a new JSONL")
    ae.add_argument("--in", dest="inp", default=os.path.join(PATHS.dataset, "dataset.jsonl"))
    ae.add_argument("--edits", default=os.path.join(PATHS.dataset, "edits.json"))
    ae.add_argument("--out", default=os.path.join(PATHS.dataset, "dataset.edited.jsonl"))
    ae.add_argument("--only-reviewed", action="store_true")

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
    elif args.cmd == "review":
        from .review_server import create_app
        import uvicorn  # type: ignore
        import webbrowser

        # Derive a dataset-specific edits file if none explicitly provided
        if not args.edits:
            jdir = os.path.dirname(args.jsonl) or PATHS.dataset
            jstem = os.path.splitext(os.path.basename(args.jsonl))[0]
            derived_edits = os.path.join(jdir, f"{jstem}.edits.json")
        else:
            derived_edits = args.edits

        app = create_app(args.jsonl, derived_edits, PATHS.crops, PATHS.dataset)
        url = f"http://{args.host}:{args.port}"
        if args.open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        uvicorn.run(app, host=args.host, port=int(args.port), log_level="info")
    elif args.cmd == "apply-edits":
        apply_file(args.inp, args.edits, args.out, only_reviewed=bool(args.only_reviewed))
        print(f"Applied edits: {args.inp} + {args.edits} -> {args.out}")


if __name__ == "__main__":
    main()
