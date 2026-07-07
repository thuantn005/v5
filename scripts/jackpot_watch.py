"""
jackpot_watch.py
------------------
Adds a "sănn kỳ chia giải" (hunt the jackpot-sharing round) early-warning
layer on top of jackpot_check.py.

jackpot_check.py only answers "is the NEXT draw the sharing round" (true
only on the exact day). This module additionally tracks jackpot state
across runs (state/jackpot_state.json) so we can send ONE early heads-up
notification the moment the jackpot first crosses 12 billion VND --
before the actual sharing day arrives -- without spamming on every run
while it stays above threshold.

State machine (per "cycle" = period between jackpot resets):
  - jackpot <= 12B  -> below threshold, "alerted" flag reset to False
  - jackpot  > 12B and not yet alerted this cycle -> fire early alert,
    set alerted = True
  - jackpot  > 12B and already alerted -> stay silent (avoid spam) until
    the actual sharing-round day, which is handled separately by
    jackpot_check.is_sharing_round
  - jackpot drops back <= 12B (meaning it was won/paid out) -> new cycle,
    flag resets automatically
"""

import json
import os

STATE_PATH = "state/jackpot_state.json"
THRESHOLD_VND = 12_000_000_000


def _load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {"alerted_this_cycle": False, "last_jackpot_vnd": None}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_state(state: dict):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_early_alert(jackpot_vnd: int | None) -> dict:
    """
    Returns {"should_alert": bool, "jackpot_vnd": int|None} and updates
    state/jackpot_state.json accordingly. Call this once per run, after
    jackpot_check.check_jackpot() has given you a jackpot_vnd figure
    (may be None if scraping failed -- in which case we stay silent and
    don't touch the state, since we can't confidently tell what's going on).
    """
    if jackpot_vnd is None:
        return {"should_alert": False, "jackpot_vnd": None}

    state = _load_state()
    should_alert = False

    if jackpot_vnd <= THRESHOLD_VND:
        state["alerted_this_cycle"] = False
    else:
        if not state.get("alerted_this_cycle"):
            should_alert = True
            state["alerted_this_cycle"] = True

    state["last_jackpot_vnd"] = jackpot_vnd
    _save_state(state)

    return {"should_alert": should_alert, "jackpot_vnd": jackpot_vnd}


if __name__ == "__main__":
    print(check_early_alert(12_500_000_000))
    print(check_early_alert(12_600_000_000))  # should NOT alert again
    print(check_early_alert(5_000_000_000))    # cycle resets
