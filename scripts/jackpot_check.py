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


def _extract_jackpot_vnd(html: str) -> int | None:
    matches = re.findall(r"([\d][\d\.,]{8,})\s*(?:đồng|dong|vnd)", html, re.IGNORECASE)
    candidates = []
    for m in matches:
        digits = re.sub(r"[^\d]", "", m)
        if digits:
            candidates.append(int(digits))
    plausible = [c for c in candidates if 1_000_000_000 <= c <= 500_000_000_000]
    if not plausible:
        return None
    return max(plausible)


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


if __name__ == "__main__":
    import json
    print(json.dumps(check_jackpot("2026-07-07", "21:00"), ensure_ascii=False, indent=2))
