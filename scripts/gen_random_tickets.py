#!/usr/bin/env python3
"""gen_random_tickets.py — sinh 2 mục ngẫu nhiên + 50 vé ngẫu nhiên có seed.

Xuất docs/random_tickets.json cho dashboard. Mỗi vé:
  - numbers/special: bộ số cho kỳ tới (tái lập được từ seed + draw_id).
  - last_result: đối chiếu với kết quả kỳ VỪA QUAY (số đã chọn vs thực tế,
    trúng mấy số) — cùng bộ luật seed nên hoàn toàn trung thực, không cherry-pick.

Chạy trong CI sau bước cập nhật data:
    python scripts/gen_random_tickets.py --csv data/all.csv --out docs/random_tickets.json

Lưu ý trung thực: mọi vé đều có xác suất trúng như nhau (1/324.632). Đây chỉ là
các bộ số ngẫu nhiên có seed để tái lập & đối chiếu — KHÔNG có edge dự đoán nào.
"""
import argparse
import csv
import datetime
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from references import _fair_from_seed, _repeat_from_seed, REPEAT_SEED_OFFSET  # noqa: E402

# Mỗi vé thứ i (1..N) có seed = draw_id + i * TICKET_SEED_STRIDE, dùng phương
# pháp "fair" (5 số phân biệt). Stride lớn để không đụng seed của fair (i=0) hay
# repeat (+1_000_000).
TICKET_SEED_STRIDE = 10_000_000
N_TICKETS = 50


def _load_draws(csv_path: str) -> dict[int, dict]:
    draws = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                draw_id = int(row["draw_id"])
                result = json.loads(row["result_json"])
                draws[draw_id] = {
                    "numbers": sorted(result["numbers"]),
                    "special": result["special_numbers"][0] if result.get("special_numbers") else None,
                    "draw_date": row.get("draw_date", ""),
                }
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
    return draws


def _compare(predicted_main, predicted_special, draw_id: int, draws: dict) -> dict | None:
    """Đối chiếu một bộ số với kết quả thực tại kỳ `draw_id`."""
    if draw_id not in draws:
        return None
    actual = draws[draw_id]
    main_hits = len(set(predicted_main) & set(actual["numbers"]))
    special_hit = (predicted_special == actual["special"]) if actual["special"] is not None else False
    return {
        "draw_id": draw_id,
        "draw_date": actual["draw_date"],
        "actual": actual["numbers"],
        "actual_special": actual["special"],
        "predicted": predicted_main,
        "predicted_special": predicted_special,
        "main_hits": main_hits,
        "special_hit": bool(special_hit),
    }


def _fair_ticket(seed_base: int, draw_id: int):
    """Vé fair (5 số phân biệt) tái lập từ seed_base tại kỳ draw_id."""
    t = _fair_from_seed(draw_id + seed_base)
    return t["main"], t["special"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/all.csv")
    ap.add_argument("--out", default="docs/random_tickets.json")
    ap.add_argument("--count", type=int, default=N_TICKETS)
    ap.add_argument("--draw", type=int, help="kỳ cần sinh vé (mặc định: kỳ mới nhất + 1)")
    a = ap.parse_args()

    draws = _load_draws(a.csv)
    if not draws:
        sys.exit(f"Không đọc được kỳ nào từ {a.csv}")
    next_draw = a.draw or max(draws) + 1
    prev_draw = next_draw - 1

    # ── 2 mục ngẫu nhiên (giữ nguyên công thức references) ──
    fair = _fair_from_seed(next_draw)
    repeat = _repeat_from_seed(next_draw + REPEAT_SEED_OFFSET)
    fair_prev = _fair_from_seed(prev_draw)
    repeat_prev = _repeat_from_seed(prev_draw + REPEAT_SEED_OFFSET)
    baselines = [
        {
            "id": "fair",
            "name": "Mốc so sánh công bằng (ngẫu nhiên, không lặp)",
            "badge": "RANDOM",
            "numbers": fair["main"], "special": fair["special"],
            "trace": f"L535-{next_draw}-FAIR",
            "last_result": _compare(fair_prev["main"], fair_prev["special"], prev_draw, draws),
        },
        {
            "id": "repeat",
            "name": "Chọn ngẫu nhiên (có thể lặp lại)",
            "badge": "RANDOM",
            "numbers": repeat["main"], "special": repeat["special"],
            "trace": f"L535-{next_draw}-REPEAT",
            "last_result": _compare(repeat_prev["main"], repeat_prev["special"], prev_draw, draws),
        },
    ]

    # ── 50 vé ngẫu nhiên có seed ──
    tickets = []
    for i in range(1, a.count + 1):
        seed_base = i * TICKET_SEED_STRIDE
        main, sp = _fair_ticket(seed_base, next_draw)
        pmain, psp = _fair_ticket(seed_base, prev_draw)
        tickets.append({
            "id": f"R{i:02d}",
            "seed": next_draw + seed_base,
            "numbers": main, "special": sp,
            "trace": f"L535-{next_draw}-R{i:02d}",
            "last_result": _compare(pmain, psp, prev_draw, draws),
        })

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "next_draw": next_draw,
        "prev_draw": prev_draw,
        "count": len(tickets),
        "disclaimer": ("Mọi vé đều có xác suất trúng như nhau (1/324.632) — đây là các bộ "
                       "số ngẫu nhiên có seed để tái lập & đối chiếu trung thực, KHÔNG có "
                       "khả năng dự đoán. Chơi có trách nhiệm."),
        "baselines": baselines,
        "tickets": tickets,
    }

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK: 2 mục ngẫu nhiên + {len(tickets)} vé cho kỳ #{next_draw} -> {a.out}")


if __name__ == "__main__":
    main()
