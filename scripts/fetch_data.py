"""
fetch_data.py
-------------
Cập nhật data/all.csv từ NhanAZ-Data (nguồn chính) + fallback scrapers.

Chiến lược:
  1. Tải NhanAZ-Data CSV (raw + CDN) → ghi đè data/all.csv (bộ lịch sử đầy đủ,
     giữ lại kỳ local NhanAZ chưa có để không mất dữ liệu khi nguồn chính trễ).
  2. Nếu kỳ mới nhất trong file < kỳ hôm nay → chạy fallback: THỬ TẤT CẢ nguồn
     rồi GỘP lại (không phụ thuộc một nguồn — chống bị chặn):
       - Vietlott.vn AJAX (chính thức, ưu tiên khử trùng)
       - lotto-8.com (quốc tế, ít bị chặn)
       - NhanAZ CDN bust (trên GitHub, gần như luôn truy cập được)
       - xosominhngoc.net.vn (nếu không 403)
  3. Lấp mọi kỳ THIẾU + append kỳ mới (khử trùng theo draw_id, giữ file sắp xếp).

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
LOTTO8_URL       = "https://www.lotto-8.com/Vietnam/listltoVM35.asp?indexpage=1"
VIETLOTT_BASE    = "https://vietlott.vn"
VIETLOTT_LIST_PATH = "/vi/trung-thuong/ket-qua-trung-thuong/winning-number-535"
VIETLOTT_AJAX_PATH = (
    "/ajaxpro/Vietlott.PlugIn.WebParts.Game535CompareWebPart,"
    "Vietlott.PlugIn.WebParts.ashx"
)
# VƯỢT CHẶN cho nguồn chính Vietlott (dùng ở production khi vietlott.vn chặn IP):
#  - VIETLOTT_PROXY: proxy do người dùng cấu hình (GitHub secret) — cách chắc
#    chắn nhất, chạy được cả AJAX POST.
#  - VIETLOTT_READER: reader-proxy công khai (vd "https://r.jina.ai/"). MẶC ĐỊNH
#    TẮT: đã đo trên GitHub Actions — WAF của vietlott.vn trả 403 cho CẢ
#    r.jina.ai, nên bật chỉ tốn thêm request mà không bao giờ thành công.
#    Đặt biến môi trường nếu muốn thử một reader khác.
VIETLOTT_READER_DEFAULT = ""

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


# ── Session ──────────────────────────────────────────────────────────────────

def _session(proxy: str | None = None) -> requests.Session:
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "vi-VN,vi;q=0.9"})
    if proxy:
        # Định tuyến request qua proxy do người dùng chỉ định (GitHub secret
        # VIETLOTT_PROXY) để VƯỢT chặn IP/vùng — dùng cho cả GET lẫn POST AJAX.
        s.proxies.update({"http": proxy, "https": proxy})
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


# Bản ghi Vietlott sau khi reader-proxy render: mã kỳ 5 chữ số, ngày dd/mm/yyyy,
# rồi 6 số hai chữ số (5 chính + 1 đặc biệt) phân tách bởi khoảng trắng/dấu phẩy.
_VIETLOTT_READER_REC = re.compile(
    r"(?<!\d)(\d{5})(?!\d)"
    r"[\s\S]*?(\d{1,2}/\d{1,2}/\d{4})"
    r"[\s\S]*?((?:\b\d{1,2}\b[\s,|]+){5}\b\d{1,2}\b)"
)


def _parse_vietlott_reader_text(text: str) -> list[dict]:
    """Trích kết quả từ trang Vietlott đã được reader-proxy render (best-effort).
    Mọi bản ghi đều qua kiểm tra hợp lệ (5 số 1-35 + ĐB 1-12) nên dữ liệu sai bị
    loại — không thể làm hỏng file."""
    draws = []
    for m in _VIETLOTT_READER_REC.finditer(text):
        did, date_s, nums_s = m.groups()
        nums = [int(x) for x in re.findall(r"\d{1,2}", nums_s)]
        if len(nums) < 6:
            continue
        numbers, special = sorted(nums[:5]), nums[5]
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if not (1 <= special <= 12):
            continue
        try:
            draw_date = datetime.strptime(date_s, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        draws.append({
            "draw_id":    did.zfill(5),
            "draw_date":  draw_date,
            "numbers":    numbers,
            "special":    special,
            "data_source":"vietlott_vn_reader",
            "source_url": VIETLOTT_BASE + VIETLOTT_LIST_PATH,
        })
    return draws


def _fetch_vietlott_via_reader() -> list[dict]:
    """VƯỢT CHẶN: lấy trang list Vietlott qua reader-proxy render-JS (r.jina.ai),
    không cần AJAX key. Dùng khi request trực tiếp tới vietlott.vn bị chặn."""
    reader = os.environ.get("VIETLOTT_READER", VIETLOTT_READER_DEFAULT).strip()
    if not reader:
        return []
    url = reader + VIETLOTT_BASE + VIETLOTT_LIST_PATH
    try:
        r = _session().get(url, timeout=TIMEOUT)
        if r.status_code in (401, 403, 407):
            print(f"vietlott reader-proxy: {r.status_code} — bỏ qua")
            return []
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: vietlott reader-proxy: {e}", file=sys.stderr)
        return []
    draws = _parse_vietlott_reader_text(r.text)
    if draws:
        print(f"vietlott.vn (reader-proxy vượt chặn): {len(draws)} kỳ quay")
    return draws


def _fetch_vietlott() -> list[dict]:
    proxy = os.environ.get("VIETLOTT_PROXY", "").strip() or None
    if not proxy and not os.environ.get("VIETLOTT_READER", VIETLOTT_READER_DEFAULT).strip():
        # Không proxy, không reader → gọi thẳng vietlott.vn chắc chắn 403 (đã đo
        # trên CI). Bỏ qua để khỏi tốn request; các nguồn khác vẫn chạy đủ.
        print("vietlott.vn: bỏ qua (WAF chặn IP datacenter — cần secret VIETLOTT_PROXY)")
        return []
    s = _session(proxy)
    list_url = VIETLOTT_BASE + VIETLOTT_LIST_PATH
    ajax_url = VIETLOTT_BASE + VIETLOTT_AJAX_PATH
    if proxy:
        print("vietlott.vn: định tuyến qua VIETLOTT_PROXY để vượt chặn")
    try:
        r = s.get(list_url, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: vietlott.vn list page thất bại: {e} → thử reader-proxy", file=sys.stderr)
        return _fetch_vietlott_via_reader()

    key_m = re.search(
        r"ServerSideDrawResult\s*\(\s*RenderInfo\s*,\s*'([0-9a-fA-F]+)'", r.text)
    if not key_m:
        print("WARNING: vietlott.vn: không lấy được AJAX key → thử reader-proxy", file=sys.stderr)
        return _fetch_vietlott_via_reader()

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
        return all_draws
    print("WARNING: vietlott.vn AJAX: không parse được kỳ nào → thử reader-proxy", file=sys.stderr)
    return _fetch_vietlott_via_reader()


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


def _infer_year(day: int, month: int, today) -> int:
    """lotto-8.com hiển thị ngày dạng dd/mm (không kèm năm đủ). Suy năm từ hôm
    nay: mặc định năm hiện tại, nếu ngày rơi quá 7 ngày trong tương lai thì đó
    là năm trước (xử lý ranh giới cuối/đầu năm)."""
    from datetime import date
    y = today.year
    try:
        cand = date(y, month, day)
    except ValueError:
        return y
    if (cand - today).days > 7:
        y -= 1
    return y


# Mỗi bản ghi: mã kỳ 5 chữ số → ngày dd/mm → (bỏ qua thứ/năm) → 5 số chính phân
# tách bằng dấu phẩy → số đặc biệt. Non-greedy để không lấn sang kỳ kế tiếp.
_LOTTO8_REC = re.compile(
    r"(?<!\d)(\d{5})(?!\d)"                       # mã kỳ
    r"\D+?(\d{1,2})/(\d{1,2})"                    # dd/mm
    r"[\s\S]*?"                                   # bỏ qua "(Thứ ..)", năm "26", tab
    r"(\d{1,2}(?:\s*,\s*\d{1,2}){4})"             # 5 số chính "10, 13, 18, 21, 27"
    r"\D+?(\d{1,2})"                              # số đặc biệt
)


def _fetch_lotto8() -> list[dict]:
    """Nguồn quốc tế lotto-8.com (VM35). Thường KHÔNG bị chặn như mirror nội địa.
    Parser viết theo cấu trúc bảng suy đoán — lỗi/403 thì trả rỗng, và mọi bản
    ghi đều qua kiểm tra hợp lệ (5 số 1-35 + ĐB 1-12) nên không thể làm hỏng file.
    """
    try:
        r = _session().get(LOTTO8_URL, timeout=TIMEOUT)
        if r.status_code == 403:
            print("lotto-8.com: 403 Forbidden — bỏ qua")
            return []
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: lotto-8.com: {e}", file=sys.stderr)
        return []

    try:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(r.text, "lxml").get_text("\n")
    except ImportError:
        text = r.text

    today = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
    draws = []
    for m in _LOTTO8_REC.finditer(text):
        did, dd, mm, main_s, sp_s = m.groups()
        try:
            day, month = int(dd), int(mm)
            numbers = sorted(int(x) for x in main_s.split(","))
            special = int(sp_s)
        except ValueError:
            continue
        if len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            continue
        if not (1 <= special <= 12) or not (1 <= day <= 31 and 1 <= month <= 12):
            continue
        year = _infer_year(day, month, today)
        draws.append({
            "draw_id":    did.zfill(5),
            "draw_date":  f"{year:04d}-{month:02d}-{day:02d}",
            "numbers":    numbers,
            "special":    special,
            "data_source":"lotto8_com",
            "source_url": LOTTO8_URL,
        })
    if draws:
        print(f"lotto-8.com: {len(draws)} kỳ quay")
    return draws


# ── Bước 4: Append kỳ mới vào CSV ───────────────────────────────────────────

def _rewrite_csv(rows: list[dict], fieldnames: list[str]) -> None:
    """Ghi lại toàn bộ file theo thứ tự draw_id tăng dần (giữ file luôn sắp xếp,
    kể cả khi vừa lấp một kỳ bị thiếu ở giữa)."""
    rows = sorted(rows, key=lambda r: int(r["draw_id"]) if r.get("draw_id", "").isdigit() else 0)
    with open(DATA_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _find_gaps(rows: list[dict]) -> list[int]:
    """Danh sách các draw_id còn thiếu trong khoảng [min, max]."""
    ids = sorted(int(r["draw_id"]) for r in rows if r.get("draw_id", "").isdigit())
    if not ids:
        return []
    return [i for i in range(ids[0], ids[-1] + 1) if i not in set(ids)]


def _scraped_row(did: int, d: dict, id_width: int, now_iso: str) -> dict:
    return {
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


def _append_scraped(scraped: list[dict]) -> int:
    rows, fieldnames = _load_csv()
    if not fieldnames:
        print("ERROR: data/all.csv không có fieldnames", file=sys.stderr)
        return 0

    id_width = len(rows[0]["draw_id"]) if rows else 5
    # Tập các kỳ ĐÃ CÓ (theo id). Dùng để bỏ qua — thay vì chỉ so với max —
    # nhờ vậy một kỳ bị THIẾU ở giữa (nhỏ hơn max) vẫn được lấp khi nguồn trả về.
    present = {int(r["draw_id"]) for r in rows if r.get("draw_id", "").isdigit()}

    candidates = []
    for d in scraped:
        try:
            did = int(d["draw_id"])
        except (ValueError, KeyError):
            continue
        if did in present:
            continue
        numbers = d.get("numbers", [])
        special = d.get("special", 0)
        if (len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers)
                or special < 1 or special > 12):
            continue
        candidates.append((did, d))
        present.add(did)

    if not candidates:
        gaps = _find_gaps(rows)
        note = f" (vẫn còn thiếu {gaps})" if gaps else ""
        print(f"Fallback: không có kỳ THIẾU/mới nào để bổ sung — max #{_max_draw_id(rows)}{note}.")
        return 0

    now_iso  = datetime.now(timezone.utc).isoformat()
    new_rows = [_scraped_row(did, d, id_width, now_iso) for did, d in candidates]

    # Gộp + sắp xếp + ghi lại: lấp đúng vị trí kỳ thiếu và giữ file theo thứ tự.
    _rewrite_csv(rows + new_rows, fieldnames)

    ids_added = sorted(str(did).zfill(id_width) for did, _ in candidates)
    remaining = _find_gaps(rows + new_rows)
    if remaining:
        print(f"⚠️  Vẫn còn {len(remaining)} kỳ thiếu chưa lấp được: {remaining}", file=sys.stderr)
    print(f"Fallback: bổ sung {len(new_rows)} kỳ: {ids_added}")
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
        # Đọc dữ liệu local TRƯỚC khi ghi đè để giữ lại các kỳ NhanAZ chưa có.
        old_rows, _ = _load_csv()
        with open(DATA_PATH, "w", encoding="utf-8", newline="") as f:
            f.write(csv_text)
        print(f"data/all.csv cập nhật: {_count_data_rows(csv_text)} kỳ")

        # NhanAZ (nguồn chính) hay bị trễ vài kỳ. Ghi đè toàn bộ file sẽ XOÁ mất
        # các kỳ mới đã scrape trước đó → dữ liệu tụt hậu. Giữ lại kỳ local nào
        # NhanAZ chưa có rồi gộp lại (giữ đúng thứ tự).
        fresh_rows, fresh_fields = _load_csv()
        if fresh_fields:
            have = {int(r["draw_id"]) for r in fresh_rows if r.get("draw_id", "").isdigit()}
            preserved = [r for r in old_rows
                         if r.get("draw_id", "").isdigit() and int(r["draw_id"]) not in have]
            if preserved:
                _rewrite_csv(fresh_rows + preserved, fresh_fields)
                kept = sorted(str(int(r["draw_id"])) for r in preserved)
                print(f"Giữ lại {len(preserved)} kỳ local NhanAZ chưa có: {kept}")

    # 2. Kiểm tra cần fallback không
    rows, _ = _load_csv()
    if not _needs_fallback(rows):
        return

    # 3. Chạy fallback: THỬ TẤT CẢ nguồn còn sống rồi GỘP lại.
    # Không phụ thuộc một nguồn duy nhất — nếu nguồn chính (Vietlott) bị chặn,
    # các nguồn khác (lotto-8.com quốc tế, NhanAZ trên GitHub, xosominhngoc) vẫn
    # đóng góp. Thứ tự dưới đây = ƯU TIÊN KHỬ TRÙNG: nguồn đứng trước THẮNG khi
    # trùng draw_id, nên số liệu CHÍNH THỨC (Vietlott) được giữ. _append_scraped
    # tự khử trùng + lấp lỗ hổng + bỏ qua kỳ đã có.
    print("\n=== Fallback scrapers (thử tất cả, gộp lại) ===")
    scraped: list[dict] = []
    for label, fn in (
        ("Vietlott (chính thức)", _fetch_vietlott),
        ("lotto-8.com",           _fetch_lotto8),
        ("NhanAZ CDN bust",       _fetch_nhanaz_bust),
        ("xosominhngoc",          _fetch_xosominhngoc),
    ):
        try:
            part = fn() or []
        except Exception as e:                       # một nguồn lỗi không được làm hỏng cả chuỗi
            print(f"WARNING: nguồn {label} lỗi: {e}", file=sys.stderr)
            part = []
        if part:
            scraped += part

    if scraped:
        _append_scraped(scraped)
    else:
        print("Tất cả nguồn fallback đều bị chặn/thất bại — giữ nguyên dữ liệu hiện có.")


if __name__ == "__main__":
    main()
