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
  2. Given the last known draw (date + time), computes whether the *next*
     draw to be predicted is that following day's 21:00 draw, AND the
     jackpot is above the 12 billion threshold.

Both conditions must hold. If either can't be determined confidently,
this returns is_sharing_round=False -- we never want a false "jackpot"
alert.
"""

from __future__ import annotations
import re
import sys
from datetime import date, datetime, timedelta

import requests

URL = "https://vietlott.vn/vi/choi/lotto535/gioi-thieu-san-pham-535"
FALLBACK_URLS = [
    "https://xsmn.mobi/xs-lotto-5-35.html",
    "https://www.minhchinh.com/truc-tiep-xo-so-tu-chon-lotto-535.html",
    "https://onbit.vn/ket-qua-xo-so/vietlott-lotto535",
    "https://www.ketquadientoan.com/tat-ca-ky-xo-so-lotto-535.html",
]
ALL_SOURCES = [URL] + FALLBACK_URLS
THRESHOLD_VND = 12_000_000_000

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
}


MIN_JACKPOT_VND = 1_000_000_000
MAX_JACKPOT_VND = 500_000_000_000
# Labels that sit right next to the jackpot figure on these pages.
_JACKPOT_LABELS = ("jackpot", "độc đắc", "doc dac", "giá trị jackpot", "giai jackpot")
_LABEL_WINDOW = 400  # chars: how far after a label the number may appear


def _money_matches(html: str) -> list[tuple[int, int]]:
    """Every plausible billion-range money figure as (value_vnd, position)."""
    out = []
    for m in re.finditer(r"([\d][\d\.,]{8,})\s*(?:đồng|dong|vnd)", html, re.IGNORECASE):
        digits = re.sub(r"[^\d]", "", m.group(1))
        if not digits:
            continue
        v = int(digits)
        if MIN_JACKPOT_VND <= v <= MAX_JACKPOT_VND:
            out.append((v, m.start()))
    return out


def _extract_jackpot_vnd(html: str) -> int | None:
    """Prefer the money figure that sits closest AFTER a 'Jackpot'/'Độc Đắc'
    label (within a window) instead of blindly taking the largest number on
    the page -- these pages also list sales totals, other games' prizes, and
    estimated figures, so 'max' routinely grabbed the wrong number and could
    return a stale/unrelated value. Falls back to the largest plausible figure
    only if no labeled candidate is found."""
    money = _money_matches(html)
    if not money:
        return None

    low = html.lower()
    label_pos = [m.start() for lab in _JACKPOT_LABELS for m in re.finditer(re.escape(lab), low)]

    if label_pos:
        best = None  # (distance_from_label, value)
        for value, pos in money:
            preceding = [lp for lp in label_pos if 0 <= pos - lp <= _LABEL_WINDOW]
            if preceding:
                dist = pos - max(preceding)
                if best is None or dist < best[0]:
                    best = (dist, value)
        if best is not None:
            return best[1]
        # A jackpot label exists but no money figure sits near it -- the page
        # layout likely changed; don't guess a wrong number.
        return None

    # No jackpot label at all: last-resort heuristic (fragile, may be wrong).
    return max(v for v, _ in money)


def _scrape_jackpot_vnd() -> tuple[int | None, str | None]:
    for url in ALL_SOURCES:
        try:
            resp = requests.get(url, timeout=15, headers=_HEADERS)
            resp.raise_for_status()
            amount = _extract_jackpot_vnd(resp.text)
            if amount is not None:
                return amount, url
            print(f"WARNING: fetched {url} but could not find a jackpot figure in it", file=sys.stderr)
        except requests.RequestException as e:
            print(f"WARNING: jackpot check failed for {url}: {e}", file=sys.stderr)
            continue
    print(f"WARNING: all {len(ALL_SOURCES)} jackpot sources failed -- "
          f"treating jackpot as unknown this run (no false alerts).", file=sys.stderr)
    return None, None


def _next_draw_datetime(last_draw_date: str, last_draw_time: str | None):
    """Given the last known draw's date/time, compute the (date, time) of the
    NEXT draw, assuming the strict daily 13:00 / 21:00 alternating schedule."""
    try:
        d = datetime.strptime(last_draw_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    if last_draw_time == "13:00":
        return d, "21:00"
    if last_draw_time == "21:00":
        return d + timedelta(days=1), "13:00"
    return None


def check_jackpot(last_draw_date: str, last_draw_time: str | None) -> dict:
    jackpot_vnd, source = _scrape_jackpot_vnd()
    next_slot = _next_draw_datetime(last_draw_date, last_draw_time)

    is_sharing_round = False
    reason = "insufficient information"

    if jackpot_vnd is None:
        reason = "could not scrape jackpot amount"
    elif next_slot is None:
        reason = "could not determine next draw's date/time slot"
    else:
        next_date, next_time = next_slot
        try:
            last_date_obj = datetime.strptime(last_draw_date, "%Y-%m-%d").date()
        except ValueError:
            last_date_obj = None

        if jackpot_vnd <= THRESHOLD_VND:
            reason = f"jackpot {jackpot_vnd:,} VND has not exceeded 12 billion yet"
        elif next_time != "21:00":
            reason = "next draw is a 13:00 draw, not the 21:00 sharing slot"
        elif last_date_obj is not None and next_date <= last_date_obj:
            reason = "next 21:00 draw is not yet the following calendar day"
        else:
            is_sharing_round = True
            reason = (
                f"jackpot {jackpot_vnd:,} VND exceeds 12 billion and next draw "
                f"({next_date} 21:00) is the following day's 21:00 slot"
            )

    return {
        "source": source,
        "jackpot_vnd": jackpot_vnd,
        "next_draw_date": next_slot[0].isoformat() if next_slot else None,
        "next_draw_time": next_slot[1] if next_slot else None,
        "is_sharing_round": is_sharing_round,
        "reason": reason,
    }


def _self_test_parser():
    """Label-anchored extraction must pick the jackpot, not the biggest number."""
    cases = [
        ("Tổng doanh thu: 45.000.000.000 đồng. Giá trị Jackpot: 6.123.456.789 đồng.",
         6_123_456_789),
        ("Doanh số lũy kế: 250.000.000.000 đồng. Độc Đắc 7.000.000.000 đồng.",
         7_000_000_000),
        ("Giải phụ 2.000.000.000 đồng. Giải khác 3.000.000.000 đồng.",  # no label -> fallback max
         3_000_000_000),
        ("Thông tin Jackpot cập nhật sau." + "x" * 600 + "99.000.000.000 đồng",  # label far -> None
         None),
    ]
    for html, expected in cases:
        got = _extract_jackpot_vnd(html)
        assert got == expected, f"parser: expected {expected}, got {got} for {html[:50]!r}"
    print("jackpot parser self-test: OK")


if __name__ == "__main__":
    import json
    _self_test_parser()
    print(json.dumps(check_jackpot("2026-07-07", "21:00"), ensure_ascii=False, indent=2))
