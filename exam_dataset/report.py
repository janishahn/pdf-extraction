from __future__ import annotations

import html
from typing import Iterable, List, Tuple

from .models import DatasetRecord


def write_html_report(items: List[Tuple[str, DatasetRecord]], out_path: str) -> None:
    """Write a simple HTML report for spot-checking."""
    lines: List[str] = [
        "<html><head><meta charset='utf-8'><style>img{max-width:600px;}</style></head><body>",
    ]
    for img_path, rec in items:
        lines.append("<div style='margin-bottom:40px;'>")
        lines.append(f"<h3>{html.escape(rec.id)}</h3>")
        lines.append(f"<p><strong>Points:</strong> {rec.points} | <strong>Answer:</strong> {html.escape(rec.answer or '')}</p>")
        lines.append(f"<img src='{img_path}' alt='question'>")
        lines.append("<pre>")
        lines.append(html.escape(rec.problem_statement))
        lines.append("</pre>")
        lines.append("<ul>")
        for letter in ["A", "B", "C", "D", "E"]:
            opt_text = getattr(rec, f"sol_{letter}")
            opt_img = getattr(rec, f"sol_{letter}_image")
            if opt_img:
                lines.append(f"<li>{letter}: <img src='{opt_img}' alt='opt{letter}'></li>")
            else:
                lines.append(f"<li>{letter}: {html.escape(opt_text or '')}</li>")
        lines.append("</ul>")
        if rec.associated_images:
            lines.append("<p>Associated images:</p><div>")
            for p in rec.associated_images:
                lines.append(f"<img src='{p}' alt='assoc'>")
            lines.append("</div>")
        lines.append("</div>")
    lines.append("</body></html>")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))