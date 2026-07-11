"""
fetch_data.py
-------------
Cập nhật data/all.csv với kết quả kỳ quay mới từ nhiều nguồn độc lập.
Chỉ THÊM kỳ mới (không ghi đè), an toàn khi chạy nhiều lần.

Thứ tự nguồn:
  1.  minhchinh.com            — chính, ~15 kỳ gần nhất, có giờ quay (13:00/21:00)
  2.  xosominhngoc.net.vn      — phụ, trang tổng hợp Lotto 5/35 (BeautifulSoup)
  3.  vietlott.vn              — phụ, AJAX API chính thức
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
import time
from datetime import datetime, timezone
from itertools import groupby

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DATA_PATH = "data/all.csv"
TIMEOUT = 25

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent": _USER_AGENT, "Accept-Language": "vi-VN,vi;q=0.9"})
    return s


_TAG_RE = re.compile(r"<[^>]+>")


def _strip(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    return re.sub(r"\s+", " ", text)


# ── Source 1: minhchinh.com ───────────────────────────────────────────────────
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
        r = _make_session().get(_MC_URL, timeout=TIMEOUT)
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


# ── Source 2: xosominhngoc.net.vn ────────────────────────────────────────────
_MN_URL = "https://xosominhngoc.net.vn/kqxs-lotto-535"


def _parse_minhngoc(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []

    articles = soup.select("article.xslotto535")
    if not articles:
        articles = soup.select("article")

    for article in articles:
        kyve = article.select_one(".kyve")
        if not kyve:
            continue
        id_match = re.search(r"#(\d+)", kyve.get_text())
        if not id_match:
            continue
        draw_id = id_match.group(1).zfill(5)

        ngay = article.select_one(".ngay")
        if not ngay:
            continue
        date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", ngay.get_text())
        if not date_match:
            continue
        try:
            dt = datetime.strptime(date_match.group(1), "%d/%m/%Y")
            draw_date = dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

        kq_spans = article.select("span.kq")
        nums = []
        for span in kq_spans:
            txt = re.sub(r"[^\d]", "", span.get_text(strip=True))
            if txt:
                nums.append(int(txt))

        if len(nums) < 6:
            continue

        numbers = sorted(nums[:5])
        sp = nums[5]

        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if sp < 1 or sp > 12:
            continue

        rows.append({"draw_date": draw_date, "draw_time": None,
                     "numbers": numbers, "special": sp,
                     "source_url": _MN_URL, "draw_id_hint": draw_id})
    return rows


def _fetch_minhngoc() -> list[dict]:
    try:
        r = _make_session().get(_MN_URL, timeout=TIMEOUT)
        r.raise_for_status()
        rows = _parse_minhngoc(r.text)
        if rows:
            print(f"xosominhngoc.net.vn: {len(rows)} recent draw(s) found")
        else:
            print("WARNING: xosominhngoc.net.vn: page fetched but no draws parsed "
                  "(check CSS selectors: article.xslotto535, .kyve, .ngay, span.kq)",
                  file=sys.stderr)
        return rows
    except requests.RequestException as e:
        print(f"WARNING: xosominhngoc.net.vn fetch failed: {e}", file=sys.stderr)
        return []


# ── Source 3: vietlott.vn (AJAX API) ─────────────────────────────────────────
_VL_BASE = "https://vietlott.vn"
_VL_LIST_PATH = "/vi/trung-thuong/ket-qua-trung-thuong/winning-number-535"
_VL_AJAX_PATH = (
    "/ajaxpro/Vietlott.PlugIn.WebParts.Game535CompareWebPart,"
    "Vietlott.PlugIn.WebParts.ashx"
)


def _parse_vietlott_ajax_html(html_content: str) -> list[dict]:
    soup = BeautifulSoup(html_content, "lxml")
    rows: list[dict] = []

    for row in soup.select("table tr"):
        cells = row.select("td")
        if len(cells) < 3:
            continue

        id_text = cells[0].get_text(strip=True)
        id_match = re.search(r"(\d+)", id_text)
        if not id_match:
            continue
        draw_id = id_match.group(1).zfill(5)

        date_text = cells[1].get_text(strip=True)
        date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", date_text)
        if not date_match:
            continue
        try:
            dt = datetime.strptime(date_match.group(1), "%d/%m/%Y")
            draw_date = dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

        num_spans = row.select("span.ball, span.number, div.ball, .bong_so")
        if not num_spans:
            num_spans = row.select("span")

        nums = []
        for span in num_spans:
            txt = re.sub(r"[^\d]", "", span.get_text(strip=True))
            if txt and 1 <= int(txt) <= 35:
                nums.append(int(txt))

        if len(nums) < 5:
            continue

        numbers = sorted(nums[:5])
        sp = nums[5] if len(nums) > 5 else 0

        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if sp and (sp < 1 or sp > 12):
            continue

        rows.append({"draw_date": draw_date, "draw_time": None,
                     "numbers": numbers, "special": sp,
                     "source_url": _VL_BASE + _VL_LIST_PATH,
                     "draw_id_hint": draw_id})
    return rows


def _fetch_vietlott() -> list[dict]:
    s = _make_session()
    list_url = _VL_BASE + _VL_LIST_PATH
    ajax_url = _VL_BASE + _VL_AJAX_PATH

    print("Bootstrapping Vietlott AJAX key...")
    try:
        resp = s.get(list_url, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: vietlott.vn list page failed: {e}", file=sys.stderr)
        return []

    key_match = re.search(
        r"ServerSideDrawResult\s*\(\s*RenderInfo\s*,\s*'([0-9a-fA-F]+)'",
        resp.text,
    )
    if not key_match:
        print("WARNING: vietlott.vn: could not extract AJAX key "
              "(page layout may have changed)", file=sys.stderr)
        return []

    key = key_match.group(1)
    print(f"Got Vietlott AJAX key: {key}")

    all_draws: list[dict] = []
    for page in range(5):
        payload = json.dumps({
            "ORenderInfo": {
                "SiteId": "main.frontend.vi",
                "SiteAlias": "main.frontend.vi",
                "UserAgent": _USER_AGENT,
                "SiteName": "Vietlott",
                "SiteURL": "",
                "FullURL": list_url,
                "SubDomain": "",
                "Is498Mobile": False,
                "GameDrawType": "MATRIX",
            },
            "Key": key,
            "GameDrawId": "",
            "ArrayNumbers": [[]],
            "CheckMulti": False,
            "PageIndex": page,
        })
        try:
            resp = s.post(
                ajax_url,
                data=payload,
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "X-AjaxPro-Method": "ServerSideDrawResult",
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": _VL_BASE,
                    "Referer": list_url,
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"WARNING: vietlott.vn AJAX page {page} failed: {e}", file=sys.stderr)
            break

        try:
            data = resp.json()
            html_content = data.get("value", {}).get("HtmlContent", "")
        except (json.JSONDecodeError, AttributeError):
            print(f"WARNING: vietlott.vn: invalid JSON on page {page}", file=sys.stderr)
            break

        if not html_content:
            break

        draws = _parse_vietlott_ajax_html(html_content)
        if not draws:
            break

        all_draws.extend(draws)
        time.sleep(1)

    print(f"vietlott.vn: {len(all_draws)} draw(s) found via AJAX")
    return all_draws


# ── CSV helpers ──────────────────────────────────────────────────────────────

def _load_csv() -> tuple[list[dict], list[str] | None]:
    try:
        with open(DATA_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return rows, list(rows[0].keys()) if rows else None
    except FileNotFoundError:
        return [], None


def _existing_keys(rows: list[dict]) -> set[tuple]:
    keys = set()
    for r in rows:
        try:
            attrs = json.loads(r.get("attributes_json") or "{}")
            keys.add((r["draw_date"], attrs.get("draw_time")))
        except (ValueError, json.JSONDecodeError):
            continue
    return keys


def _max_draw_id(rows: list[dict]) -> tuple[int, int]:
    ids = [r["draw_id"] for r in rows if r.get("draw_id", "").isdigit()]
    if not ids:
        return 0, 5
    return max(int(i) for i in ids), len(ids[0])


def _infer_time(draw_date: str, existing_keys: set[tuple]) -> str:
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
        "validation_warnings_json": json.dumps([f"scraped from {data_source}"]),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    return {k: row.get(k, "") for k in fieldnames}


def _append_draws(scraped: list[dict], data_source: str) -> int:
    existing_rows, fieldnames = _load_csv()
    if fieldnames is None:
        print(f"ERROR: {DATA_PATH} is empty or missing — cannot append.",
              file=sys.stderr)
        return 0

    existing_k = _existing_keys(existing_rows)
    max_id, width = _max_draw_id(existing_rows)

    scraped.sort(key=lambda d: (d["draw_date"], d.get("draw_time") or ""))

    new_rows = []
    running_max = max_id
    for draw in scraped:
        if draw["draw_time"] is None:
            draw["draw_time"] = _infer_time(draw["draw_date"], existing_k)
        key = (draw["draw_date"], draw["draw_time"])
        if key in existing_k:
            continue

        hint = draw.get("draw_id_hint")
        if hint and str(hint).isdigit():
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


# ── Source 4: NhanAZ-Data (supplementary) ────────────────────────────────────
_NHANAZ_URLS = [
    "https://raw.githubusercontent.com/NhanAZ-Data/vietlott-data-research"
    "/main/datasets/draws/lotto535/all.csv",
]


def _fetch_nhanaz() -> list[dict]:
    for url in _NHANAZ_URLS:
        try:
            r = _make_session().get(url, timeout=TIMEOUT)
            r.raise_for_status()
            rows = list(csv.DictReader(r.text.splitlines()))
            if rows:
                print(f"NhanAZ-Data: downloaded {len(rows)} total rows from {url}")
                return rows
        except requests.RequestException as e:
            print(f"WARNING: NhanAZ-Data {url} failed: {e}", file=sys.stderr)
    return []


def _append_nhanaz_supplement(nhanaz_rows: list[dict]) -> int:
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
_VD_URL = (
    "https://raw.githubusercontent.com/vietvudanh/vietlott-data"
    "/main/data/power535.jsonl"
)


def _fetch_vietvudanh() -> list[dict]:
    try:
        r = _make_session().get(_VD_URL, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: vietvudanh/vietlott-data fetch failed: {e}", file=sys.stderr)
        return []

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
        r = _make_session().get(url, timeout=TIMEOUT)
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

    # 1. minhchinh.com
    mc = _fetch_minhchinh()
    if mc:
        total += _append_draws(mc, "minhchinh_com_scraper")

    # 2. xosominhngoc.net.vn (BeautifulSoup + CSS selectors)
    mn = _fetch_minhngoc()
    if mn:
        total += _append_draws(mn, "xosominhngoc_scraper")

    # 3. vietlott.vn (AJAX API)
    vl = _fetch_vietlott()
    if vl:
        total += _append_draws(vl, "vietlott_vn_official")

    # 4. vietvudanh/vietlott-data
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
