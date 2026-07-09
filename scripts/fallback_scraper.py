"""
fallback_scraper.py
---------------------
A GENUINELY INDEPENDENT data source (not a mirror of NhanAZ-Data) used only
when every primary source in fetch_data.py fails. Scrapes the "15 kỳ gần
nhất" (last 15 draws) table from minhchinh.com's Lotto 5/35 live-results
page, which lists real recent draw numbers directly -- not just a jackpot
figure like jackpot_check.py's sources.

Since this only gives ~15 recent draws (not the full multi-year history),
it is used to APPEND any draws newer than what's already in data/all.csv,
never to replace the whole file. This keeps the pipeline able to catch up
on new results even if NhanAZ-Data's repo is down or stops being updated
for a few days.

Every appended row is tagged with data_source="minhchinh_com_fallback_scraper"
in attributes_json for transparency, and validation_status="unverified_fallback"
so it's clear in the data itself which rows came from the primary dataset
vs. this backup path.
"""

from __future__ import annotations
import csv
import json
import re
import sys
from datetime import datetime, timezone

import requests

URL = "https://www.minhchinh.com/truc-tiep-xo-so-tu-chon-lotto-535.html"
DATA_PATH = "data/all.csv"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}

# Matches "DD/MM/YY Hh ... NNNNNNNNNN SS" with a bounded gap between the
# date/hour label and the digit-string, so this works regardless of exact
# HTML/markdown markup around them (table cells, links, etc.) -- we strip
# tags to plain text first, then look for this pattern.
ROW_RE = re.compile(
    r"(\d{2})/(\d{2})/(\d{2})\s+(\d{1,2})h.{0,200}?(\d{10})\s+(\d{2})(?!\d)",
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _parse_rows(html: str):
    """Parse recent-draws table rows into (date, time, numbers, special).
    Works on raw HTML (tags stripped first) or already-plain text."""
    text = _TAG_RE.sub(" ", html)
    text = re.sub(r"&nbsp;|&amp;|\s+", lambda m: " " if m.group(0) != "&amp;" else "&", text)
    results = []
    for m in ROW_RE.finditer(text):
        dd, mm, yy, hh, digits10, special = m.groups()
        year = 2000 + int(yy)
        draw_date = f"{year:04d}-{mm}-{dd}"
        draw_time = "21:00" if int(hh) >= 20 else "13:00"
        numbers = sorted(int(digits10[i:i + 2]) for i in range(0, 10, 2))
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue  # malformed row, skip defensively
        sp = int(special)
        if sp < 1 or sp > 12:
            continue
        results.append((draw_date, draw_time, numbers, sp))
    return results


def _load_existing():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = rows[0].keys() if rows else None
    return rows, fieldnames


def _existing_keys(rows):
    """Set of (draw_date, draw_time) already present, to avoid duplicates."""
    keys = set()
    for r in rows:
        try:
            attrs = json.loads(r.get("attributes_json") or "{}")
            keys.add((r["draw_date"], attrs.get("draw_time")))
        except (ValueError, json.JSONDecodeError):
            continue
    return keys


def _next_draw_id(rows):
    if not rows:
        return None
    ids = [r["draw_id"] for r in rows if r.get("draw_id", "").isdigit()]
    if not ids:
        return None
    width = len(ids[0])
    return max(int(i) for i in ids), width


def scrape_and_append() -> int:
    """Returns number of new rows appended (0 if nothing new or on failure)."""
    try:
        resp = requests.get(URL, timeout=20, headers=_HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: fallback scraper could not reach {URL}: {e}", file=sys.stderr)
        return 0

    scraped = _parse_rows(resp.text)
    if not scraped:
        print("WARNING: fallback scraper reached the page but found no parseable draw rows "
              "(site layout may have changed)", file=sys.stderr)
        return 0

    try:
        existing_rows, fieldnames = _load_existing()
    except FileNotFoundError:
        print("ERROR: no existing data/all.csv to append to -- fallback scraper only "
              "patches gaps, it can't bootstrap full history.", file=sys.stderr)
        return 0

    if fieldnames is None:
        print("ERROR: data/all.csv has no rows/header to match schema against.", file=sys.stderr)
        return 0

    already = _existing_keys(existing_rows)
    next_id_info = _next_draw_id(existing_rows)
    if next_id_info is None:
        print("ERROR: could not determine next draw_id from existing data.", file=sys.stderr)
        return 0
    next_id, width = next_id_info

    # Scraped rows come newest-first; sort oldest-first to append in order
    scraped.sort(key=lambda r: (r[0], r[1]))

    new_rows = []
    for draw_date, draw_time, numbers, special in scraped:
        if (draw_date, draw_time) in already:
            continue
        next_id += 1
        new_rows.append({
            "product": "lotto535",
            "draw_id": str(next_id).zfill(width),
            "draw_date": draw_date,
            "draw_status": "confirmed",
            "result_json": json.dumps({"numbers": numbers, "special_numbers": [special]}),
            "attributes_json": json.dumps({
                "data_source": "minhchinh_com_fallback_scraper",
                "draw_time": draw_time,
                "official_verification_status": "pending",
            }),
            "official_pdf_urls_json": "[]",
            "source_url": URL,
            "prize_status": "unknown",
            "validation_status": "unverified_fallback",
            "validation_warnings_json": json.dumps(
                ["appended by independent fallback scraper, not the primary dataset"]
            ),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    if not new_rows:
        print("Fallback scraper: no new draws to append (already up to date).")
        return 0

    with open(DATA_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in new_rows:
            # only keep known columns, in the right order, defaulting missing to ""
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    print(f"Fallback scraper: appended {len(new_rows)} new draw(s) from {URL}")
    return len(new_rows)


if __name__ == "__main__":
    scrape_and_append()
