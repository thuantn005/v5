"""
multi_log.py
-------------
Persistent, append-only log of every Claude prediction (+ jackpot-round
hunter ticket sets), and the resolver that fills in real outcomes once
they're known.

Format: state/ensemble_log.jsonl, one JSON object per line:
{
  "generated_at": ISO8601, "based_on_draw_id", "based_on_draw_date",
  "target_draw_id",
  "claude": {"main": [...], "special": int, "rationale": str} | null,
  "hunter_sets": [{"main": [...], "special": int, "rationale": str}, ...],
  "notified": bool, "jackpot_vnd": int|null,
  "resolved": bool,
  "actual": {"main": [...], "special": int} | null,
  "hits": {"claude": {"main_hits", "special_hit"} | null,
           "hunter_sets": [{"main_hits", "special_hit"}, ...]} | null
}
"""

import csv
import json
import os

from model import parse_draws, match_count

LOG_PATH = "state/ensemble_log.jsonl"
DATA_PATH = "data/all.csv"


def append_prediction(entry: dict):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _next_draw_id(draw_id: str) -> str:
    width = len(draw_id)
    return str(int(draw_id) + 1).zfill(width)


def load_log() -> list[dict]:
    if not os.path.exists(LOG_PATH):
        return []
    entries = []
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def save_log(entries: list[dict]):
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def resolve_all():
    """Fill in actual results + hits for every unresolved log entry whose
    target draw has now happened. Returns number of entries resolved."""
    entries = load_log()
    if not entries:
        print("No ensemble_log.jsonl yet -- nothing to resolve.")
        return 0

    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    draws_by_id = {d.draw_id: d for d in parse_draws(rows)}

    resolved_count = 0
    for entry in entries:
        if entry.get("resolved"):
            continue
        target_id = entry.get("target_draw_id") or _next_draw_id(entry["based_on_draw_id"])
        actual = draws_by_id.get(target_id)
        if actual is None:
            continue

        hits = {}
        claude = entry.get("claude")
        hits["claude"] = match_count(claude["main"], claude["special"], actual) if claude else None
        hits["hunter_sets"] = [
            match_count(s["main"], s["special"], actual) for s in entry.get("hunter_sets", [])
        ]

        entry["actual"] = {
            "main": actual.numbers,
            "special": actual.special,
            "draw_date": actual.draw_date,
        }
        entry["hits"] = hits
        entry["resolved"] = True
        resolved_count += 1

    if resolved_count:
        save_log(entries)
    print(f"Resolved {resolved_count} entries in ensemble_log.jsonl")
    return resolved_count


if __name__ == "__main__":
    resolve_all()
