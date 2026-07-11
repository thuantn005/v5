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


def _extract_jackpot_vnd(html: str) -> int | None:
    """Pick the money figure most tightly bound to a 'Độc Đắc'/'Jackpot' label."""
    money = _money_matches(html)
    if not money:
        return None

    low = html.lower()
    label_pos = sorted(p for lab in _JACKPOT_LABELS for p in _label_positions(low, lab))

    if label_pos:
        best = None
        for value, pos in money:
            preceding = [lp for lp in label_pos if 0 <= pos - lp <= _LABEL_WINDOW]
            if not preceding:
                continue
            nearest = max(preceding)
            context = low[nearest:pos]
            if any(h in context for h in _DECOY_HINTS):
                continue
            dist = pos - nearest
            if best is None or dist < best[0]:
                best = (dist, value)
        return best[1] if best is not None else None

    return max(v for v, _ in money)


def _scrape_jackpot_vnd() -> tuple[int | None, str | None]:
    for url in JACKPOT_SOURCES:
        label = url.split("/")[2]  # hostname để log ngắn gọn
        try:
            resp = requests.get(url, timeout=20, headers=_HEADERS)
            resp.raise_for_status()
            amount = _extract_jackpot_vnd(resp.text)
            if amount is not None:
                print(f"[jackpot] {label}: {amount:,} VND ✓")
                return amount, url
            print(f"WARNING: [jackpot] {label}: OK nhưng không tìm được số Độc Đắc", file=sys.stderr)
        except requests.RequestException as e:
            print(f"WARNING: [jackpot] {label}: {e}", file=sys.stderr)
    print(f"WARNING: [jackpot] tất cả {len(JACKPOT_SOURCES)} nguồn đều thất bại", file=sys.stderr)
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
    jackpot_vnd, source = _scrape_jackpot_vnd()

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
    print("jackpot parser self-test: OK")


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
    _scrape_jackpot_vnd = lambda: (13_000_000_000, "test")
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
    _self_test_infer_time()
    _self_test_sharing()
    print(json.dumps(check_jackpot("2026-07-11", None, last_draw_id="00755"),
                     ensure_ascii=False, indent=2))
