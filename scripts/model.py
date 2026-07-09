"""
model.py
--------
Draw parsing and match-counting shared by the rest of the pipeline.

IMPORTANT HONESTY NOTE
----------------------
Lotto 5/35 draws are independent random events. Every 5-number combination
(from 1-35) and every special number (1-12) has an equal chance of being
drawn regardless of past history. Nothing in this project -- including the
Claude-based prediction in claude_predict.py -- changes that.
"""

from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Iterable

MAIN_MIN, MAIN_MAX = 1, 35
SPECIAL_MIN, SPECIAL_MAX = 1, 12
MAIN_K = 5   # numbers drawn per round, from MAIN pool
SPECIAL_K = 1


@dataclass
class Draw:
    draw_id: str
    draw_date: str
    draw_time: str | None     # "13:00" or "21:00", if known
    numbers: list[int]        # 5 main numbers
    special: int               # 1 special number


def parse_draws(rows: Iterable[dict]) -> list[Draw]:
    """Parse CSV rows (as dicts) from the dataset into Draw objects,
    sorted chronologically by draw_id."""
    draws = []
    for row in rows:
        try:
            result = json.loads(row["result_json"])
            numbers = sorted(int(n) for n in result["numbers"])
            special_list = result.get("special_numbers") or []
            special = int(special_list[0]) if special_list else None
            if special is None or len(numbers) != 5:
                continue
            draw_time = None
            try:
                attrs = json.loads(row.get("attributes_json") or "{}")
                draw_time = attrs.get("draw_time")
            except (ValueError, json.JSONDecodeError, TypeError):
                pass
            draws.append(
                Draw(
                    draw_id=row["draw_id"],
                    draw_date=row["draw_date"],
                    draw_time=draw_time,
                    numbers=numbers,
                    special=special,
                )
            )
        except (KeyError, ValueError, json.JSONDecodeError, TypeError):
            continue
    draws.sort(key=lambda d: d.draw_id)
    return draws


def match_count(predicted_main: list[int], predicted_special: int, actual: Draw) -> dict:
    main_hits = len(set(predicted_main) & set(actual.numbers))
    special_hit = int(predicted_special == actual.special)
    return {"main_hits": main_hits, "special_hit": special_hit}
