"""
fetch_data.py
-------------
Cập nhật data/all.csv với kết quả kỳ quay mới từ nhiều nguồn độc lập.
Chỉ THÊM kỳ mới (không ghi đè), an toàn khi chạy nhiều lần.

Thứ tự nguồn:
  1. minhchinh.com  — chính, ~15 kỳ gần nhất, có giờ quay (13:00/21:00)
  2. vietlott.vn    — phụ 1, kỳ mới nhất với draw_id chính thức
  3. NhanAZ-Data    — phụ 2, dataset GitHub tổng hợp; dùng để bắt kịp kỳ
                      bị bỏ qua (bù khoảng trống mà 2 nguồn trên chưa phủ)

Nếu tất cả nguồn lỗi → giữ nguyên data/all.csv, pipeline vẫn chạy được.
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


# ── Source 3: NhanAZ-Data (supplementary) ────────────────────────────────────
# Full-history CSV dataset. Used as a gap-filler: any draws with draw_id
# greater than our current max that minhchinh/vietlott didn't catch yet.
# Schema matches data/all.csv exactly, so rows are used as-is.
_NHANAZ_URLS = [
    "https://raw.githubusercontent.com/NhanAZ-Data/vietlott-data-research"
    "/main/datasets/draws/lotto535/all.csv",
    "https://cdn.jsdelivr.net/gh/NhanAZ-Data/vietlott-data-research"
    "@main/datasets/draws/lotto535/all.csv",
]


def _fetch_nhanaz() -> list[dict]:
    for url in _NHANAZ_URLS:
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=_HEADERS)
            r.raise_for_status()
            rows = list(csv.DictReader(r.text.splitlines()))
            if rows:
                print(f"NhanAZ-Data: downloaded {len(rows)} total rows from {url}")
                return rows
        except requests.RequestException as e:
            print(f"WARNING: NhanAZ-Data {url} failed: {e}", file=sys.stderr)
    return []


def _append_nhanaz_supplement(nhanaz_rows: list[dict]) -> int:
    """Append rows from NhanAZ-Data whose draw_id exceeds our current max.
    Their schema matches ours exactly, so rows are written directly."""
    existing_rows, fieldnames = _load_csv()
    if not existing_rows or fieldnames is None:
        return 0

    max_id, _ = _max_draw_id(existing_rows)

    new_rows = []
    for r in nhanaz_rows:
        try:
            rid = int(r.get("draw_id") or "0")
        except ValueError:
            continue
        if rid <= max_id:
            continue
        new_rows.append({k: r.get(k, "") for k in fieldnames})

    if not new_rows:
        print("NhanAZ-Data: no new draws beyond our current max.")
        return 0

    new_rows.sort(key=lambda r: r.get("draw_id", ""))

    with open(DATA_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in new_rows:
            writer.writerow(row)

    print(f"NhanAZ-Data: appended {len(new_rows)} supplementary draw(s).")
    return len(new_rows)


def main():
    if not os.path.exists(DATA_PATH):
        print(f"ERROR: {DATA_PATH} not found. "
              "Restore it from git history or a backup before running fetch_data.",
              file=sys.stderr)
        sys.exit(1)

    total = 0

    # 1. minhchinh.com: chính — ~15 kỳ gần nhất có giờ quay
    mc = _fetch_minhchinh()
    if mc:
        total += _append_draws(mc, "minhchinh_com_scraper")

    # 2. vietlott.vn: phụ 1 — kỳ mới nhất với draw_id chính thức
    vl = _fetch_vietlott()
    if vl:
        total += _append_draws(vl, "vietlott_vn_official")

    # 3. NhanAZ-Data: phụ 2 — bù khoảng trống mà 2 nguồn trên chưa phủ
    nz = _fetch_nhanaz()
    if nz:
        total += _append_nhanaz_supplement(nz)

    if not mc and not vl and not nz:
        print("WARNING: tất cả nguồn lỗi — giữ nguyên data/all.csv. "
              "Pipeline vẫn chạy trên dữ liệu cũ.", file=sys.stderr)

    if total:
        print(f"Tổng kỳ mới bổ sung: {total}")


if __name__ == "__main__":
    main()
