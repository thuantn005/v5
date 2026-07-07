"""
check_results.py
------------------
Goes through state/predictions_log.csv and, for every past prediction whose
target draw has now actually happened, fills in the real result and computes
how many numbers matched. This is the honest, no-spin accuracy record for
the whole project -- it's committed back to the repo every run so anyone
can audit it directly.

This does NOT send notifications. It just keeps the log truthful.
"""

import csv
import os

from model import parse_draws, match_count

DATA_PATH = "data/all.csv"
LOG_PATH = "state/predictions_log.csv"

FIELDNAMES = [
    "generated_at", "based_on_draw_id", "based_on_draw_date",
    "target_draw_id",
    "predicted_main_numbers", "predicted_special",
    "confidence", "threshold", "jackpot_vnd", "notified",
    "actual_draw_id", "actual_main_numbers", "actual_special",
    "main_hits", "special_hit", "jackpot_match",
]


def _next_draw_id(draw_id: str) -> str:
    width = len(draw_id)
    return str(int(draw_id) + 1).zfill(width)


def load_draws_by_id():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    draws = parse_draws(rows)
    return {d.draw_id: d for d in draws}


def main():
    if not os.path.exists(LOG_PATH):
        print("No predictions_log.csv yet -- nothing to check.")
        return

    draws_by_id = load_draws_by_id()

    with open(LOG_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    updated = 0
    for row in rows:
        # Normalize missing new columns for older rows
        for field in FIELDNAMES:
            row.setdefault(field, "")

        if row.get("actual_draw_id"):
            continue  # already resolved

        target_id = row.get("target_draw_id") or _next_draw_id(row["based_on_draw_id"])
        row["target_draw_id"] = target_id

        actual = draws_by_id.get(target_id)
        if actual is None:
            continue  # that draw hasn't happened / been published yet

        predicted_main = [int(n) for n in row["predicted_main_numbers"].split("-")]
        predicted_special = int(row["predicted_special"])
        hits = match_count(predicted_main, predicted_special, actual)

        row["actual_draw_id"] = actual.draw_id
        row["actual_main_numbers"] = "-".join(f"{n:02d}" for n in actual.numbers)
        row["actual_special"] = f"{actual.special:02d}"
        row["main_hits"] = hits["main_hits"]
        row["special_hit"] = hits["special_hit"]
        row["jackpot_match"] = int(hits["main_hits"] == 5 and hits["special_hit"] == 1)
        updated += 1

    if updated:
        with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

    print(f"Resolved {updated} past prediction(s) against actual results.")

    resolved = [r for r in rows if r.get("actual_draw_id")]
    if resolved:
        total = len(resolved)
        avg_hits = sum(int(r["main_hits"]) for r in resolved) / total
        special_rate = sum(int(r["special_hit"]) for r in resolved) / total
        jackpots = sum(int(r["jackpot_match"]) for r in resolved)
        print(f"Track record so far: {total} predictions resolved, "
              f"avg main-number hits = {avg_hits:.3f} (chance ~= 0.71), "
              f"special-number hit rate = {special_rate:.3f} (chance ~= 1/12 = 0.083), "
              f"full jackpot matches = {jackpots}")


if __name__ == "__main__":
    main()
