"""
jackpot_check.py
-----------------
Determines whether the *next* draw is Lotto 5/35's jackpot-sharing draw
("ky chia giai Doc Dac"), per Vietlott's published rule:

  "Sau khi ket thuc mot ky quay so mo thuong bat ky va gia tri Giai Doc Dac
   vuot tren 12 ty dong (cong bo khong co nguoi trung Giai Doc Dac) thi ky
   quay so mo thuong CUOI CUNG cua ngay LIEN KE TIEP THEO duoc xac dinh la
   ky quay so mo thuong 'Chia Giai Doc Dac'."

In plain terms:
  - Jackpot accumulates from 6 billion VND if unclaimed.
  - Once it's confirmed to exceed 12 billion VND after some draw, the
    21:00 draw of the FOLLOWING calendar day is the sharing round --
    not just "any draw where jackpot > 12 billion".

This module:
  1. Scrapes the current jackpot figure (best-effort; falls back across
     sources; returns None if it can't confidently parse a number rather
     than guessing).
  2. Given the last known draw (date + time), infers the next draw's
     time slot, including recovering when draw_time is None (using
     draw_id parity: odd ID = 13:00, even ID = 21:00).
  3. Both conditions (jackpot > 12B AND next draw is the 21:00 of the
     following day) must hold.  If either can't be determined confidently,
     returns is_sharing_round=False -- we never want a false alert.

Sources for jackpot value (ordered by reliability):
  PRIMARY  : vietlott.vn result / product pages  (official, but its WAF
             returns 403 to datacenter IPs such as GitHub Actions runners —
             so in CI it almost always fails and we must have a fallback)
  FALLBACK : xosominhngoc.net.vn/kqxs-lotto-535  (reachable in CI — it is the
             SAME host fetch_data.py reads draw results from every run — and
             it prints "Giá trị giải Độc Đắc: X.XXX.XXX.XXX" on that page)
NOTE: xosominhngoc.net.vn IS a results page, but it also shows the current
jackpot value, so the label-anchored parser below picks it up.  Earlier
comments claiming "result pages don't show the jackpot" were inaccurate for
this specific page and were the reason the scraper had no working source in
CI once vietlott.vn started 403-ing.
"""

from __future__ import annotations
import re
import sys
from datetime import date, datetime, timedelta

import requests

# ── Sources ─────────────────────────────────────────────────────────────────
# Only pages that actually show the Jackpot (Độc Đắc) value.
# xsmn.mobi/xs-lotto-5-35.html shows "Giá trị Độc Đắc: X đồng" prominently.
# Pure result pages (xosominhngoc, xskt…) do NOT show jackpot value — excluded.
JACKPOT_SOURCES = [
    # Nguồn 1: vietlott.vn trang kết quả — chính thức, cập nhật ngay sau kỳ quay.
    #          LƯU Ý: WAF của vietlott.vn chặn IP datacenter (GitHub Actions) →
    #          thường trả 403 trong CI, nên BẮT BUỘC phải có nguồn dự phòng bên dưới.
    "https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/535",
    # Nguồn 2: vietlott.vn trang giới thiệu sản phẩm — thường hiển thị jackpot hiện tại
    "https://vietlott.vn/vi/choi/lotto535/gioi-thieu-san-pham-535",
    # Nguồn 3 (DỰ PHÒNG, hoạt động trong CI): xosominhngoc.net.vn — CÙNG host mà
    #          fetch_data.py đọc kết quả kỳ quay mỗi lần chạy (đã chứng minh
    #          truy cập được từ GitHub Actions), và hiển thị dòng
    #          "Giá trị giải Độc Đắc: X.XXX.XXX.XXX" ngay trên trang kết quả.
    "https://xosominhngoc.net.vn/kqxs-lotto-535",
    # xsmn.mobi đã xóa: trả số cũ, không đồng bộ với vietlott.vn
    # minhchinh.com đã xóa: chậm cập nhật, không đáng tin cậy
]

