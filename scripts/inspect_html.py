"""Print short context windows around keywords in a saved HTML page, plus ld+json blocks.

Usage: python3 scripts/inspect_html.py <html_file> <keyword> [<keyword> ...]
"""
import re
import sys

html = open(sys.argv[1]).read()

for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
    print("[ld+json]", block[:800], "\n")

for kw in sys.argv[2:]:
    hits = [m.start() for m in re.finditer(re.escape(kw), html)][:4]
    print(f"===== {kw!r}: {len(hits)} shown")
    for h in hits:
        snippet = html[max(0, h - 250): h + 250]
        snippet = re.sub(r"<[^>]+>", " ", snippet)
        snippet = re.sub(r"\s+", " ", snippet)
        print("  ...", snippet, "...\n")
