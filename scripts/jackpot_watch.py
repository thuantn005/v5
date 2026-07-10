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

This module ALSO covers the "silent blind spot": both the early alert and
jackpot_check.is_sharing_round depend on successfully scraping the jackpot
figure. If every source fails (site down / HTML format changed),
check_jackpot() returns jackpot_vnd=None, is_sharing_round is forced False,
and we would otherwise stay completely silent -- potentially missing the
real sharing round without anyone knowing. check_scrape_alert() fires ONE
heads-up the moment scraping starts failing (using the same state file, key
"scrape_fail_alerted"), stays quiet while it keeps failing, and resets once
scraping recovers.
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


def get_threshold_crossed_date() -> str | None:
    """The date (YYYY-MM-DD) of the draw after which the jackpot first crossed
    12 billion this cycle, or None. jackpot_check uses it to pin the sharing
    round to '21:00 of the following day'."""
    return _load_state().get("threshold_crossed_date")


def check_early_alert(jackpot_vnd: int | None, draw_date: str | None = None) -> dict:
    """
    Returns {"should_alert": bool, "jackpot_vnd": int|None} and updates
    state/jackpot_state.json accordingly. Call this once per run, after
    jackpot_check.check_jackpot() has given you a jackpot_vnd figure
    (may be None if scraping failed -- in which case we stay silent and
    don't touch the state, since we can't confidently tell what's going on).

    `draw_date` is the last completed draw's date; when the jackpot first
    crosses 12B this cycle we record it as `threshold_crossed_date` so the
    sharing round (21:00 of the following day) can be identified. It is
    cleared when the jackpot drops back below 12B (a new cycle).
    """
    if jackpot_vnd is None:
        return {"should_alert": False, "jackpot_vnd": None}

    state = _load_state()
    should_alert = False

    if jackpot_vnd <= THRESHOLD_VND:
        state["alerted_this_cycle"] = False
        state["threshold_crossed_date"] = None
    else:
        if not state.get("alerted_this_cycle"):
            should_alert = True
            state["alerted_this_cycle"] = True
        # Record the crossing day the first time we see >12B this cycle (and
        # keep it stable for the rest of the cycle).
        if not state.get("threshold_crossed_date") and draw_date:
            state["threshold_crossed_date"] = draw_date

    state["last_jackpot_vnd"] = jackpot_vnd
    _save_state(state)

    return {"should_alert": should_alert, "jackpot_vnd": jackpot_vnd}


def check_scrape_alert(jackpot_vnd: int | None) -> dict:
    """
    Returns {"should_alert": bool} and updates state/jackpot_state.json.
    Fires ONE alert when jackpot scraping first fails (jackpot_vnd is None),
    then stays silent while it keeps failing, and resets once a real figure
    is scraped again. This surfaces the otherwise-silent blind spot where we
    can't tell whether the next draw is the sharing round.

    Call once per run, right after jackpot_check.check_jackpot(). Call this
    BEFORE check_early_alert() -- when jackpot_vnd is None, check_early_alert
    returns early without touching the state file, so ordering is safe.
    """
    state = _load_state()
    should_alert = False

    if jackpot_vnd is None:
        if not state.get("scrape_fail_alerted"):
            should_alert = True
            state["scrape_fail_alerted"] = True
    else:
        state["scrape_fail_alerted"] = False

    _save_state(state)
    return {"should_alert": should_alert, "jackpot_vnd": jackpot_vnd}


if __name__ == "__main__":
    print(check_early_alert(12_500_000_000))
    print(check_early_alert(12_600_000_000))  # should NOT alert again
    print(check_early_alert(5_000_000_000))    # cycle resets
    print("--- scrape alert ---")
    print(check_scrape_alert(None))            # scrape failed -> alert once
    print(check_scrape_alert(None))            # still failing -> silent
    print(check_scrape_alert(7_000_000_000))   # recovered -> reset (no alert)
    print(check_scrape_alert(None))            # fails again -> alert once more
