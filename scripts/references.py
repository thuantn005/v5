"""
references.py
--------------
Reference & fair-comparison predictions shown ALONGSIDE the ensemble. These
replace the former "Jackpot Hunter" block. None of them are ensemble members
or claim any edge -- they are yardsticks so the ensemble can be read against
honest baselines and against the public reference site:

  - random_fair   : "Mốc so sánh công bằng" -- 5 DISTINCT numbers picked
                    uniformly at random. This is the correct null model:
                    every ticket has identical odds, so any model that can't
                    beat this over time has no real skill.
  - random_repeat : "Chọn ngẫu nhiên (có lặp lại)" -- 5 numbers sampled WITH
                    replacement (duplicates allowed), a deliberately WORSE
                    baseline since duplicate slots waste coverage.
  - nhanaz        : mirror of the public nhanaz-data prediction site
                    (https://nhanaz-data.github.io/vietlott-prediction-web),
                    the consensus (most-recommended 5) of their latest
                    published strategy predictions -- so you can compare the
                    ensemble directly against what that popular tool suggests.

Picks are seeded by the target draw id, so a given draw's random baselines
are reproducible/auditable across reruns.
"""

from __future__ import annotations
import json
import random
from collections import Counter

import requests

from model import MAIN_MIN, MAIN_MAX, SPECIAL_MIN, SPECIAL_MAX, MAIN_K, SPECIAL_K

LEDGER_URL = (
    "https://raw.githubusercontent.com/NhanAZ-Data/"
    "vietlott-prediction-web/main/predictions/ledger.jsonl"
)
PRODUCT = "lotto535"


def random_fair_pick(rng) -> dict:
    """5 distinct numbers + special, uniform at random (the fair null model)."""
    main = sorted(rng.sample(range(MAIN_MIN, MAIN_MAX + 1), MAIN_K))
    return {"main": main, "special": rng.randint(SPECIAL_MIN, SPECIAL_MAX)}


def random_repeat_pick(rng) -> dict:
    """5 numbers sampled WITH replacement (duplicates allowed) + special."""
    main = sorted(rng.randint(MAIN_MIN, MAIN_MAX) for _ in range(MAIN_K))
    return {"main": main, "special": rng.randint(SPECIAL_MIN, SPECIAL_MAX)}


def fetch_nhanaz_prediction() -> dict | None:
    """Mirror the nhanaz-data site's current prediction: fetch its locked,
    hash-chained ledger, take the latest batch of per-strategy predictions,
    and return the CONSENSUS (the 5 most-recommended main numbers + the most
    -recommended special). Returns None if unavailable."""
    try:
        resp = requests.get(LEDGER_URL, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: could not fetch nhanaz ledger: {e}")
        return None

    entries = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("product") == PRODUCT and obj.get("event_type") == "prediction":
            entries.append(obj)
    if not entries:
        return None

    entries.sort(key=lambda e: e["generated_at"])
    latest_ts = entries[-1]["generated_at"]
    latest_batch = [e for e in entries if e["generated_at"] == latest_ts]

    main_counter, special_counter = Counter(), Counter()
    for e in latest_batch:
        for n in e["prediction"]["numbers"]:
            main_counter[n] += 1
        for s in e["prediction"]["special_numbers"]:
            special_counter[s] += 1

    if len(main_counter) < MAIN_K:
        return None
    main = sorted(n for n, _ in main_counter.most_common(MAIN_K))
    special = special_counter.most_common(1)[0][0] if special_counter else None
    return {"main": main, "special": special, "generated_at": latest_ts,
            "n_strategies": len(latest_batch)}


def compute_references(target_draw_id: str) -> dict:
    """Build all three reference predictions for the given target draw."""
    try:
        seed = int(target_draw_id)
    except (TypeError, ValueError):
        seed = hash(target_draw_id)
    rng = random.Random(seed)

    refs = {
        "random_fair": {"label": "Mốc so sánh công bằng (ngẫu nhiên, không lặp)",
                        **random_fair_pick(rng)},
        "random_repeat": {"label": "Chọn ngẫu nhiên (có thể lặp lại)",
                          **random_repeat_pick(rng)},
    }

    nh = fetch_nhanaz_prediction()
    if nh and nh.get("main") and nh.get("special") is not None:
        refs["nhanaz"] = {"label": "Giống nhanaz-data (đồng thuận công cụ tham khảo)",
                          "main": nh["main"], "special": nh["special"],
                          "available": True, "generated_at": nh.get("generated_at")}
    else:
        refs["nhanaz"] = {"label": "Giống nhanaz-data (đồng thuận công cụ tham khảo)",
                          "main": None, "special": None, "available": False}
    return refs


if __name__ == "__main__":
    print(json.dumps(compute_references("00999"), ensure_ascii=False, indent=2))
