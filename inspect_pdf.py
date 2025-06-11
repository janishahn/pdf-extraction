import argparse
import fitz
import os
from typing import Optional


def inspect_page(doc: fitz.Document, page_index: int):
    page = doc[page_index]
    text_dict = page.get_text("dict")
    print(f"\n=== Page {page_index + 1}/{len(doc)} ===")
    for bi, block in enumerate(text_dict.get("blocks", [])):
        btype = block.get("type")
        bbox = block.get("bbox")
        print(f"\n-- Block {bi} (type={btype}) bbox={bbox}")
        if btype != 0:
            continue  # Non-text block
        for li, line in enumerate(block.get("lines", [])):
            l_bbox = line.get("bbox")
            spans = line.get("spans", [])
            line_text = ''.join(span.get("text", '') for span in spans)
            print(f"  Line {li} y={l_bbox[1]:.1f}-{l_bbox[3]:.1f} x={l_bbox[0]:.1f}-{l_bbox[2]:.1f}: {line_text}")


def main(pdf_path: str, pages: Optional[str]):
    if not os.path.isfile(pdf_path):
        raise SystemExit(f"File not found: {pdf_path}")
    doc = fitz.open(pdf_path)
    try:
        if pages:
            indices = []
            for part in pages.split(','):
                if '-' in part:
                    a, b = part.split('-')
                    indices.extend(range(int(a) - 1, int(b)))
                else:
                    indices.append(int(part) - 1)
        else:
            indices = list(range(min(3, len(doc))))
        indices = [i for i in indices if 0 <= i < len(doc)]
        for idx in indices:
            inspect_page(doc, idx)
    finally:
        doc.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect PDF text structure using PyMuPDF.")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--pages", help="Page numbers to inspect (e.g., '1', '1-3', '1,3,5')")
    args = parser.parse_args()
    main(args.pdf, args.pages) 