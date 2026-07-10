"""
references.py
--------------
The CORE of the project after it was reduced to "3 vé mỗi kỳ" (3 tickets per
draw). There is no model/ensemble anymore -- every draw we publish exactly
three tickets and later score them against the real result:

  - random_repeat : "Chọn ngẫu nhiên có thể lặp lại" -- 5 numbers sampled
                    WITH replacement (duplicates allowed). A deliberately
                    weaker baseline: duplicate slots waste coverage.
  - random_fair   : "Mốc so sánh công bằng" -- 5 DISTINCT numbers picked
                    uniformly at random. The correct null model: every
                    ticket has identical odds, so this is the honest yardstick
                    everything else is measured against.
  - nhanaz        : "Giống nhanaz-data" -- mirror of the public prediction
                    site https://nhanaz-data.github.io/vietlott-prediction-web
                    (consensus of its latest locked ledger batch).

Reproducibility ("mã lưu vết"): each random ticket carries a trace code and a
fixed integer seed, plus the exact algorithm string, so anyone can regenerate
the identical numbers and audit that they were not cherry-picked. The seeds are
derived only from the target draw id (known in advance), never from the result.

    random_fair   : seed = int(draw_id)
    random_repeat : seed = int(draw_id) + 1_000_000
    both use Python's random.Random(seed):
      main = ... (see FORMULA_* below), special = rng.randint(1, 12)
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

REPEAT_SEED_OFFSET = 1_000_000

FORMULA_FAIR = (
    "rng = random.Random(seed); "
    "main = sorted(rng.sample(range(1, 36), 5)); special = rng.randint(1, 12)"
)
FORMULA_REPEAT = (
    "rng = random.Random(seed); "
    "main = sorted(rng.randint(1, 35) for _ in range(5)); special = rng.randint(1, 12)"
)


def _fair_from_seed(seed: int) -> dict:
    rng = random.Random(seed)
    main = sorted(rng.sample(range(MAIN_MIN, MAIN_MAX + 1), MAIN_K))
    return {"main": main, "special": rng.randint(SPECIAL_MIN, SPECIAL_MAX)}


def _repeat_from_seed(seed: int) -> dict:
    rng = random.Random(seed)
    main = sorted(rng.randint(MAIN_MIN, MAIN_MAX) for _ in range(MAIN_K))
    return {"main": main, "special": rng.randint(SPECIAL_MIN, SPECIAL_MAX)}


def fetch_nhanaz_prediction() -> dict | None:
    """Mirror the nhanaz-data site's current prediction: fetch its locked,
    hash-chained ledger, take the latest batch of per-strategy predictions,
    and return the CONSENSUS (5 most-recommended main numbers + most-recommended
    special). Returns None if unavailable."""
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


def compute_tickets(target_draw_id: str) -> dict:
    """Build the three tickets for the given target draw."""
    try:
        base_seed = int(target_draw_id)
    except (TypeError, ValueError):
        base_seed = abs(hash(target_draw_id)) % (10 ** 9)

    fair_seed = base_seed
    repeat_seed = base_seed + REPEAT_SEED_OFFSET

    tickets = {
        "random_fair": {
            "label": "Mốc so sánh công bằng (ngẫu nhiên, không lặp)",
            **_fair_from_seed(fair_seed),
            "trace": f"L535-{target_draw_id}-FAIR",
            "seed": fair_seed,
            "method": FORMULA_FAIR,
        },
        "random_repeat": {
            "label": "Chọn ngẫu nhiên (có thể lặp lại)",
            **_repeat_from_seed(repeat_seed),
            "trace": f"L535-{target_draw_id}-REPEAT",
            "seed": repeat_seed,
            "method": FORMULA_REPEAT,
        },
    }

    nh = fetch_nhanaz_prediction()
    if nh and nh.get("main") and nh.get("special") is not None:
        tickets["nhanaz"] = {
            "label": "Giống nhanaz-data (đồng thuận công cụ tham khảo)",
            "main": nh["main"], "special": nh["special"],
            "available": True, "generated_at": nh.get("generated_at"),
            "trace": f"nhanaz@{nh.get('generated_at')}",
        }
    else:
        tickets["nhanaz"] = {
            "label": "Giống nhanaz-data (đồng thuận công cụ tham khảo)",
            "main": None, "special": None, "available": False,
        }
    return tickets


def reproduce(trace: str) -> dict | None:
    """Regenerate a random ticket's numbers purely from its trace code, to
    prove reproducibility. Only works for the FAIR/REPEAT traces."""
    parts = trace.split("-")
    if len(parts) != 3 or parts[0] != "L535":
        return None
    draw_id, kind = parts[1], parts[2]
    try:
        base = int(draw_id)
    except ValueError:
        return None
    if kind == "FAIR":
        return _fair_from_seed(base)
    if kind == "REPEAT":
        return _repeat_from_seed(base + REPEAT_SEED_OFFSET)
    return None


if __name__ == "__main__":
    t = compute_tickets("00999")
    print(json.dumps(t, ensure_ascii=False, indent=2))
    # prove the trace codes regenerate the same numbers
    print("reproduce FAIR:", reproduce(t["random_fair"]["trace"]))
    print("reproduce REPEAT:", reproduce(t["random_repeat"]["trace"]))
