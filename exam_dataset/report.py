from __future__ import annotations

import html
from typing import List, Tuple

from .models import DatasetRecord


def write_html_report(items: List[Tuple[str, DatasetRecord]], out_path: str) -> None:
    """Write an HTML report with a dedicated review section and clearer cards."""

    def needs_review(rec: DatasetRecord) -> bool:
        no_opts = True
        for letter in ["A", "B", "C", "D", "E"]:
            if getattr(rec, f"sol_{letter}") or getattr(rec, f"sol_{letter}_image"):
                no_opts = False
                break
        q = rec.quality
        return (
            no_opts
            or q.needs_review
            or q.ocr_short_text
            or q.key_mismatch
            or q.options_missing_or_extra
            or q.answer_missing
        )

    def option_li(letter: str, rec: DatasetRecord) -> str:
        opt_text = getattr(rec, f"sol_{letter}")
        opt_img = getattr(rec, f"sol_{letter}_image")
        if opt_img:
            return f"<li><span class='lbl'>{letter}</span> <img src='{opt_img}' alt='opt{letter}'></li>"
        else:
            return f"<li><span class='lbl'>{letter}</span> {html.escape(opt_text or '')}</li>"

    def quality_badges(rec: DatasetRecord) -> str:
        badges: List[str] = []
        if rec.quality.needs_review:
            badges.append("<span class='bad'>needs_review</span>")
        if rec.quality.options_missing_or_extra:
            badges.append("<span class='bad'>options_miss/extra</span>")
        if rec.quality.ocr_short_text:
            badges.append("<span class='bad'>ocr_short</span>")
        if rec.quality.key_mismatch:
            badges.append("<span class='bad'>key_mismatch</span>")
        if rec.quality.answer_missing:
            badges.append("<span class='bad'>answer_missing</span>")
        return " ".join(badges)

    def render_item(img_path: str, rec: DatasetRecord) -> List[str]:
        out: List[str] = []
        out.append("<div class='card'>")
        out.append(f"<div class='head'><span class='qid'>{html.escape(rec.id)}</span><span class='meta'>Pts: {rec.points} | Ans: {html.escape(rec.answer or '')}</span><span class='badges'>{quality_badges(rec)}</span></div>")
        out.append("<div class='body'>")
        out.append(f"<div class='qimg'><img src='{img_path}' alt='question'></div>")
        out.append("<div class='qtext'>")
        out.append("<h4>Extracted Question Text</h4>")
        out.append(f"<pre>{html.escape(rec.problem_statement or '')}</pre>")
        out.append("<h4>Extracted Options</h4>")
        out.append("<ul class='opts'>")
        for L in ["A", "B", "C", "D", "E"]:
            out.append(option_li(L, rec))
        out.append("</ul>")
        if rec.associated_images:
            out.append("<h4>Associated Images</h4><div class='assoc'>")
            for p in rec.associated_images:
                out.append(f"<img src='{p}' alt='assoc'>")
            out.append("</div>")
        out.append("</div>")  # qtext
        out.append("</div>")  # body
        out.append("</div>")  # card
        return out

    # Partition
    review: List[Tuple[str, DatasetRecord]] = []
    normal: List[Tuple[str, DatasetRecord]] = []
    for img_path, rec in items:
        (review if needs_review(rec) else normal).append((img_path, rec))

    css = (
        "<style>"
        "/* Global image bounds to avoid oversized images */"
        "img{max-width:800px;height:auto;}"
        "body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif;margin:16px;}"
        ".card{border:1px solid #ddd;border-radius:8px;margin:16px 0;box-shadow:0 1px 3px rgba(0,0,0,0.06);}"
        ".head{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:8px 12px;border-bottom:1px solid #eee;background:#fafafa;}"
        ".qid{font-weight:600;} .meta{color:#555;} .bad{color:#b00;font-weight:600;margin-left:8px;}"
        ".body{display:flex;gap:16px;padding:12px;flex-wrap:wrap;}"
        ".qimg img{max-width:600px;border:1px solid #eee;border-radius:4px;}"
        ".qtext{flex:1;min-width:300px;} .qtext pre{white-space:pre-wrap;background:#f9f9f9;padding:8px;border:1px solid #eee;border-radius:4px;}"
        ".opts{columns:2;-webkit-columns:2;-moz-columns:2;list-style:none;padding-left:0;} .opts li{margin:6px 0;} .opts .lbl{display:inline-block;width:20px;font-weight:600;} .opts li img{max-width:220px;height:auto;display:block;margin-top:4px;border:1px solid #eee;border-radius:4px;}"
        ".assoc img{max-width:280px;margin:6px;border:1px solid #eee;border-radius:4px;}"
        "h2{margin-top:8px;} section{margin-bottom:24px;}"
        "</style>"
    )

    lines: List[str] = ["<html><head><meta charset='utf-8'>", css, "</head><body>"]

    lines.append("<section>")
    lines.append(f"<h2>Needs Review ({len(review)})</h2>")
    if not review:
        lines.append("<p>No items flagged for review.</p>")
    else:
        for img_path, rec in review:
            lines.extend(render_item(img_path, rec))
    lines.append("</section>")

    lines.append("<section>")
    lines.append(f"<h2>All Items ({len(items)})</h2>")
    for img_path, rec in normal:
        lines.extend(render_item(img_path, rec))
    lines.append("</section>")

    lines.append("</body></html>")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
