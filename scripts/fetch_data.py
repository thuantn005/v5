"""
fetch_data.py
-------------
Cập nhật data/all.csv từ NhanAZ-Data (nguồn chính) + scraper live (fallback).

Chiến lược:
  1. Tải NhanAZ-Data CSV  → ghi đè toàn bộ data/all.csv (sạch, có lịch sử đầy đủ)
  2. Xác định draw_id mới nhất trong file vừa tải
  3. Nếu kỳ mới nhất đó > 6 giờ trước giờ hiện tại → NhanAZ chưa cập nhật,
     chạy fallback scraper để bổ sung kỳ vừa quay:
       a. xosominhngoc.net.vn (CSS selector .kyve / .ngay / span.kq)
       b. Vietlott AJAX API (AJAX key + HtmlContent)
     Chỉ APPEND kỳ có draw_id mới hơn max hiện tại.

Nếu tất cả thất bại → giữ nguyên file, pipeline vẫn chạy trên dữ liệu cũ.
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

DATA_PATH = "data/all.csv"
TIMEOUT = 30
STALE_HOURS = 6  # Coi NhanAZ là "chậm" nếu kỳ mới nhất > 6h trước

NHANAZ_CSV_URL = (
    "https://raw.githubusercontent.com/"
    "NhanAZ-Data/vietlott-data-research/main/datasets/draws/lotto535/all.csv"
)
NHANAZ_CDN_URL = (
    "https://cdn.jsdelivr.net/gh/"
    "NhanAZ-Data/vietlott-data-research@main/datasets/draws/lotto535/all.csv"
)

XSMN_URL = "https://xosominhngoc.net.vn/kqxs-lotto-535"
VIETLOTT_BASE = "https://vietlott.vn"
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


# ── Bước 1: NhanAZ (nguồn chính) ────────────────────────────────────────────

def _count_data_rows(text: str) -> int:
    return max(0, text.strip().count("\n"))


def _fetch_nhanaz() -> str | None:
    s = _session()
    for label, url in [("NhanAZ raw", NHANAZ_CSV_URL), ("NhanAZ CDN", NHANAZ_CDN_URL)]:
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


# ── Helpers CSV (dùng cho cả đọc và ghi) ────────────────────────────────────

def _load_csv() -> tuple[list[dict], list[str]]:
    """Trả về (rows, fieldnames). Rows rỗng nếu file không tồn tại."""
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


def _latest_fetched_at(rows: list[dict]) -> datetime | None:
    """Thời điểm fetched_at của kỳ có draw_id lớn nhất (để đánh giá NhanAZ có chậm không)."""
    best_id, best_dt = -1, None
    for r in rows:
        if not r.get("draw_id", "").isdigit():
            continue
        rid = int(r["draw_id"])
        try:
            dt = datetime.fromisoformat(r.get("fetched_at", ""))
        except (ValueError, TypeError):
            continue
        if rid > best_id:
            best_id, best_dt = rid, dt
    return best_dt


# ── Bước 2: Kiểm tra NhanAZ có chậm không ──────────────────────────────────

def _nhanaz_is_stale(rows: list[dict]) -> bool:
    """True nếu kỳ mới nhất của NhanAZ được fetch > STALE_HOURS giờ trước."""
    now = datetime.now(timezone.utc)
    # Lấy draw_date của kỳ lớn nhất để ước tính
    max_id = _max_draw_id(rows)
    if max_id == 0:
        return True
    # Cách đơn giản hơn: so sánh draw_date của kỳ mới nhất với ngày hiện tại
    max_rows = [r for r in rows if r.get("draw_id", "") == str(max_id).zfill(5)]
    if not max_rows:
        return True
    last_draw_date_str = max_rows[0].get("draw_date", "")
    try:
        last_draw_date = datetime.strptime(last_draw_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    # Nếu ngày kỳ cuối < hôm nay (giờ VN = UTC+7) → có thể đã có kỳ mới chưa được đưa vào
    today_vn = (now + timedelta(hours=7)).date()
    last_date_vn = (last_draw_date + timedelta(hours=7)).date()
    if last_date_vn < today_vn:
        print(f"NhanAZ: kỳ mới nhất là {last_draw_date_str} ({max_id}), hôm nay {today_vn} → kiểm tra kỳ mới...")
        return True
    # Nếu cùng ngày: kiểm tra giờ (13:00 và 21:00 VN)
    hour_vn = (now + timedelta(hours=7)).hour
    # Sau 21:30 VN mà kỳ cuối là 13:00 → có thể còn kỳ 21:00 chưa vào
    # Ta dùng heuristic đơn giản: luôn thử fallback nếu ngày cuối = hôm nay
    # vì overhead nhỏ, lợi ích rõ ràng
    print(f"NhanAZ: kỳ mới nhất là ngày hôm nay ({last_draw_date_str}), kiểm tra thêm kỳ mới nhất...")
    return True


# ── Bước 3a: xosominhngoc (fallback chính) ──────────────────────────────────

def _parse_xosominhngoc(html: str) -> list[dict]:
    """Parse xosominhngoc.net.vn — CSS selector .kyve / .ngay / span.kq (từ V51)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "lxml")
    draws = []

    articles = soup.select("article.xslotto535") or soup.select("article")
    for article in articles:
        # draw_id
        kyve = article.select_one(".kyve")
        if not kyve:
            continue
        id_m = re.search(r"#(\d+)", kyve.get_text())
        if not id_m:
            continue
        draw_id = id_m.group(1).zfill(5)

        # draw_date
        ngay = article.select_one(".ngay")
        if not ngay:
            continue
        date_m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", ngay.get_text())
        if not date_m:
            continue
        try:
            draw_date = datetime.strptime(date_m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue

        # numbers
        nums = []
        for span in article.select("span.kq"):
            txt = re.sub(r"[^\d]", "", span.get_text(strip=True))
            if txt:
                nums.append(int(txt))
        if len(nums) < 6:
            continue

        numbers = sorted(nums[:5])
        special = nums[5]
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if special < 1 or special > 12:
            continue

        draws.append({
            "draw_id": draw_id,
            "draw_date": draw_date,
            "numbers": numbers,
            "special": special,
            "source_url": XSMN_URL,
            "data_source": "xosominhngoc_scraper",
        })

    return draws


def _fetch_xosominhngoc() -> list[dict]:
    try:
        r = _session().get(XSMN_URL, timeout=TIMEOUT)
        r.raise_for_status()
        draws = _parse_xosominhngoc(r.text)
        if draws:
            print(f"xosominhngoc.net.vn: {len(draws)} kỳ quay")
        else:
            print("WARNING: xosominhngoc.net.vn: không parse được kỳ nào", file=sys.stderr)
        return draws
    except requests.RequestException as e:
        print(f"WARNING: xosominhngoc.net.vn thất bại: {e}", file=sys.stderr)
        return []


# ── Bước 3b: Vietlott AJAX (fallback phụ) ───────────────────────────────────

def _parse_vietlott_ajax_html(html_content: str) -> list[dict]:
    """Parse HtmlContent từ Vietlott AJAX (từ V51)."""
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
        date_m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", cells[1].get_text(strip=True))
        if not date_m:
            continue
        try:
            draw_date = datetime.strptime(date_m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        spans = row.select("span.ball, span.number, div.ball, .bong_so") or row.select("span")
        nums = [int(re.sub(r"[^\d]", "", s.get_text(strip=True)))
                for s in spans
                if re.sub(r"[^\d]", "", s.get_text(strip=True))
                and 1 <= int(re.sub(r"[^\d]", "", s.get_text(strip=True))) <= 35]
        if len(nums) < 5:
            continue
        numbers = sorted(nums[:5])
        special = nums[5] if len(nums) > 5 else 0
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if special and (special < 1 or special > 12):
            continue
        draws.append({
            "draw_id": draw_id,
            "draw_date": draw_date,
            "numbers": numbers,
            "special": special,
            "source_url": VIETLOTT_BASE + VIETLOTT_LIST_PATH,
            "data_source": "vietlott_vn_ajax",
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

    key_m = re.search(r"ServerSideDrawResult\s*\(\s*RenderInfo\s*,\s*'([0-9a-fA-F]+)'", r.text)
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
            print(f"WARNING: vietlott.vn AJAX page {page} thất bại: {e}", file=sys.stderr)
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


# ── Bước 4: Append kỳ mới từ scraper vào CSV ────────────────────────────────

def _append_scraped(scraped: list[dict]) -> int:
    """Chỉ append kỳ có draw_id lớn hơn max hiện tại (không trùng, không rác)."""
    rows, fieldnames = _load_csv()
    if not fieldnames:
        print("ERROR: data/all.csv không có fieldnames — không thể append", file=sys.stderr)
        return 0

    current_max = _max_draw_id(rows)
    id_width = len(rows[0]["draw_id"]) if rows else 5

    # Lọc: chỉ kỳ có draw_id > current_max và hợp lệ
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
        print("Fallback scraper: không có kỳ mới hơn (NhanAZ đã cập nhật).")
        return 0

    candidates.sort(key=lambda x: x[0])
    now_iso = datetime.now(timezone.utc).isoformat()
    new_rows = []
    for did, d in candidates:
        row = {
            "product": "lotto535",
            "draw_id": str(did).zfill(id_width),
            "draw_date": d["draw_date"],
            "draw_status": "confirmed",
            "result_json": json.dumps({
                "numbers": sorted(d["numbers"]),
                "special_numbers": [d["special"]],
            }),
            "attributes_json": json.dumps({
                "data_source": d.get("data_source", "scraper"),
                # Infer draw_time from draw_id parity if scraper did not supply it.
                # Lotto 5/35: odd draw_id = 13:00, even draw_id = 21:00.
                "draw_time": d.get("draw_time") or ("13:00" if did % 2 == 1 else "21:00"),
            }),
            "official_pdf_urls_json": "[]",
            "source_url": d.get("source_url", ""),
            "prize_status": "unknown",
            "validation_status": "scraped",
            "validation_warnings_json": json.dumps([f"scraped from {d.get('data_source', 'scraper')}"]),
            "fetched_at": now_iso,
        }
        new_rows.append({k: row.get(k, "") for k in fieldnames})

    with open(DATA_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in new_rows:
            writer.writerow(row)

    ids_added = [str(did).zfill(id_width) for did, _ in candidates]
    print(f"Fallback scraper: append {len(new_rows)} kỳ mới: {ids_added}")
    return len(new_rows)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(os.path.dirname(DATA_PATH) if os.path.dirname(DATA_PATH) else ".", exist_ok=True)

    # 1. Tải NhanAZ (ghi đè)
    csv_text = _fetch_nhanaz()
    if csv_text is None:
        if os.path.exists(DATA_PATH):
            print("WARNING: NhanAZ thất bại — giữ nguyên data/all.csv.", file=sys.stderr)
        else:
            print("ERROR: NhanAZ thất bại và data/all.csv không tồn tại.", file=sys.stderr)
            sys.exit(1)
    else:
        with open(DATA_PATH, "w", encoding="utf-8", newline="") as f:
            f.write(csv_text)
        print(f"data/all.csv đã cập nhật: {_count_data_rows(csv_text)} kỳ quay")

    # 2. Kiểm tra có kỳ mới hơn NhanAZ không
    rows, _ = _load_csv()
    if not _nhanaz_is_stale(rows):
        return  # NhanAZ đủ mới, không cần scraper

    # 3. Chạy fallback scraper
    scraped: list[dict] = []

    # 3a. xosominhngoc (ưu tiên vì có draw_id rõ ràng)
    scraped = _fetch_xosominhngoc()

    # 3b. Vietlott AJAX nếu xosominhngoc trống
    if not scraped:
        scraped = _fetch_vietlott()

    if scraped:
        _append_scraped(scraped)
    else:
        print("Fallback scraper: tất cả đều thất bại — sẽ dùng dữ liệu NhanAZ hiện tại.")


if __name__ == "__main__":
    main()
