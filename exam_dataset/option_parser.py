from __future__ import annotations

import re
from typing import Dict, Tuple


ANCHORS = [
    r"^[ \t|]*\(([A-E])\)[ \t]+",                            # (A) ...
    r"^[ \t|]*\((?:\\mathbf\{)?([A-E])(?:\})?\)[ \t]+",     # (\mathbf{A}) ...
    r"^[ \t|]*(?:\\mathbf\{)?([A-E])(?:\})?[\)\.:\-][ \t]+",  # A) / A. / A:
    r"^[ \t|]*([A-E])[ \t]+\–[ \t]+"                          # A – ...
]


def split_options(text: str) -> Tuple[str, Dict[str, str]]:
    # Normalize LaTeX and table pipes to help anchor detection
    t = text
    t = re.sub(r"\(\s*\\?mathbf\{([A-E])\}\s*\)", r"(\1)", t)
    t = re.sub(r"\\?mathbf\{([A-E])\}\)", r"\1)", t)
    lines = t.splitlines()
    idxs = []
    letters = []
    for i, raw in enumerate(lines):
        line = raw.lstrip(" |")
        for pat in ANCHORS:
            m = re.match(pat, line)
            if m:
                letter = m.group(1)
                if letter in ["A", "B", "C", "D", "E"]:
                    idxs.append(i)
                    letters.append(letter)
                break
    if len(letters) == 5:
        parts: Dict[str, str] = {}
        for j, letter in enumerate(letters):
            start = idxs[j]
            end = idxs[j + 1] if j + 1 < len(idxs) else len(lines)
            chunk = "\n".join(lines[start:end])
            chunk = re.sub(r"^[ \t|]*\(([A-E])\)[ \t]+", "", chunk)
            chunk = re.sub(r"^[ \t|]*\((?:\\mathbf\{)?([A-E])(?:\})?\)[ \t]+", "", chunk)
            chunk = re.sub(r"^[ \t|]*(?:\\mathbf\{)?([A-E])(?:\})?[\)\.:\-][ \t]+", "", chunk)
            chunk = re.sub(r"^[ \t|]*([A-E])[ \t]+\–[ \t]+", "", chunk)
            chunk = re.sub(r"^[ \t]*\\mathbf\{([A-E])\}[ \t]+", "", chunk)
            chunk = re.sub(r"^[ \t]*\*\*([A-E])\*\*[ \t]+", "", chunk)
            chunk = re.sub(r"^[ \t]*\|[ \t]*([A-E])[\)\.:\-]?[ \t]*\|[ \t]+", "", chunk)
            chunk = re.sub(r"^[ \t]*\|[ \t]*\\mathbf\{([A-E])\}[ \t]*\|[ \t]+", "", chunk)
            chunk = re.sub(r"^[ \t]*([A-E])[ \t]+[\-–—][ \t]+", "", chunk)
            parts[letter] = chunk.strip()
        stem = "\n".join(lines[: idxs[0]]).strip()
        return stem, parts

    # Fallback: scan anchors anywhere (inline math/table rows), assign by the letter at each anchor
    body = t.replace("$$", " ")
    pat = re.compile(r"\((?:\\mathbf\{)?([A-E])(?:\})?\)\s*|\b([A-E])\)\s*")
    matches = list(pat.finditer(body))
    if matches:
        # Sort anchors by appearance; create segments between successive anchors
        anchors = [(m.start(), m.end(), (m.group(1) or m.group(2))) for m in matches]
        anchors.sort(key=lambda x: x[0])
        if anchors:
            head = body[: anchors[0][0]].strip()
            parts: Dict[str, str] = {}
            for idx, (st, en, L) in enumerate(anchors):
                seg_start = en
                seg_end = anchors[idx + 1][0] if idx + 1 < len(anchors) else len(body)
                # Save only the first segment encountered for each letter
                if L in ["A", "B", "C", "D", "E"] and L not in parts:
                    parts[L] = body[seg_start:seg_end].strip()
            if all(k in parts for k in ["A", "B", "C", "D", "E"]):
                return head, parts

    return t.strip(), {}
