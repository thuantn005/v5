"""
fetch_data.py
-------------
Cập nhật data/all.csv từ NhanAZ-Data (nguồn chính) + fallback scrapers.

Chiến lược:
  1. Tải NhanAZ-Data CSV (raw + CDN) → ghi đè data/all.csv
  2. Nếu kỳ mới nhất trong file < kỳ hôm nay → chạy fallback:
       a. NhanAZ CDN với cache-bust
       b. Vietlott AJAX API
       c. xosominhngoc.net.vn (nếu không bị 403)
  3. Append kỳ mới hơn max hiện tại.

Nếu tất cả thất bại → giữ nguyên file, pipeline chạy trên dữ liệu cũ.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DATA_PATH   = "data/all.csv"
TIMEOUT     = 30
STALE_HOURS = 6

NHANAZ_CSV_URL = (
    "https://raw.githubusercontent.com/"
    "NhanAZ-Data/vietlott-data-research/main/datasets/draws/lotto535/all.csv"
)
NHANAZ_CDN_URL = (
    "https://cdn.jsdelivr.net/gh/"
    "NhanAZ-Data/vietlott-data-research@main/datasets/draws/lotto535/all.csv"
)

XSMN_URL         = "https://xosominhngoc.net.vn/kqxs-lotto-535"
VIETLOTT_BASE    = "https://vietlott.vn"
VIETLOTT_LIST_PATH = "/vi/trung-thuong/ket-qua-trung-thuong/winning-number-535"
VIETLOTT_AJAX_PATH = (
    "/ajaxpro/Vietlott.PlugIn.WebParts.Game535CompareWebPart,"
    "Vietlott.PlugIn.WebParts.ashx"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


# ── Session ──────────────────────────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "vi-VN,vi;q=0.9"})
    return s


# ── Helpers CSV ───────────────────────────────────────────────────────────────

def _count_data_rows(text: str) -> int:
    return max(0, text.strip().count("\n"))


def _load_csv() -> tuple[list[dict], list[str]]:
    if not os.path.exists(DATA_PATH):
        return [], []
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return [], []
    return rows, list(rows[0].keys())


def _max_draw_id(rows: list[dict]) -> int:
    ids = [int(r["draw_id"]) for r in rows if r.get("draw_id", "").isdigit()]
    return max(ids) if ids else 0


# ── Bước 1: NhanAZ (nguồn chính) ────────────────────────────────────────────

def _fetch_nhanaz() -> str | None:
    s = _session()
    ts = int(time.time())  # cache-bust
    urls = [
        ("NhanAZ raw",  NHANAZ_CSV_URL),
        ("NhanAZ CDN",  f"{NHANAZ_CDN_URL}?_={ts}"),
    ]
    for label, url in urls:
        try:
            r = s.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            if "draw_id" in r.text and _count_data_rows(r.text) >= 100:
                n = _count_data_rows(r.text)
                print(f"{label}: OK — {n} kỳ quay")
                return r.text
            print(f"WARNING: {label}: nội dung không hợp lệ", file=sys.stderr)
        except requests.RequestException as e:
            print(f"WARNING: {label} thất bại: {e}", file=sys.stderr)
    return None


# ── Bước 2: Kiểm tra có thiếu kỳ không ─────────────────────────────────────

def _needs_fallback(rows: list[dict]) -> bool:
    """
    True nếu kỳ mới nhất trong all.csv < kỳ hôm nay.
    Hôm nay có 2 kỳ (13:00 và 21:00 VN = 06:00 và 14:00 UTC).
    Luôn thử fallback để không bỏ sót kỳ mới nhất.
    """
    if not rows:
        return True
    max_id = _max_draw_id(rows)
    now_utc = datetime.now(timezone.utc)
    now_vn  = now_utc + timedelta(hours=7)
    # Lấy draw_date kỳ mới nhất
    max_row = next((r for r in reversed(rows) if r.get("draw_id","").isdigit()
                    and int(r["draw_id"]) == max_id), None)
    if not max_row:
        return True
    try:
        last_date = datetime.strptime(max_row["draw_date"], "%Y-%m-%d").date()
    except ValueError:
        return True
    today_vn = now_vn.date()
    if last_date < today_vn:
        print(f"Kỳ mới nhất #{max_id} ngày {last_date} < hôm nay {today_vn} → cần fallback")
        return True
    # Cùng ngày nhưng chưa tới 21:00 VN (14:00 UTC): chỉ có kỳ 13:00, thử lấy kỳ 21:00
    hour_utc = now_utc.hour
    if hour_utc >= 14:   # sau 21:00 VN
        print(f"Sau 21:00 VN, kiểm tra kỳ 21:00 hôm nay...")
        return True
    print(f"NhanAZ đủ mới (kỳ #{max_id} ngày {last_date})")
    return False


# ── Bước 3: Fallback scrapers ────────────────────────────────────────────────

def _fetch_nhanaz_bust() -> list[dict]:
    """Thử lại NhanAZ với nhiều cache-bust variant để lấy kỳ mới nhất."""
    s = _session()
    results = []
    for i in range(3):
        ts = int(time.time()) + i * 7
        url = f"{NHANAZ_CDN_URL}?v={ts}"
        try:
            r = s.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            if "draw_id" not in r.text:
                continue
            reader = csv.DictReader(io.StringIO(r.text))
            for row in reader:
                if not row.get("draw_id", "").isdigit():
                    continue
                try:
                    res = json.loads(row["result_json"])
                    nums = res.get("numbers", [])
                    sps  = res.get("special_numbers", [0])
                    attr = json.loads(row.get("attributes_json", "{}"))
                    if len(set(nums)) == 5 and all(1 <= n <= 35 for n in nums):
                        results.append({
                            "draw_id":   row["draw_id"],
                            "draw_date": row["draw_date"],
                            "numbers":   nums,
                            "special":   sps[0] if sps else 0,
                            "draw_time": attr.get("draw_time", ""),
                            "data_source": "nhanaz_cdn_bust",
                            "source_url":  url,
                        })
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
            if results:
                # Deduplicate
                seen = {}
                for d in results:
                    seen[d["draw_id"]] = d
                results = list(seen.values())
                print(f"NhanAZ CDN bust: {len(results)} kỳ tổng")
                return results
        except requests.RequestException as e:
            print(f"WARNING: NhanAZ CDN bust #{i}: {e}", file=sys.stderr)
        time.sleep(2)
    return results


def _parse_vietlott_ajax_html(html_content: str) -> list[dict]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html_content, "lxml")
    draws = []
    for row in soup.select("table tr"):
        cells = row.select("td")
        if len(cells) < 3:
            continue
        id_m = re.search(r"(\d+)", cells[0].get_text(strip=True))
        if not id_m:
            continue
        draw_id = id_m.group(1).zfill(5)
        date_m  = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", cells[1].get_text(strip=True))
        if not date_m:
            continue
        try:
            draw_date = datetime.strptime(date_m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        # Lấy tất cả số từ row
        all_nums = []
        for span in row.select("span, div"):
            t = re.sub(r"[^\d]", "", span.get_text(strip=True))
            if t and 1 <= int(t) <= 35:
                all_nums.append(int(t))
        # Lọc duplicates giữ thứ tự
        seen_n, unique = set(), []
        for n in all_nums:
            if n not in seen_n:
                seen_n.add(n); unique.append(n)
        if len(unique) < 6:
            continue
        numbers = sorted(unique[:5])
        special = unique[5]
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if special < 1 or special > 12:
            continue
        draws.append({
            "draw_id":    draw_id,
            "draw_date":  draw_date,
            "numbers":    numbers,
            "special":    special,
            "data_source":"vietlott_vn_ajax",
            "source_url": VIETLOTT_BASE + VIETLOTT_LIST_PATH,
        })
    return draws


def _fetch_vietlott() -> list[dict]:
    s = _session()
    list_url = VIETLOTT_BASE + VIETLOTT_LIST_PATH
    ajax_url = VIETLOTT_BASE + VIETLOTT_AJAX_PATH
    try:
        r = s.get(list_url, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: vietlott.vn list page thất bại: {e}", file=sys.stderr)
        return []

    key_m = re.search(
        r"ServerSideDrawResult\s*\(\s*RenderInfo\s*,\s*'([0-9a-fA-F]+)'", r.text)
    if not key_m:
        print("WARNING: vietlott.vn: không lấy được AJAX key", file=sys.stderr)
        return []

    key = key_m.group(1)
    all_draws: list[dict] = []
    for page in range(5):
        payload = json.dumps({
            "ORenderInfo": {
                "SiteId": "main.frontend.vi", "SiteAlias": "main.frontend.vi",
                "UserAgent": USER_AGENT, "SiteName": "Vietlott",
                "SiteURL": "", "FullURL": list_url,
                "SubDomain": "", "Is498Mobile": False, "GameDrawType": "MATRIX",
            },
            "Key": key, "GameDrawId": "", "ArrayNumbers": [[]], "CheckMulti": False,
            "PageIndex": page,
        })
        try:
            ar = s.post(ajax_url, data=payload, timeout=TIMEOUT, headers={
                "Content-Type": "text/plain; charset=utf-8",
                "X-AjaxPro-Method": "ServerSideDrawResult",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": VIETLOTT_BASE, "Referer": list_url,
            })
            ar.raise_for_status()
            html_content = ar.json().get("value", {}).get("HtmlContent", "")
        except Exception as e:
            print(f"WARNING: vietlott.vn AJAX page {page}: {e}", file=sys.stderr)
            break
        if not html_content:
            break
        draws = _parse_vietlott_ajax_html(html_content)
        if not draws:
            break
        all_draws.extend(draws)
        time.sleep(1)

    if all_draws:
        print(f"vietlott.vn AJAX: {len(all_draws)} kỳ quay")
    else:
        print("WARNING: vietlott.vn AJAX: không parse được kỳ nào", file=sys.stderr)
    return all_draws


def _fetch_xosominhngoc() -> list[dict]:
    """Thử xosominhngoc — nếu 403 thì bỏ qua yên lặng."""
    try:
        r = _session().get(XSMN_URL, timeout=TIMEOUT)
        if r.status_code == 403:
            print("xosominhngoc.net.vn: 403 Forbidden — bỏ qua")
            return []
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: xosominhngoc.net.vn: {e}", file=sys.stderr)
        return []

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    from bs4 import BeautifulSoup
    soup  = BeautifulSoup(r.text, "lxml")
    draws = []
    for article in (soup.select("article.xslotto535") or soup.select("article")):
        kyve = article.select_one(".kyve")
        ngay = article.select_one(".ngay")
        if not kyve or not ngay:
            continue
        id_m   = re.search(r"#(\d+)", kyve.get_text())
        date_m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", ngay.get_text())
        if not id_m or not date_m:
            continue
        try:
            draw_date = datetime.strptime(date_m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        nums = []
        for span in article.select("span.kq"):
            t = re.sub(r"[^\d]", "", span.get_text(strip=True))
            if t:
                nums.append(int(t))
        if len(nums) < 6:
            continue
        numbers = sorted(nums[:5]); special = nums[5]
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if special < 1 or special > 12:
            continue
        draws.append({
            "draw_id":    id_m.group(1).zfill(5),
            "draw_date":  draw_date,
            "numbers":    numbers,
            "special":    special,
            "data_source":"xosominhngoc_scraper",
            "source_url": XSMN_URL,
        })
    if draws:
        print(f"xosominhngoc.net.vn: {len(draws)} kỳ quay")
    return draws


# ── Bước 4: Append kỳ mới vào CSV ───────────────────────────────────────────

def _append_scraped(scraped: list[dict]) -> int:
    rows, fieldnames = _load_csv()
    if not fieldnames:
        print("ERROR: data/all.csv không có fieldnames", file=sys.stderr)
        return 0

    current_max = _max_draw_id(rows)
    id_width    = len(rows[0]["draw_id"]) if rows else 5

    candidates = []
    for d in scraped:
        try:
            did = int(d["draw_id"])
        except (ValueError, KeyError):
            continue
        if did <= current_max:
            continue
        numbers = d.get("numbers", [])
        special = d.get("special", 0)
        if (len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers)
                or special < 1 or special > 12):
            continue
        candidates.append((did, d))

    if not candidates:
        print(f"Fallback: không có kỳ mới hơn #{current_max} — NhanAZ đã đủ.")
        return 0

    candidates.sort(key=lambda x: x[0])
    now_iso  = datetime.now(timezone.utc).isoformat()
    new_rows = []
    for did, d in candidates:
        row = {
            "product":       "lotto535",
            "draw_id":       str(did).zfill(id_width),
            "draw_date":     d["draw_date"],
            "draw_status":   "confirmed",
            "result_json":   json.dumps({
                "numbers": sorted(d["numbers"]),
                "special_numbers": [d["special"]],
            }),
            "attributes_json": json.dumps({
                "data_source": d.get("data_source", "scraper"),
                "draw_time":   d.get("draw_time") or ("13:00" if did % 2 == 1 else "21:00"),
            }),
            "official_pdf_urls_json": "[]",
            "source_url":            d.get("source_url", ""),
            "prize_status":          "unknown",
            "validation_status":     "scraped",
            "validation_warnings_json": json.dumps([
                f"scraped from {d.get('data_source', 'scraper')}"]),
            "fetched_at": now_iso,
        }
        new_rows.append({k: row.get(k, "") for k in fieldnames})

    with open(DATA_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in new_rows:
            writer.writerow(row)

    ids_added = [str(did).zfill(id_width) for did, _ in candidates]
    print(f"Fallback: append {len(new_rows)} kỳ mới: {ids_added}")
    return len(new_rows)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(os.path.dirname(DATA_PATH) if os.path.dirname(DATA_PATH) else ".", exist_ok=True)

    # 1. Tải NhanAZ (ghi đè toàn bộ)
    csv_text = _fetch_nhanaz()
    if csv_text is None:
        if os.path.exists(DATA_PATH):
            print("WARNING: NhanAZ thất bại — giữ nguyên data/all.csv.", file=sys.stderr)
        else:
            print("ERROR: NhanAZ thất bại và không có data/all.csv.", file=sys.stderr)
            sys.exit(1)
    else:
        with open(DATA_PATH, "w", encoding="utf-8", newline="") as f:
            f.write(csv_text)
        print(f"data/all.csv cập nhật: {_count_data_rows(csv_text)} kỳ")

    # 2. Kiểm tra cần fallback không
    rows, _ = _load_csv()
    if not _needs_fallback(rows):
        return

    # 3. Chạy fallback theo thứ tự ưu tiên
    print("\n=== Fallback scrapers ===")
    scraped: list[dict] = []

    # 3a. NhanAZ CDN với cache-bust (thường bắt được kỳ mới nhất)
    scraped = _fetch_nhanaz_bust()

    # 3b. Vietlott AJAX
    if not scraped or _max_draw_id(rows) >= max((int(d["draw_id"]) for d in scraped), default=0):
        vl = _fetch_vietlott()
        if vl:
            scraped = vl

    # 3c. xosominhngoc (nếu chưa có gì)
    if not scraped:
        scraped = _fetch_xosominhngoc()

    if scraped:
        _append_scraped(scraped)
    else:
        print("Tất cả fallback thất bại — pipeline chạy trên dữ liệu NhanAZ hiện tại.")


if __name__ == "__main__":
    main()
