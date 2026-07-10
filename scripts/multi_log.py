"""
multi_log.py
-------------
Persistent, append-only log of the 3 tickets published each draw, and the
resolver that fills in real outcomes once they're known.

Format: state/ensemble_log.jsonl, one JSON object per line:
{
  "generated_at": ISO8601, "based_on_draw_id", "based_on_draw_date",
  "target_draw_id",
  "tickets": {"random_fair": {"main":[...], "special":int, "trace":...},
              "random_repeat": {...}, "nhanaz": {...}},
  "jackpot_vnd": int|null,
  "resolved": bool,
  "actual": {"main": [...], "special": int} | null,
  "hits": {"random_fair": {"main_hits", "special_hit"}, ...} | null
}
(Older entries used ensemble/per_strategy/references/hunter keys; resolve_all
still handles them so historical rows keep resolving.)
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
    target draw has now happened. Returns the list of entries resolved on
    THIS call (so callers can e.g. notify on a jackpot-level hit exactly
    once, the run the result first becomes available)."""
    entries = load_log()
    if not entries:
        print("No ensemble_log.jsonl yet -- nothing to resolve.")
        return []

    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    draws_by_id = {d.draw_id: d for d in parse_draws(rows)}

    newly_resolved = []
    for entry in entries:
        if entry.get("resolved"):
            continue
        target_id = entry.get("target_draw_id") or _next_draw_id(entry["based_on_draw_id"])
        actual = draws_by_id.get(target_id)
        if actual is None:
            continue

        hits = {}
        # current format: the 3 tickets
        for key, t in (entry.get("tickets") or {}).items():
            if t and t.get("main") and t.get("special") is not None:
                hits[key] = match_count(t["main"], t["special"], actual)
        # --- legacy formats (so historical rows keep resolving) ---
        ens = entry.get("ensemble")
        if ens and ens.get("main") and ens.get("special") is not None:
            hits["ensemble"] = match_count(ens["main"], ens["special"], actual)
        for name, pick in (entry.get("per_strategy") or {}).items():
            hits[name] = match_count(pick["main"], pick["special"], actual)
        for key, ref in (entry.get("references") or {}).items():
            if ref and ref.get("main") and ref.get("special") is not None:
                hits[f"ref_{key}"] = match_count(ref["main"], ref["special"], actual)
        hunter = entry.get("hunter")
        if hunter and hunter.get("main") and hunter.get("special") is not None:
            hits["jackpot_hunter"] = match_count(hunter["main"], hunter["special"], actual)

        entry["actual"] = {
            "main": actual.numbers,
            "special": actual.special,
            "draw_date": actual.draw_date,
        }
        entry["hits"] = hits
        entry["resolved"] = True
        newly_resolved.append(entry)

    if newly_resolved:
        save_log(entries)
    print(f"Resolved {len(newly_resolved)} entries in ensemble_log.jsonl")
    return newly_resolved


if __name__ == "__main__":
    resolve_all()
