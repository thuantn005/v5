"""
jackpot_hunter.py
-------------------
"Người săn Jackpot" mode.

IMPORTANT: this does NOT increase your odds of winning. Every 5-number
combination has identical probability. What it DOES address is a real
economic consideration: Vietlott jackpots are pari-mutuel -- if multiple
tickets match the jackpot in the same draw, they SPLIT the pool. A
publicly available prediction tool (like nhanaz-data's site) may have many
users independently picking the same "recommended" numbers. If you win
using those same numbers, you have a higher chance of splitting with them.

This module fetches the reference site's latest LOCKED prediction ledger
(predictions/ledger.jsonl -- a public, hash-chained, pre-registered log,
not something we're guessing at), then asks Claude (claude_predict.py) for
several DIVERSE number sets that completely exclude every number in the
reference site's recommended set -- giving the user multiple ticket
options to buy for a jackpot-sharing round, all avoiding the same crowd
collision risk.

If the ledger can't be fetched (network issue, repo restructured), this
falls back to a plain Claude pick with no exclusions, and says so
explicitly rather than silently guessing.
"""

from __future__ import annotations
import json

import requests

from claude_predict import claude_pick
from model import Draw

LEDGER_URL = (
    "https://raw.githubusercontent.com/NhanAZ-Data/"
    "vietlott-prediction-web/main/predictions/ledger.jsonl"
)
PRODUCT = "lotto535"
N_HUNTER_SETS = 5


def fetch_reference_predictions() -> dict | None:
    """Fetch the reference site's most recent locked prediction batch for
    lotto535. Returns {"main": set[int], "special": set[int], "generated_at": str}
    or None if unavailable."""
    try:
        resp = requests.get(LEDGER_URL, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: could not fetch reference ledger: {e}")
        return None

    lotto_entries = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("product") == PRODUCT and obj.get("event_type") == "prediction":
            lotto_entries.append(obj)

    if not lotto_entries:
        return None

    lotto_entries.sort(key=lambda e: e["generated_at"])
    latest_ts = lotto_entries[-1]["generated_at"]
    latest_batch = [e for e in lotto_entries if e["generated_at"] == latest_ts]

    main_set, special_set = set(), set()
    for e in latest_batch:
        main_set.update(e["prediction"]["numbers"])
        special_set.update(e["prediction"]["special_numbers"])

    return {"main": main_set, "special": special_set, "generated_at": latest_ts,
            "n_strategies": len(latest_batch)}


def hunter_predict(history: list[Draw], n_sets: int = N_HUNTER_SETS) -> dict:
    """Returns multiple diverse ticket sets for a jackpot-sharing round,
    each excluding the public reference tool's recommended numbers.

    {
      "sets": [{"main": [...], "special": int, "rationale": str}, ...],
      "excluded_main": [...], "excluded_special": [...],
      "reference_available": bool,
      "reference_generated_at": str | None,
    }
    """
    reference = fetch_reference_predictions()
    exclude_main = reference["main"] if reference else set()
    exclude_special = reference["special"] if reference else set()

    sets = claude_pick(history, n_sets=n_sets, exclude_main=exclude_main, exclude_special=exclude_special)

    return {
        "sets": sets or [],
        "excluded_main": sorted(exclude_main),
        "excluded_special": sorted(exclude_special),
        "reference_available": reference is not None,
        "reference_generated_at": reference["generated_at"] if reference else None,
    }


if __name__ == "__main__":
    import csv
    from model import parse_draws
    with open("data/all.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    draws = parse_draws(rows)
    result = hunter_predict(draws)
    print(json.dumps(result, ensure_ascii=False, indent=2))
