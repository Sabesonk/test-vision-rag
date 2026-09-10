"""fixes/001's verification sweep: every PDF of the real corpus through the shipped ladder.

Needs no key, no Qdrant and no spend — `plan()` is a pure function of the page count, the outline
and the file size. Level 1 is given the best possible break by feeding it each file's own outline,
which is strictly better than what S1 can read off rendered front matter.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pymupdf

from vsir.config import CAP_PAGES_PER_WINDOW
from vsir.ingest import window as w

if len(sys.argv) < 2:
    raise SystemExit("usage: sweep-corpus.py <corpus-root>   (a directory of PDFs, read only)")
ROOT = Path(sys.argv[1]).expanduser()
if not ROOT.is_dir():
    raise SystemExit(f"not a directory: {ROOT}")

levels: Counter[str] = Counter()
pages_by_level: Counter[str] = Counter()
refused: list[tuple[str, int, str]] = []
windows_total = 0
pages_total = 0
docs = 0
violations: list[str] = []
worst: list[tuple[int, str]] = []

for pdf in sorted(ROOT.rglob("*")):
    if pdf.suffix.lower() != ".pdf" or not pdf.is_file():
        continue
    try:
        with pymupdf.open(pdf) as doc:
            page_count = doc.page_count
            outline = [{"title": t, "page_no": p} for _lvl, t, p in doc.get_toc()]
    except Exception as broken:                      # a file PyMuPDF cannot open is not the ladder
        refused.append((pdf.name, 0, f"unreadable: {type(broken).__name__}"))
        continue

    docs += 1
    pages_total += page_count
    try:
        plan = w.plan(page_count, toc=outline, size_bytes=pdf.stat().st_size,
                      document=pdf.stem)
    except w.WindowError as refusal:
        refused.append((pdf.name, page_count, refusal.code))
        continue

    levels[f"level {plan.level}"] += 1
    pages_by_level[f"level {plan.level}"] += page_count
    windows_total += len(plan.windows)
    worst.append((len(plan.windows), f"{pdf.name} ({page_count}pp)"))

    if not plan.covers(page_count):
        violations.append(f"{pdf.name}: does not tile {page_count} pages exactly once")
    if any(win.pages > CAP_PAGES_PER_WINDOW for win in plan.windows):
        violations.append(f"{pdf.name}: a window exceeds the {CAP_PAGES_PER_WINDOW}-page cap")
    if not plan.parallel:
        violations.append(f"{pdf.name}: plan is not parallel")

print(f"corpus            {ROOT}")
print(f"documents planned {docs} · pages {pages_total:,} · windows {windows_total:,}")
for level in sorted(levels):
    print(f"  {level:<9} {levels[level]:>4} document(s)  {pages_by_level[level]:>6,} page(s)")
print(f"refused           {len(refused)}")
for name, pages, code in refused[:20]:
    print(f"    {pages:>5}pp  {code}  {name}")
print(f"coverage/cap/parallel violations: {len(violations)}")
for line in violations[:20]:
    print(f"    {line}")
print("most windows:")
for count, name in sorted(worst, reverse=True)[:5]:
    print(f"    {count:>4} windows  {name}")
