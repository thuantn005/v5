"""
fetch_data.py
-------------
Downloads the latest Lotto 5/35 historical draw CSV from the public
NhanAZ-Data/vietlott-data-research dataset repo and saves it locally.

If you have your own scraper/data source, just point SOURCE_URL at it --
everything downstream only needs a CSV with a `draw_id` and `result_json`
column in the same shape as this dataset.
"""

import sys
import requests

SOURCE_URL = (
    "https://raw.githubusercontent.com/NhanAZ-Data/"
    "vietlott-data-research/main/datasets/draws/lotto535/all.csv"
)
OUTPUT_PATH = "data/all.csv"


def main():
    resp = requests.get(SOURCE_URL, timeout=30)
    resp.raise_for_status()
    content = resp.text
    if "draw_id" not in content.splitlines()[0]:
        print("ERROR: downloaded file does not look like the expected CSV", file=sys.stderr)
        sys.exit(1)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    line_count = content.count("\n")
    print(f"Saved {OUTPUT_PATH} ({line_count} lines)")


if __name__ == "__main__":
    main()