# vietlott.vn (nguồn CHÍNH THỨC) bị WAF chặn 403 với IP datacenter. Đã ĐO THỰC TẾ
# trên GitHub Actions: cả request trực tiếp LẪN reader-proxy công cộng
# (r.jina.ai) đều nhận 403 → thử chúng mỗi lần chạy chỉ tốn thời gian mà không
# bao giờ thành công. Vì vậy CHỈ gọi vietlott.vn khi có proxy riêng
# (secret VIETLOTT_PROXY) — đường duy nhất còn khả năng qua được WAF.
VIETLOTT_JACKPOT_SOURCES = [u for u in JACKPOT_SOURCES if "vietlott.vn" in u]

# Nguồn bên thứ ba bổ sung — CHỈ giữ URL đã kiểm chứng bằng
# scripts/check_sources.py. Trang nào không parse được dòng "Giá trị ... Độc
# Đắc: X" sẽ tự bị bỏ qua, không làm hỏng luồng.
#   Đã GỠ (đo được HTTP 404, URL sai): xskt.com.vn, ketqua.net
EXTRA_JACKPOT_SOURCES = [
    # ĐÃ KIỂM CHỨNG 06/08/2026 (do người dùng cung cấp): trả đúng
    # 24.994.046.000 đ gắn ĐÚNG kỳ #806 — khớp xosominhngoc. Nguồn dự phòng
    # đáng tin cậy thứ hai, đặt ngay sau nguồn chính.
    "https://www.minhchinh.com/xo-so-dien-toan-lotto-535.html",
    # lotto-8: trả 200 nhưng hiện KHÔNG có dòng Độc Đắc. Giữ vì vô hại và
    # trang có thể bổ sung sau; checker sẽ báo nếu bắt đầu có số.
    "https://www.lotto-8.com/Vietnam/listltoVM35.asp?indexpage=1",
    # onbit.vn: ĐÃ KIỂM CHỨNG có số, NHƯNG đo được 14.537.041.000 đ và KHÔNG
    # gắn được mã kỳ — lệch hẳn giá trị thật của kỳ #806. Nhiều khả năng là pot
    # cũ/khác sản phẩm. Để CUỐI: lớp kiểm định theo kỳ sẽ loại giá trị không
    # khớp kỳ mới nhất, nên nó chỉ được dùng khi mọi nguồn trên đều chết.
    "https://onbit.vn/ket-qua-xo-so/vietlott-lotto535",
]

# ỨNG VIÊN — CHƯA kiểm chứng, KHÔNG dùng trong pipeline. check_sources.py sẽ dò
# thử; cái nào thật sự trả về giá trị Độc Đắc thì mới chuyển lên
# EXTRA_JACKPOT_SOURCES. Tránh lặp lại lỗi thêm URL đoán mò vào production.
#
# ĐÃ DÒ VÀ LOẠI (đo 06/08/2026 trên GitHub Actions — đừng thêm lại):
#   404          : xosodaiphat.com/xo-so-dien-toan-vietlott/lotto-5-35.html
#                  xoso.com.vn/lotto-5-35-xstd.html
#                  ketqua.net/xo-so-vietlott  (+ /xo-so-vietlott-lotto-535)
#                  xskt.com.vn/xo-so-dien-toan/lotto-5-35
#   200, KHÔNG có dòng "Giá trị Độc Đắc":
#                  minhngoc.net.vn/ket-qua-xo-so/dien-toan-lotto-5-35.html
#                  xskt.com.vn/xsdt/lotto-5-35
# Kết luận: các trang kết quả phổ biến chỉ đăng DÃY SỐ, không đăng giá trị
# Độc Đắc — nên rất ít nguồn thay thế được xosominhngoc.
#   ĐÃ THĂNG HẠNG (kiểm chứng đạt): minhchinh.com, onbit.vn
CANDIDATE_JACKPOT_SOURCES: list[str] = []

# NGUỒN CUỐI CÙNG: Google. Kém tin cậy — Google hay trả CAPTCHA cho IP
# datacenter (GitHub Actions) và HTML đổi liên tục, nên chỉ dùng khi mọi nguồn
# trên đều chết; thất bại là bình thường và được bỏ qua yên lặng.
GOOGLE_JACKPOT_URL = (
    "https://www.google.com/search?q=gi%C3%A1+tr%E1%BB%8B+gi%E1%BA%A3i+"
    "%C4%91%E1%BB%99c+%C4%91%E1%BA%AFc+lotto+5%2F35+vietlott&hl=vi"
)

