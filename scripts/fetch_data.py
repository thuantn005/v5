"""
fetch_data.py
-------------
Scrapes Lotto 5/35 draw results directly from lottery result websites and
appends any new draws to data/all.csv. No external data-repo dependency.

data/all.csv is committed with full draw history. This script only APPENDS
draws not yet present (deduped by draw_date+draw_time). Running it multiple
times is safe. If every source fails, the existing file is kept intact and
the pipeline continues on the last known-good data.

Sources (tried in parallel, all independent):
  1. minhchinh.com — Vietnamese results site, ~15 recent draws, time-aware
  2. vietlott.vn   — official Vietlott site, shows the latest 1–3 draws
                     with the official draw_id
"""

from __future__ import annotations
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

DATA_PATH = "data/all.csv"
TIMEOUT = 25

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9",
}
_TAG_RE = re.compile(r"<[^>]+>")


def _strip(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    return re.sub(r"\s+", " ", text)


# ── Source 1: minhchinh.com ───────────────────────────────────────────────────
# Shows ~15 recent draws; each row has date, hour, 10-digit result, 2-digit special.
_MC_URL = "https://www.minhchinh.com/truc-tiep-xo-so-tu-chon-lotto-535.html"
_MC_RE = re.compile(
    r"(\d{2})/(\d{2})/(\d{2})\s+(\d{1,2})h.{0,200}?(\d{10})\s+(\d{2})(?!\d)",
    re.DOTALL,
)


def _parse_minhchinh(html: str) -> list[dict]:
    text = _strip(html)
    rows = []
    for m in _MC_RE.finditer(text):
        dd, mm, yy, hh, digits10, sp_str = m.groups()
        draw_date = f"20{yy}-{mm}-{dd}"
        draw_time = "21:00" if int(hh) >= 20 else "13:00"
        numbers = sorted(int(digits10[i:i + 2]) for i in range(0, 10, 2))
        sp = int(sp_str)
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if sp < 1 or sp > 12:
            continue
        rows.append({"draw_date": draw_date, "draw_time": draw_time,
                     "numbers": numbers, "special": sp,
                     "source_url": _MC_URL, "draw_id_hint": None})
    return rows


def _fetch_minhchinh() -> list[dict]:
    try:
        r = requests.get(_MC_URL, timeout=TIMEOUT, headers=_HEADERS)
        r.raise_for_status()
        rows = _parse_minhchinh(r.text)
        if rows:
            print(f"minhchinh.com: {len(rows)} recent draw(s) found")
        else:
            print("WARNING: minhchinh.com: page fetched but no draws parsed "
                  "(site layout may have changed)", file=sys.stderr)
        return rows
    except requests.RequestException as e:
        print(f"WARNING: minhchinh.com fetch failed: {e}", file=sys.stderr)
        return []


# ── Source 2: vietlott.vn ────────────────────────────────────────────────────
# Official site. Shows the latest draw result with the official draw_id.
# Format observed: "Kỳ quay thưởng #00752 ngày 09/07/2026 ... 1419252830|04"
_VL_URL = "https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/535"
_VL_DRAW_RE = re.compile(
    r"#(\d+)\s+ng[aà]y\s+(\d{2})/(\d{2})/(\d{4})"
)
_VL_RESULT_RE = re.compile(r"(\d{10})\|(\d{2})")
_VL_TIME_RE = re.compile(r"(13|21)[h:]0*0")


def _parse_vietlott(html: str) -> list[dict]:
    text = _strip(html)
    rows = []
    for dm in _VL_DRAW_RE.finditer(text):
        draw_id_str, dd, mm, yyyy = dm.groups()
        draw_date = f"{yyyy}-{mm}-{dd}"
        snippet = text[dm.start():dm.start() + 400]
        rm = _VL_RESULT_RE.search(snippet)
        if not rm:
            continue
        digits10, sp_str = rm.groups()
        numbers = sorted(int(digits10[i:i + 2]) for i in range(0, 10, 2))
        sp = int(sp_str)
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if sp < 1 or sp > 12:
            continue
        tm = _VL_TIME_RE.search(snippet)
        draw_time = f"{tm.group(1)}:00" if tm else None
        rows.append({"draw_date": draw_date, "draw_time": draw_time,
                     "numbers": numbers, "special": sp,
                     "source_url": _VL_URL, "draw_id_hint": draw_id_str})
    return rows


def _fetch_vietlott() -> list[dict]:
    try:
        r = requests.get(_VL_URL, timeout=TIMEOUT, headers=_HEADERS)
        r.raise_for_status()
        rows = _parse_vietlott(r.text)
        if rows:
            print(f"vietlott.vn: {len(rows)} draw(s) found (official ids: "
                  f"{', '.join(d['draw_id_hint'] for d in rows if d['draw_id_hint'])})")
        else:
            print("WARNING: vietlott.vn: page fetched but no draws parsed "
                  "(site layout may have changed)", file=sys.stderr)
        return rows
    except requests.RequestException as e:
        print(f"WARNING: vietlott.vn fetch failed: {e}", file=sys.stderr)
        return []


# ── CSV helpers ──────────────────────────────────────────────────────────────

def _load_csv() -> tuple[list[dict], list[str] | None]:
    try:
        with open(DATA_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return rows, list(rows[0].keys()) if rows else None
    except FileNotFoundError:
        return [], None


def _existing_keys(rows: list[dict]) -> set[tuple]:
    """(draw_date, draw_time) pairs already in the CSV, used for dedup."""
    keys = set()
    for r in rows:
        try:
            attrs = json.loads(r.get("attributes_json") or "{}")
            keys.add((r["draw_date"], attrs.get("draw_time")))
        except (ValueError, json.JSONDecodeError):
            continue
    return keys


def _max_draw_id(rows: list[dict]) -> tuple[int, int]:
    """Returns (max_numeric_id, zero_pad_width)."""
    ids = [r["draw_id"] for r in rows if r.get("draw_id", "").isdigit()]
    if not ids:
        return 0, 5
    return max(int(i) for i in ids), len(ids[0])


def _infer_time(draw_date: str, existing_keys: set[tuple]) -> str:
    """If the scraper couldn't parse a time, infer from which slot is already taken."""
    if (draw_date, "13:00") in existing_keys:
        return "21:00"
    if (draw_date, "21:00") in existing_keys:
        return "13:00"
    return "21:00"


def _make_row(fieldnames: list[str], draw: dict, draw_id_str: str,
              data_source: str) -> dict:
    row = {
        "product": "lotto535",
        "draw_id": draw_id_str,
        "draw_date": draw["draw_date"],
        "draw_status": "confirmed",
        "result_json": json.dumps({
            "numbers": draw["numbers"],
            "special_numbers": [draw["special"]],
        }),
        "attributes_json": json.dumps({
            "data_source": data_source,
            "draw_time": draw["draw_time"],
        }),
        "official_pdf_urls_json": "[]",
        "source_url": draw.get("source_url", ""),
        "prize_status": "unknown",
        "validation_status": "scraped",
        "validation_warnings_json": json.dumps(
            [f"scraped from {data_source}"]
        ),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    return {k: row.get(k, "") for k in fieldnames}


def _append_draws(scraped: list[dict], data_source: str) -> int:
    """Append scraped draws not already in the CSV. Returns count appended."""
    existing_rows, fieldnames = _load_csv()
    if fieldnames is None:
        print(f"ERROR: {DATA_PATH} is empty or missing — cannot append.",
              file=sys.stderr)
        return 0

    existing_k = _existing_keys(existing_rows)
    max_id, width = _max_draw_id(existing_rows)

    # Sort oldest-first so IDs increment in chronological order
    scraped.sort(key=lambda d: (d["draw_date"], d.get("draw_time") or ""))

    new_rows = []
    running_max = max_id
    for draw in scraped:
        if draw["draw_time"] is None:
            draw["draw_time"] = _infer_time(draw["draw_date"], existing_k)
        key = (draw["draw_date"], draw["draw_time"])
        if key in existing_k:
            continue

        # Prefer the official draw_id supplied by vietlott.vn when available
        # and it makes sense (> current max, within a reasonable gap)
        hint = draw.get("draw_id_hint")
        if hint and hint.isdigit():
            hint_id = int(hint)
            if running_max < hint_id <= running_max + 10:
                running_max = hint_id
            else:
                running_max += 1
        else:
            running_max += 1

        draw_id_str = str(running_max).zfill(width)
        new_rows.append(_make_row(fieldnames, draw, draw_id_str, data_source))
        existing_k.add(key)

    if not new_rows:
        print(f"{data_source}: no new draws to append (already up to date).")
        return 0

    with open(DATA_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in new_rows:
            writer.writerow(row)

    print(f"{data_source}: appended {len(new_rows)} new draw(s).")
    return len(new_rows)


def main():
    if not os.path.exists(DATA_PATH):
        print(f"ERROR: {DATA_PATH} not found. "
              "Restore it from git history or a backup before running fetch_data.",
              file=sys.stderr)
        sys.exit(1)

    total = 0

    # minhchinh.com: primary — covers ~15 recent draws
    mc = _fetch_minhchinh()
    if mc:
        total += _append_draws(mc, "minhchinh_com_scraper")

    # vietlott.vn: secondary — official source with draw_id, catches the latest
    vl = _fetch_vietlott()
    if vl:
        total += _append_draws(vl, "vietlott_vn_official")

    if not mc and not vl:
        print("WARNING: all scraping sources failed — "
              "keeping existing data/all.csv unchanged. "
              "Pipeline will continue on the last known-good data.",
              file=sys.stderr)

    if total:
        print(f"Total new draws appended: {total}")


if __name__ == "__main__":
    main()
