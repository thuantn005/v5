"""
fetch_data.py
-------------
Cập nhật data/all.csv với kết quả kỳ quay mới từ nhiều nguồn độc lập.
Chỉ THÊM kỳ mới (không ghi đè), an toàn khi chạy nhiều lần.

Thứ tự nguồn:
  1.  minhchinh.com            — chính, ~15 kỳ gần nhất, có giờ quay (13:00/21:00)
  2.  xosominhngoc.net.vn      — phụ, trang tổng hợp Lotto 5/35
  3.  vietlott.vn              — phụ, kỳ mới nhất với draw_id chính thức
  4.  vietvudanh/vietlott-data — phụ, GitHub repo cào tự động hàng ngày
  5.  xskt.com.vn              — phụ, tổng hợp 30 kỳ gần nhất
  6.  xsmn.net                 — phụ, tổng hợp kết quả miền Nam
  7.  xsmn.mobi                — phụ, bản mobile
  8.  onbit.vn                 — phụ, cập nhật sau mỗi kỳ quay
  9.  ketquadientoan.com        — phụ, kết quả điện toán Vietlott
  10. NhanAZ-Data              — phụ cuối, dataset GitHub; bù khoảng trống còn lại

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


# ── Source 3: vietlott.vn ────────────────────────────────────────────────────
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


# ── Source 2: xosominhngoc.net.vn ────────────────────────────────────────────
# Results aggregator for Lotto 5/35. The page renders draw results with a
# date (dd/mm/yyyy), optional draw-time, 5 main numbers and 1 special number.
#
# Three layout patterns are tried in order (most→least specific):
#   A) dd/mm/yyyy  Xh  ...  <10-digit-concat>  <2-digit-special>  (inline time)
#   B) dd/mm/yyyy  ...  <10-digit-concat>  <2-digit-special>       (no inline time)
#   C) dd/mm/yyyy  ...  N1 N2 N3 N4 N5  ...  SP                    (5 separate nums)
#
# If the site changes its layout, update the regex here and verify with:
#   python - <<'EOF'
#   import requests, re, sys
#   sys.path.insert(0,"scripts"); from fetch_data import _fetch_minhngoc, _parse_minhngoc
#   r = requests.get("https://xosominhngoc.net.vn/kqxs-lotto-535", timeout=25)
#   print(_parse_minhngoc(r.text))
#   EOF
_MN_URL = "https://xosominhngoc.net.vn/kqxs-lotto-535"

# Pattern A: 4-digit year + inline hour → groups (dd, mm, yyyy, hh, digits10, sp)
_MN_RE_A = re.compile(
    r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2})h.{0,250}?(?<!\d)(\d{10})(?!\d)\s*(\d{2})(?!\d)",
    re.DOTALL,
)
# Pattern B: 4-digit year, no inline hour → groups (dd, mm, yyyy, digits10, sp)
_MN_RE_B = re.compile(
    r"(\d{2})/(\d{2})/(\d{4}).{0,250}?(?<!\d)(\d{10})(?!\d)\s*(\d{2})(?!\d)",
    re.DOTALL,
)
# Pattern C: 5 separate 2-digit main numbers then a ≤2-digit special
# Anchored by date; numbers must be space-separated; special follows within 80 chars
_MN_RE_C = re.compile(
    r"(\d{2})/(\d{2})/(\d{4}).{0,150}?"
    r"(?<!\d)(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})(?!\d)"
    r".{0,80}?(?<!\d)(\d{1,2})(?!\d)",
    re.DOTALL,
)


def _parse_minhngoc(html: str) -> list[dict]:
    text = _strip(html)
    rows: list[dict] = []

    # Try pattern A first (has inline hour → best time accuracy)
    for m in _MN_RE_A.finditer(text):
        dd, mm, yyyy, hh, digits10, sp_str = m.groups()
        draw_date = f"{yyyy}-{mm}-{dd}"
        draw_time = "21:00" if int(hh) >= 20 else "13:00"
        numbers = sorted(int(digits10[i:i + 2]) for i in range(0, 10, 2))
        sp = int(sp_str)
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if sp < 1 or sp > 12:
            continue
        rows.append({"draw_date": draw_date, "draw_time": draw_time,
                     "numbers": numbers, "special": sp,
                     "source_url": _MN_URL, "draw_id_hint": None})
    if rows:
        return rows

    # Pattern B: no inline hour (time will be inferred later)
    for m in _MN_RE_B.finditer(text):
        dd, mm, yyyy, digits10, sp_str = m.groups()
        draw_date = f"{yyyy}-{mm}-{dd}"
        numbers = sorted(int(digits10[i:i + 2]) for i in range(0, 10, 2))
        sp = int(sp_str)
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if sp < 1 or sp > 12:
            continue
        rows.append({"draw_date": draw_date, "draw_time": None,
                     "numbers": numbers, "special": sp,
                     "source_url": _MN_URL, "draw_id_hint": None})
    if rows:
        return rows

    # Pattern C: 5 separate numbers
    for m in _MN_RE_C.finditer(text):
        dd, mm, yyyy, n1, n2, n3, n4, n5, sp_str = m.groups()
        draw_date = f"{yyyy}-{mm}-{dd}"
        numbers = sorted(int(x) for x in (n1, n2, n3, n4, n5))
        sp = int(sp_str)
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if sp < 1 or sp > 12:
            continue
        rows.append({"draw_date": draw_date, "draw_time": None,
                     "numbers": numbers, "special": sp,
                     "source_url": _MN_URL, "draw_id_hint": None})
    return rows


def _fetch_minhngoc() -> list[dict]:
    try:
        r = requests.get(_MN_URL, timeout=TIMEOUT, headers=_HEADERS)
        r.raise_for_status()
        rows = _parse_minhngoc(r.text)
        if rows:
            print(f"xosominhngoc.net.vn: {len(rows)} recent draw(s) found")
        else:
            print("WARNING: xosominhngoc.net.vn: page fetched but no draws parsed "
                  "(site layout may have changed — check _MN_RE_A/B/C)", file=sys.stderr)
        return rows
    except requests.RequestException as e:
        print(f"WARNING: xosominhngoc.net.vn fetch failed: {e}", file=sys.stderr)
        return []


# ── Source 4: NhanAZ-Data (supplementary) ────────────────────────────────────────────
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


# ── Source 5: vietvudanh/vietlott-data (GitHub, power535.jsonl) ──────────────
# Repo tự động cào vietlott.vn hàng ngày qua GitHub Actions.
# Format: {"date":"YYYY-MM-DD","id":"NNNNN","result":[n1,n2,n3,n4,n5,sp],...}
# result[0:5] = 5 số chính (1-35), result[5] = số đặc biệt (1-12).
# Không có thông tin giờ quay → suy ra từ thứ tự id trong cùng ngày:
#   id nhỏ hơn của ngày → 13:00 ; id lớn hơn → 21:00.
_VD_URL = (
    "https://raw.githubusercontent.com/vietvudanh/vietlott-data"
    "/main/data/power535.jsonl"
)


def _fetch_vietvudanh() -> list[dict]:
    try:
        r = requests.get(_VD_URL, timeout=TIMEOUT, headers=_HEADERS)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: vietvudanh/vietlott-data fetch failed: {e}", file=sys.stderr)
        return []

    # Parse JSONL — collect all valid rows
    raw: list[dict] = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = obj.get("result") or []
        if len(result) != 6:
            continue
        numbers = sorted(result[:5])
        sp = result[5]
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if sp < 1 or sp > 12:
            continue
        raw.append({
            "draw_date": obj["date"],
            "draw_id_hint": obj.get("id"),
            "numbers": numbers,
            "special": sp,
        })

    if not raw:
        print("WARNING: vietvudanh/vietlott-data: fetched but no valid rows parsed",
              file=sys.stderr)
        return []

    # Assign draw time by order within each date (lowest id → 13:00, next → 21:00)
    from itertools import groupby
    raw.sort(key=lambda d: (d["draw_date"], d["draw_id_hint"] or ""))
    rows: list[dict] = []
    for date, group in groupby(raw, key=lambda d: d["draw_date"]):
        entries = list(group)
        times = ["13:00", "21:00"] if len(entries) >= 2 else ["21:00"]
        for i, entry in enumerate(entries[:2]):
            rows.append({
                "draw_date": date,
                "draw_time": times[i] if i < len(times) else "21:00",
                "numbers": entry["numbers"],
                "special": entry["special"],
                "source_url": _VD_URL,
                "draw_id_hint": entry["draw_id_hint"],
            })

    print(f"vietvudanh/vietlott-data: {len(rows)} total draw(s) in dataset")
    return rows


# ── Sources 6-10: web scrapers bổ sung ───────────────────────────────────────
# Các trang tổng hợp kết quả Lotto 5/35. Dùng chung 3 regex pattern:
#   A) dd/mm/yyyy Xh ... <10digits> <2-digit-sp>    (có giờ inline)
#   B) dd/mm/yyyy ...  <10digits> <2-digit-sp>       (không có giờ)
#   C) dd/mm/yyyy ... N1 N2 N3 N4 N5 ... SP          (5 số riêng lẻ)
# HTML không được kiểm tra trực tiếp do proxy session chặn.
# Chạy được trên GitHub Actions.

_EXTRA_SOURCES = [
    ("xskt_com_vn",        "https://xskt.com.vn/xslotto-5-35"),
    ("xsmn_net",           "https://xsmn.net/kqxslotto535"),
    ("xsmn_mobi",          "https://xsmn.mobi/xs-lotto-5-35.html"),
    ("onbit_vn",           "https://onbit.vn/ket-qua-xo-so/vietlott-lotto535"),
    ("ketquadientoan_com", "https://www.ketquadientoan.com/ket-qua-xo-so-dien-toan-lotto-535.html"),
]

_EXTRA_RE_A = re.compile(
    r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2})h.{0,250}?(?<!\d)(\d{10})(?!\d)\s*(\d{2})(?!\d)",
    re.DOTALL,
)
_EXTRA_RE_B = re.compile(
    r"(\d{2})/(\d{2})/(\d{4}).{0,250}?(?<!\d)(\d{10})(?!\d)\s*(\d{2})(?!\d)",
    re.DOTALL,
)
_EXTRA_RE_C = re.compile(
    r"(\d{2})/(\d{2})/(\d{4}).{0,150}?"
    r"(?<!\d)(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})(?!\d)"
    r".{0,80}?(?<!\d)(\d{1,2})(?!\d)",
    re.DOTALL,
)


def _parse_generic(html: str, source_url: str) -> list[dict]:
    text = _strip(html)
    rows: list[dict] = []

    for m in _EXTRA_RE_A.finditer(text):
        dd, mm, yyyy, hh, digits10, sp_str = m.groups()
        draw_date = f"{yyyy}-{mm}-{dd}"
        draw_time = "21:00" if int(hh) >= 20 else "13:00"
        numbers = sorted(int(digits10[i:i + 2]) for i in range(0, 10, 2))
        sp = int(sp_str)
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if sp < 1 or sp > 12:
            continue
        rows.append({"draw_date": draw_date, "draw_time": draw_time,
                     "numbers": numbers, "special": sp,
                     "source_url": source_url, "draw_id_hint": None})
    if rows:
        return rows

    for m in _EXTRA_RE_B.finditer(text):
        dd, mm, yyyy, digits10, sp_str = m.groups()
        draw_date = f"{yyyy}-{mm}-{dd}"
        numbers = sorted(int(digits10[i:i + 2]) for i in range(0, 10, 2))
        sp = int(sp_str)
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if sp < 1 or sp > 12:
            continue
        rows.append({"draw_date": draw_date, "draw_time": None,
                     "numbers": numbers, "special": sp,
                     "source_url": source_url, "draw_id_hint": None})
    if rows:
        return rows

    for m in _EXTRA_RE_C.finditer(text):
        dd, mm, yyyy, n1, n2, n3, n4, n5, sp_str = m.groups()
        draw_date = f"{yyyy}-{mm}-{dd}"
        numbers = sorted(int(x) for x in (n1, n2, n3, n4, n5))
        sp = int(sp_str)
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if sp < 1 or sp > 12:
            continue
        rows.append({"draw_date": draw_date, "draw_time": None,
                     "numbers": numbers, "special": sp,
                     "source_url": source_url, "draw_id_hint": None})
    return rows


def _fetch_extra(key: str, url: str) -> list[dict]:
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=_HEADERS)
        r.raise_for_status()
        rows = _parse_generic(r.text, url)
        if rows:
            print(f"{key}: {len(rows)} draw(s) found")
        else:
            print(f"WARNING: {key}: fetched but no draws parsed "
                  f"(check _EXTRA_RE_A/B/C for this site's layout)", file=sys.stderr)
        return rows
    except requests.RequestException as e:
        print(f"WARNING: {key} ({url}) fetch failed: {e}", file=sys.stderr)
        return []


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

    # 2. xosominhngoc.net.vn: phụ 1 — trang tổng hợp kết quả Lotto 5/35
    mn = _fetch_minhngoc()
    if mn:
        total += _append_draws(mn, "xosominhngoc_scraper")

    # 3. vietlott.vn: phụ 2 — kỳ mới nhất với draw_id chính thức
    vl = _fetch_vietlott()
    if vl:
        total += _append_draws(vl, "vietlott_vn_official")

    # 4. vietvudanh/vietlott-data: phụ 3 — repo GitHub cào tự động hàng ngày
    vd = _fetch_vietvudanh()
    if vd:
        total += _append_draws(vd, "vietvudanh_github")

    # 5-9. Các nguồn web scraper bổ sung
    for key, url in _EXTRA_SOURCES:
        ex = _fetch_extra(key, url)
        if ex:
            total += _append_draws(ex, key)

    # 10. NhanAZ-Data: bù khoảng trống cuối cùng
    nz = _fetch_nhanaz()
    if nz:
        total += _append_nhanaz_supplement(nz)

    if not mc and not mn and not vl and not vd and not nz:
        print("WARNING: tất cả nguồn lỗi — giữ nguyên data/all.csv. "
              "Pipeline vẫn chạy trên dữ liệu cũ.", file=sys.stderr)

    if total:
        print(f"Tổng kỳ mới bổ sung: {total}")


if __name__ == "__main__":
    main()