THRESHOLD_VND = 12_000_000_000

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9",
}

MIN_JACKPOT_VND = 1_000_000_000
MAX_JACKPOT_VND = 500_000_000_000

_JACKPOT_LABELS = ("độc đắc", "doc dac", "jackpot")
_DECOY_HINTS = ("ước tính", "uoc tinh", "kỳ tới", "ky toi", "dự kiến", "du kien",
                "doanh thu", "doanh số", "doanh so", "tổng giá trị", "luỹ kế", "lũy kế")
_LABEL_WINDOW = 200   # chars — xsmn.mobi puts value ~100 chars after the label


# ── Jackpot parser ───────────────────────────────────────────────────────────

def _label_positions(low_html: str, label: str) -> list[int]:
    return [m.start() for m in re.finditer(re.escape(label), low_html)]


def _money_matches(html: str) -> list[tuple[int, int]]:
    out = []
    low = html.lower()
    label_pos = sorted(p for lab in _JACKPOT_LABELS for p in _label_positions(low, lab))
    for m in re.finditer(r"([\d][\d\.,]{8,})(?:\s*(?:đồng|dong|vnd))?", html, re.IGNORECASE):
        raw = m.group(1)
        # Requires thousands-separator — rejects run-together IDs like "1419252830"
        if "." not in raw and "," not in raw:
            continue
        digits = re.sub(r"[^\d]", "", raw)
        if not digits:
            continue
        v = int(digits)
        if not (MIN_JACKPOT_VND <= v <= MAX_JACKPOT_VND):
            continue
        has_unit = m.group(0).lower().rstrip().endswith(("đồng", "dong", "vnd"))
        near_label = any(0 <= m.start() - lp <= _LABEL_WINDOW for lp in label_pos)
        if has_unit or near_label:
            out.append((v, m.start()))
    return out


# draw_id (kỳ) '#NNNNN' — dùng để KIỂM ĐỊNH giá trị jackpot đúng theo kỳ.
_KY_RE = re.compile(r"#\s*(\d{3,6})")


def _draw_id_before(html: str, pos: int) -> str | None:
    """draw_id (kỳ) '#NNNNN' gần nhất NẰM TRƯỚC vị trí pos trong html.

    Trang kết quả (xosominhngoc, vietlott…) liệt kê nhiều kỳ; mỗi khối bắt đầu
    bằng 'Kỳ … #NNNNN' rồi tới 'Giá trị … Độc Đắc: <số>'. Kỳ gắn với một giá
    trị jackpot chính là '#NNNNN' đứng ngay trước con số đó."""
    best = None
    for m in _KY_RE.finditer(html):
        if m.start() < pos:
            best = m.group(1)
        else:
            break
    return best


def _jackpot_candidates(html: str) -> list[tuple[int, int, str | None]]:
    """Mọi ứng viên (value, khoảng_cách_tới_nhãn, kỳ) gắn với nhãn Độc Đắc,
    đã loại các decoy ('ước tính', 'kỳ tới', 'doanh thu'…)."""
    money = _money_matches(html)
    if not money:
        return []
    low = html.lower()
    label_pos = sorted(p for lab in _JACKPOT_LABELS for p in _label_positions(low, lab))

    out: list[tuple[int, int, str | None]] = []
    if label_pos:
        for value, pos in money:
            preceding = [lp for lp in label_pos if 0 <= pos - lp <= _LABEL_WINDOW]
            if not preceding:
                continue
            nearest = max(preceding)
            if any(h in low[nearest:pos] for h in _DECOY_HINTS):
                continue
            out.append((value, pos - nearest, _draw_id_before(html, pos)))
    else:
        # Không có nhãn nào: lấy giá trị lớn nhất (khoảng cách coi như vô cùng).
        for value, pos in money:
            out.append((value, 10 ** 9, _draw_id_before(html, pos)))
    return out


