"""
jackpot_check.py
-----------------
Best-effort check for Lotto 5/35's jackpot-sharing draw ("ky chia giai").

Background (public rules, see vietlott.vn):
  - Jackpot starts at 6 billion VND and accumulates if unclaimed.
  - Once it passes 12 billion VND with no winner, the NEXT day's 21:00 draw
    is designated the "ky chia giai" (jackpot-sharing draw), where the
    jackpot pool gets distributed across lower prize tiers even without a
    5/5 match.

This script tries to scrape the current jackpot figure from Vietlott's
public Lotto 5/35 page. Page structure on lottery sites changes often and
without notice, so this is intentionally defensive: if scraping fails or
the figure can't be confidently parsed, it returns is_jackpot_round=False
rather than guessing -- we never want to send a false "jackpot" alert.
"""

import re
import sys
import requests

URL = "https://vietlott.vn/vi/choi/lotto535/gioi-thieu-san-pham-535"
FALLBACK_URL = "https://xsmn.mobi/xs-lotto-5-35.html"
THRESHOLD_VND = 12_000_000_000


def _extract_jackpot_vnd(html: str) -> int | None:
    # Look for patterns like "12.345.678.900 đồng" or "12,345,678,900 dong"
    matches = re.findall(r"([\d][\d\.,]{8,})\s*(?:đồng|dong|vnd)", html, re.IGNORECASE)
    candidates = []
    for m in matches:
        digits = re.sub(r"[^\d]", "", m)
        if digits:
            candidates.append(int(digits))
    # Jackpot figures are large (billions); filter out noise
    plausible = [c for c in candidates if 1_000_000_000 <= c <= 500_000_000_000]
    if not plausible:
        return None
    return max(plausible)


def check_jackpot() -> dict:
    for url in (URL, FALLBACK_URL):
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            amount = _extract_jackpot_vnd(resp.text)
            if amount is not None:
                return {
                    "source": url,
                    "jackpot_vnd": amount,
                    "is_sharing_round_likely": amount >= THRESHOLD_VND,
                }
        except requests.RequestException as e:
            print(f"WARNING: jackpot check failed for {url}: {e}", file=sys.stderr)
            continue
    return {"source": None, "jackpot_vnd": None, "is_sharing_round_likely": False}


if __name__ == "__main__":
    import json
    print(json.dumps(check_jackpot(), ensure_ascii=False, indent=2))
