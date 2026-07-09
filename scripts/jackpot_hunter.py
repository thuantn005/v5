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
not something we're guessing at), takes the union of every number their
various strategies recommended for the upcoming draw, and produces a pick
that:
  1. Starts from OUR OWN ensemble score (so it's still informed by our
     own multi-model analysis, not just "anything but theirs").
  2. Completely excludes any number in the reference site's recommended
     set, reducing (not eliminating -- other tools/players exist too)
     the chance of an accidental crowd collision.

If the ledger can't be fetched (network issue, repo restructured), this
falls back to the plain ensemble pick with no exclusions, and says so
explicitly rather than silently guessing.
"""

from __future__ import annotations
import json

import requests

from ensemble import ensemble_scores, load_tuned_params
from strategies import pick_topk
from model import MAIN_MIN, MAIN_MAX, SPECIAL_MIN, SPECIAL_MAX, MAIN_K, SPECIAL_K

LEDGER_URL = (
    "https://raw.githubusercontent.com/NhanAZ-Data/"
    "vietlott-prediction-web/main/predictions/ledger.jsonl"
)
PRODUCT = "lotto535"


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


def hunter_predict(history, tuned_params=None) -> dict:
    tuned_params = tuned_params or load_tuned_params()

    main_ensemble, _ = ensemble_scores(history, MAIN_MIN, MAIN_MAX, MAIN_K, False, tuned_params)
    special_ensemble, _ = ensemble_scores(history, SPECIAL_MIN, SPECIAL_MAX, SPECIAL_K, True, tuned_params)

    reference = fetch_reference_predictions()

    if reference is None:
        return {
            "main_numbers": pick_topk(main_ensemble, 5),
            "special_number": pick_topk(special_ensemble, 1)[0],
            "excluded_main": [],
            "excluded_special": [],
            "reference_available": False,
        }

    remaining_main = {n: s for n, s in main_ensemble.items() if n not in reference["main"]}
    remaining_special = {n: s for n, s in special_ensemble.items() if n not in reference["special"]}

    # Safety net: if the reference set is somehow huge and empties the pool,
    # fall back to the full pool rather than erroring out.
    if len(remaining_main) < 5:
        remaining_main = main_ensemble
    if not remaining_special:
        remaining_special = special_ensemble

    return {
        "main_numbers": pick_topk(remaining_main, 5),
        "special_number": pick_topk(remaining_special, 1)[0],
        "excluded_main": sorted(reference["main"]),
        "excluded_special": sorted(reference["special"]),
        "reference_available": True,
        "reference_generated_at": reference["generated_at"],
    }


if __name__ == "__main__":
    import csv
    from model import parse_draws
    with open("data/all.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    draws = parse_draws(rows)
    result = hunter_predict(draws)
    print(json.dumps(result, ensure_ascii=False, indent=2))