def _extract_jackpot(html: str,
                     expected_draw_id: str | None = None) -> tuple[int | None, str | None]:
    """Trả (jackpot_vnd, kỳ) — giá trị Độc Đắc gắn chặt nhất với nhãn.

    KIỂM ĐỊNH THEO KỲ: nếu biết `expected_draw_id` (kỳ mới nhất trong dữ liệu),
    LOẠI mọi ứng viên có kỳ CŨ HƠN — trang chưa cập nhật sẽ hiển thị jackpot của
    kỳ trước, dùng nhầm sẽ kích hoạt/huỷ kỳ chia giải sai. Ưu tiên ứng viên đúng
    kỳ; nếu không có ứng viên hợp lệ nào (toàn kỳ cũ) → trả (None, None) để
    không hành động trên dữ liệu cũ."""
    cands = _jackpot_candidates(html)
    if not cands:
        return None, None

    exp = None
    if expected_draw_id:
        try:
            exp = int(expected_draw_id)
        except (ValueError, TypeError):
            exp = None

    def _ky_int(ky: str | None) -> int | None:
        try:
            return int(ky) if ky else None
        except ValueError:
            return None

    pool = cands
    if exp is not None:
        # Giữ ứng viên có kỳ >= kỳ mới nhất (hoặc không rõ kỳ); bỏ kỳ cũ.
        valid = [c for c in cands if _ky_int(c[2]) is None or _ky_int(c[2]) >= exp]
        exact = [c for c in valid if _ky_int(c[2]) == exp]
        pool = exact or valid
        if not pool:
            return None, None

    # Nhãn gần nhất; khi khoảng cách bằng nhau (vd nhánh không nhãn) → giá trị lớn nhất.
    best = min(pool, key=lambda c: (c[1], -c[0]))
    return best[0], best[2]


def _extract_jackpot_vnd(html: str) -> int | None:
    """Chỉ lấy giá trị (không kiểm định kỳ) — giữ cho tương thích/self-test."""
    return _extract_jackpot(html)[0]


# ── Nguồn AI (Gemini) — CHỐT CHẶN CUỐI ──────────────────────────────────────
# Chỉ bật khi có secret GEMINI_API_KEY. Đặt SAU mọi nguồn thật vì LLM có thể
# BỊA một con số trông rất hợp lý — nguy hiểm hơn scraper hỏng (scraper hỏng thì
# im, LLM bịa thì thuyết phục). Ba lớp chặn:
#   1. Bắt buộc Google Search grounding (không cho trả lời từ trí nhớ)
#   2. Chỉ nhận số trong khoảng hợp lý GEMINI_MIN..GEMINI_MAX
#   3. Vẫn đi qua lớp kiểm định theo kỳ như mọi nguồn khác
GEMINI_MODEL = "gemini-flash-latest"
GEMINI_MIN_VND = 5_000_000_000     # pot khởi điểm ~6 tỷ
GEMINI_MAX_VND = 500_000_000_000   # trần an toàn


