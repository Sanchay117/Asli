"""Strip markdown images and blank lines from an extracted page, print the rest.

Usage: python3 scripts/clean_text.py <file> [max_chars]
"""
import re
import sys

text = open(sys.argv[1]).read()
text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
lines = [l.strip() for l in text.splitlines() if l.strip()]
out = "\n".join(lines)
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
print(out[:limit])
print(f"\n--- {len(out)} chars after cleaning ---")
