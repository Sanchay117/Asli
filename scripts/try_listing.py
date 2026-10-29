"""Read listing URLs and print the parsed fields.

Usage: python -m scripts.try_listing <url> [<url> ...]
"""
import json
import sys

from asli.listing import read_listing

for url in sys.argv[1:]:
    listing, calls, _ = read_listing(url)
    print(json.dumps(listing, indent=1, ensure_ascii=False)[:2500])
    for c in calls:
        print("  call:", c)
    print("-" * 60)