def _fetch_jackpot_gemini(expected_draw_id: str | None) -> tuple[int | None, str | None]:
    """Hỏi Gemini (có Google Search grounding) giá trị Độc Đắc hiện tại.
    Trả (số tiền, mã kỳ) hoặc (None, None). Không có API key → bỏ qua."""
    import json as _json
    import os
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None, None

    prompt = (
        "Tra cứu bằng Google Search: giá trị giải Độc Đắc (Jackpot) hiện tại của "
        "xổ số Vietlott Lotto 5/35, và mã kỳ quay gần nhất. "
        "CHỈ trả lời bằng JSON thuần, không giải thích, dạng: "
        '{"jackpot_vnd": <số nguyên VND, không dấu chấm>, "draw_id": "<mã kỳ 5 chữ số>"} '
        "Nếu không tra được chắc chắn, trả {\"jackpot_vnd\": null, \"draw_id\": null}. "
        "TUYỆT ĐỐI không đoán hay bịa số."
    )
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent")
    base = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0},
    }
    # Tên trường công cụ grounding khác nhau giữa các phiên bản API/model. Thử
    # lần lượt; KHÔNG bao giờ gọi mà thiếu grounding (dễ bịa số).
    tool_variants = [
        ("google_search", {"google_search": {}}),
        ("googleSearch", {"googleSearch": {}}),
        ("google_search_retrieval", {"google_search_retrieval": {}}),
    ]
    text = None
    for name, tool in tool_variants:
        try:
            r = requests.post(url, timeout=40,
                              headers={"Content-Type": "application/json",
                                       "X-goog-api-key": key},
                              json={**base, "tools": [tool]})
        except requests.RequestException as e:
            print(f"[jackpot] gemini: lỗi mạng ({name}): {str(e)[:80]}")
            return None, None
        if r.ok:
            try:
                parts = r.json()["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts)
                break
            except (KeyError, IndexError, ValueError) as e:
                print(f"[jackpot] gemini: phản hồi lạ ({name}): {str(e)[:60]}")
                return None, None
        # In lỗi ra STDOUT để luôn thấy trong log Actions (stderr hay bị nuốt).
        body = r.text[:200].replace("\n", " ")
        print(f"[jackpot] gemini: HTTP {r.status_code} với tools={name} → {body}")
        if r.status_code in (401, 403):
            return None, None          # key sai/không quyền → thử tiếp vô ích
    if text is None:
        print("[jackpot] gemini: không gọi được API với mọi biến thể grounding")
        return None, None

    m = re.search(r"\{[^{}]*\}", text, re.S)
    if not m:
        print("WARNING: [jackpot] gemini: không đọc được JSON", file=sys.stderr)
        return None, None
    try:
        data = _json.loads(m.group(0))
        amount = data.get("jackpot_vnd")
        ky = data.get("draw_id")
    except ValueError:
        return None, None

    if not isinstance(amount, int):
        return None, None
    if not (GEMINI_MIN_VND <= amount <= GEMINI_MAX_VND):
        print(f"WARNING: [jackpot] gemini: bỏ {amount:,} VND — ngoài khoảng hợp lý",
              file=sys.stderr)
        return None, None
    ky = str(ky).zfill(5) if ky else None
    if expected_draw_id and ky and int(ky) < int(expected_draw_id):
        print(f"WARNING: [jackpot] gemini: bỏ giá trị của kỳ #{ky} (cũ hơn "
              f"#{expected_draw_id})", file=sys.stderr)
        return None, None
    print(f"[jackpot] gemini (AI, chốt cuối): {amount:,} VND ✓ (kỳ #{ky or '?'})")
    return amount, ky


def _vietlott_proxy() -> str | None:
    """Proxy riêng để vượt WAF vietlott.vn (secret VIETLOTT_PROXY). Không có
    thì bỏ qua hẳn vietlott.vn — gọi thẳng chỉ nhận 403."""
    import os
    return os.environ.get("VIETLOTT_PROXY", "").strip() or None


def _jackpot_attempts() -> list[tuple[str, str]]:
    """Danh sách (url, nhãn) sẽ thử, theo thứ tự ưu tiên giảm dần:
      1. vietlott.vn (CHÍNH THỨC) — CHỈ khi có secret VIETLOTT_PROXY, vì không
         có proxy thì chắc chắn 403 (đã đo trên CI).
      2. xosominhngoc + các nguồn bên thứ ba
      3. Google (chốt chặn cuối, hay CAPTCHA — thất bại là bình thường)
    """
    attempts = []
    if _vietlott_proxy():
        attempts += [(u, "vietlott.vn (chính thức, qua proxy)")
                     for u in VIETLOTT_JACKPOT_SOURCES]

    third_party = [u for u in JACKPOT_SOURCES if u not in VIETLOTT_JACKPOT_SOURCES]
    attempts += [(u, u.split("/")[2]) for u in third_party + EXTRA_JACKPOT_SOURCES]
    attempts.append((GOOGLE_JACKPOT_URL, "google.com (chốt chặn cuối)"))
    return attempts


def _scrape_jackpot_vnd(expected_draw_id: str | None = None) -> tuple[int | None, str | None]:
    """Lấy giá trị Độc Đắc, ĐÃ kiểm định theo kỳ.

    `expected_draw_id` = kỳ mới nhất trong dữ liệu. Chỉ chấp nhận giá trị của
    kỳ đó trở đi; giá trị của kỳ cũ hơn (trang chưa cập nhật) bị bỏ để tránh
    kích hoạt/huỷ kỳ chia giải nhầm."""
    proxy = _vietlott_proxy()
    for url, label in _jackpot_attempts():
        try:
            # Chỉ định tuyến vietlott.vn qua proxy; nguồn khác đi thẳng.
            proxies = ({"http": proxy, "https": proxy}
                       if proxy and "vietlott.vn" in url else None)
            resp = requests.get(url, timeout=20, headers=_HEADERS, proxies=proxies)
            resp.raise_for_status()
            amount, ky = _extract_jackpot(resp.text, expected_draw_id)
            if amount is not None:
                ky_note = f"kỳ #{ky}" if ky else "kỳ không xác định"
                print(f"[jackpot] {label}: {amount:,} VND ✓ ({ky_note})")
                return amount, url
            # Phân biệt "không có số" với "có số nhưng là kỳ cũ" để log rõ ràng.
            raw_amount, raw_ky = _extract_jackpot(resp.text)
            if raw_amount is not None and expected_draw_id and raw_ky:
                print(f"WARNING: [jackpot] {label}: bỏ giá trị {raw_amount:,} VND của "
                      f"kỳ #{raw_ky} vì cũ hơn kỳ mới nhất #{expected_draw_id} "
                      f"(nguồn chưa cập nhật)", file=sys.stderr)
            else:
                print(f"WARNING: [jackpot] {label}: OK nhưng không tìm được số Độc Đắc",
                      file=sys.stderr)
        except requests.RequestException as e:
            print(f"WARNING: [jackpot] {label}: {e}", file=sys.stderr)

    # CHỐT CHẶN CUỐI: mọi nguồn thật đã chết → thử Gemini (nếu có API key).
    amount, ky = _fetch_jackpot_gemini(expected_draw_id)
    if amount is not None:
        return amount, f"gemini:{GEMINI_MODEL}"

    print("WARNING: [jackpot] tất cả nguồn đều thất bại", file=sys.stderr)
    return None, None


# ── draw_time inference ──────────────────────────────────────────────────────

def _infer_draw_time(draw_id: str | None, draw_time: str | None) -> str | None:
    """Return draw_time if known; otherwise infer from draw_id parity.

    Lotto 5/35 schedule (confirmed from NhanAZ data):
      draw_id odd  → 13:00 draw
      draw_id even → 21:00 draw
    This covers the case where fallback scraper appended a row without
    draw_time in attributes_json.
    """
    if draw_time in ("13:00", "21:00"):
        return draw_time
    # Infer from draw_id parity
    if draw_id:
        try:
            n = int(draw_id)
            return "13:00" if n % 2 == 1 else "21:00"
        except (ValueError, TypeError):
            pass
    return None


def _next_draw_slot(last_draw_date: str, last_draw_time: str) -> tuple[date, str] | None:
    """Compute (date, time) of the draw immediately following last_draw."""
    try:
        d = datetime.strptime(last_draw_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    if last_draw_time == "13:00":
        return d, "21:00"
    if last_draw_time == "21:00":
        return d + timedelta(days=1), "13:00"
    return None


# ── Public API ───────────────────────────────────────────────────────────────

def check_jackpot(last_draw_date: str, last_draw_time: str | None,
                  threshold_crossed_date: str | None = None,
                  last_draw_id: str | None = None) -> dict:
    """Determine whether the NEXT draw is the jackpot-sharing round.

    Per Vietlott's rule the sharing round is the 21:00 draw of the day
    IMMEDIATELY FOLLOWING the day a draw first confirmed the jackpot above 12
    billion. `threshold_crossed_date` (YYYY-MM-DD) is that confirmation day.

    draw_time may be None when data came from a scraper that didn't record it;
    pass last_draw_id so the function can infer from draw_id parity.
    """
    jackpot_vnd, source = _scrape_jackpot_vnd(last_draw_id)

    # Resolve draw_time: explicit > inferred from ID parity
    resolved_time = _infer_draw_time(last_draw_id, last_draw_time)

    next_slot = None
    if resolved_time:
        next_slot = _next_draw_slot(last_draw_date, resolved_time)

    is_sharing_round = False
    reason = "insufficient information"

    crossed = None
    if threshold_crossed_date:
        try:
            crossed = datetime.strptime(threshold_crossed_date, "%Y-%m-%d").date()
        except ValueError:
            crossed = None

    if jackpot_vnd is None:
        reason = "could not scrape jackpot amount"
    elif next_slot is None:
        reason = f"could not determine next draw slot (draw_time={last_draw_time}, draw_id={last_draw_id})"
    else:
        next_date, next_time = next_slot
        if jackpot_vnd <= THRESHOLD_VND:
            reason = f"jackpot {jackpot_vnd:,} VND has not exceeded 12 billion yet"
        elif next_time != "21:00":
            reason = "next draw is a 13:00 draw, not the 21:00 sharing slot"
        elif crossed is None:
            reason = ("jackpot > 12 billion but threshold_crossed_date unknown "
                      "— staying silent to avoid false alert")
        elif next_date == crossed + timedelta(days=1):
            is_sharing_round = True
            reason = (
                f"jackpot {jackpot_vnd:,} VND exceeds 12 billion and the next 21:00 "
                f"draw ({next_date}) is the day after 12B was first crossed ({crossed})"
            )
        else:
            reason = (f"next 21:00 draw {next_date} is not the day after the 12B "
                      f"crossing ({crossed}); sharing round already passed or not yet")

    return {
        "source": source,
        "jackpot_vnd": jackpot_vnd,
        "resolved_draw_time": resolved_time,
        "next_draw_date": next_slot[0].isoformat() if next_slot else None,
        "next_draw_time": next_slot[1] if next_slot else None,
        "threshold_crossed_date": threshold_crossed_date,
        "is_sharing_round": is_sharing_round,
        "reason": reason,
    }


# ── Self-tests ───────────────────────────────────────────────────────────────

def _self_test_parser():
    vietlott = (
        "Kỳ quay thưởng #00752 ngày 09/07/2026\n1419252830|04\n"
        "Doanh thu kỳ này: 7.269.262.500 đồng\n"
        "Giải Độc Đắc\t6.231.022.500 VND\n"
        "Giải Độc Đắc\tO O O O O + O\t0\t6.231.022.500"
    )
    xsmn = ("Kỳ vé #00751\nGiá trị Độc Đắc:\n6.088.615.000 đồng\n"
            "Jackpot ước tính kỳ tới: 7.269.262.500 đồng")
    # Định dạng thực tế trên xosominhngoc.net.vn/kqxs-lotto-535 (nguồn dự phòng
    # hoạt động trong CI): nhãn "Giá trị giải Độc Đắc" + con số có dấu chấm phân
    # cách, kèm decoy "kỳ tới" phải bị bỏ qua.
    xosominhngoc = ("KQXS Lotto 5/35 – Kỳ #00756 ngày 11/07/2026\n"
                    "Giá trị giải Độc Đắc: 11.925.318.500 đồng\n"
                    "Giá trị Jackpot dự kiến kỳ tới: 13.000.000.000 đồng")
    # Định dạng THẬT trên xosominhngoc.net.vn (đối chiếu trực tiếp kỳ #00756):
    # nhãn nằm dòng riêng, con số ở dòng kế, KHÔNG có chữ "đồng", có khoảng
    # trắng cuối — vẫn phải lấy đúng nhờ số nằm sát ngay sau nhãn "Độc Đắc".
    # Dòng "01 04 11 21 27 11" (bộ số + số đặc biệt) KHÔNG được nhận nhầm.
    xosominhngoc_real = ("Kỳ QSMT: #00756 Thứ bảy, Ngày: 11/07/2026 - 21:00\n"
                         "01 04 11 21 27 11\n"
                         "Giá trị giải Độc Đắc\n"
                         "6.652.382.500 ")
    cases = [
        (vietlott, 6_231_022_500),
        (xsmn, 6_088_615_000),
        (xosominhngoc, 11_925_318_500),
        (xosominhngoc_real, 6_652_382_500),
        ("Giải phụ 2.000.000.000 đồng. Giải khác 3.000.000.000 đồng.", 3_000_000_000),
        ("Thông tin Jackpot cập nhật sau." + "x" * 600 + "99.000.000.000 đồng", None),
    ]
    for html, expected in cases:
        got = _extract_jackpot_vnd(html)
        assert got == expected, f"parser: expected {expected}, got {got} for {html[:60]!r}"
    # Kỳ phải được gắn đúng với giá trị.
    assert _extract_jackpot(xosominhngoc_real) == (6_652_382_500, "00756")
    assert _extract_jackpot(vietlott)[1] == "00752"
    print("jackpot parser self-test: OK")


def _self_test_ky_validation():
    """KIỂM ĐỊNH THEO KỲ: trang liệt kê nhiều kỳ; chỉ dùng jackpot của kỳ mới
    nhất, bỏ giá trị của kỳ cũ (nguồn chưa cập nhật)."""
    # Trang có kỳ mới #00758 (ở trên) và kỳ cũ #00756 (bên dưới).
    page_new = (
        "Kỳ QSMT: #00758 Ngày: 12/07/2026 - 21:00\n"
        "Giá trị giải Độc Đắc\n13.500.000.000\n"
        "Kỳ QSMT: #00756 Ngày: 11/07/2026 - 21:00\n"
        "Giá trị giải Độc Đắc\n6.652.382.500\n"
    )
    # Biết kỳ mới nhất là #00758 → lấy đúng 13,5 tỷ của kỳ #00758.
    assert _extract_jackpot(page_new, "00758") == (13_500_000_000, "00758")

    # Nguồn CHƯA cập nhật: chỉ có kỳ cũ #00756, nhưng ta đã có tới #00758.
    page_stale = ("Kỳ QSMT: #00756 Ngày: 11/07/2026 - 21:00\n"
                  "Giá trị giải Độc Đắc\n6.652.382.500\n")
    # → phải TỪ CHỐI (None) thay vì trả giá trị cũ.
    assert _extract_jackpot(page_stale, "00758") == (None, None)
    # Không truyền kỳ kỳ vọng → vẫn lấy giá trị (tương thích cũ).
    assert _extract_jackpot(page_stale)[0] == 6_652_382_500
    # Nguồn mới hơn dữ liệu (kỳ #00757 > #00756 ta đang có) → chấp nhận.
    page_ahead = ("Kỳ QSMT: #00757 Ngày: 12/07/2026 - 13:00\n"
                  "Giá trị giải Độc Đắc\n7.000.000.000\n")
    assert _extract_jackpot(page_ahead, "00756") == (7_000_000_000, "00757")
    print("jackpot per-kỳ validation self-test: OK")


def _self_test_infer_time():
    assert _infer_draw_time(None, "13:00") == "13:00"
    assert _infer_draw_time("00755", None) == "13:00"   # 755 odd → 13:00
    assert _infer_draw_time("00756", None) == "21:00"   # 756 even → 21:00
    assert _infer_draw_time("00754", "13:00") == "13:00"  # explicit wins
    assert _infer_draw_time(None, None) is None
    print("draw_time inference self-test: OK")


def _self_test_sharing():
    global _scrape_jackpot_vnd
    orig = _scrape_jackpot_vnd
    _scrape_jackpot_vnd = lambda *a, **k: (13_000_000_000, "test")
    try:
        crossed = "2026-07-09"
        # 21:00 slot of 10/07 is next after 10/07 13:00 → sharing
        assert check_jackpot("2026-07-10", "13:00", crossed)[
            "is_sharing_round"] is True
        # draw_time=None but draw_id=00755 (odd) → inferred 13:00 → next is 21:00 same day → sharing
        assert check_jackpot("2026-07-10", None, crossed, last_draw_id="00755")[
            "is_sharing_round"] is True
        # draw_id=00756 (even) → inferred 21:00 → next is 13:00 → NOT sharing
        assert check_jackpot("2026-07-10", None, crossed, last_draw_id="00756")[
            "is_sharing_round"] is False
        # Not the sharing round slots
        assert check_jackpot("2026-07-09", "13:00", crossed)["is_sharing_round"] is False
        assert check_jackpot("2026-07-10", "21:00", crossed)["is_sharing_round"] is False
        assert check_jackpot("2026-07-11", "13:00", crossed)["is_sharing_round"] is False
        assert check_jackpot("2026-07-10", "13:00", None)["is_sharing_round"] is False
    finally:
        _scrape_jackpot_vnd = orig
    print("jackpot sharing-round self-test: OK")


if __name__ == "__main__":
    import json
    _self_test_parser()
    _self_test_ky_validation()
    _self_test_infer_time()
    _self_test_sharing()
    print(json.dumps(check_jackpot("2026-07-11", None, last_draw_id="00755"),
                     ensure_ascii=False, indent=2))
