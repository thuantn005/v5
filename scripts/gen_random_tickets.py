#!/usr/bin/env python3
"""gen_random_tickets.py — sinh các nhóm vé ngẫu nhiên có seed cho dashboard.

Xuất docs/random_tickets.json gồm:
  - 2 mục ngẫu nhiên (baseline): fair (không lặp) + repeat (có lặp).
  - Nhóm "không lặp": N_FAIR vé (mặc định 50), 5 số phân biệt.
  - Nhóm "có lặp":   N_REPEAT vé (mặc định 500), 5 số cho phép trùng.

MỖI vé đều có:
  - last_result: đối chiếu với kết quả kỳ VỪA QUAY (số đã chọn vs thực tế).
  - recent (THỐNG KÊ): qua N kỳ gần nhất — trung bình số chính khớp / kỳ và số
    lần trúng ĐB. Vì mỗi kỳ vé sinh lại từ seed nên đây là đối chiếu trung thực.

Chạy trong CI sau bước cập nhật data:
    python scripts/gen_random_tickets.py --csv data/all.csv --out docs/random_tickets.json

Lưu ý trung thực: mọi vé đều có xác suất trúng như nhau (1/324.632). Đây là các
bộ số ngẫu nhiên có seed để tái lập & đối chiếu — KHÔNG có khả năng dự đoán.
"""
import argparse
import csv
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from references import _fair_from_seed, _repeat_from_seed, REPEAT_SEED_OFFSET  # noqa: E402

# Mỗi vé thứ i có seed lệch i * STRIDE (đủ lớn để các seed không chồng nhau
# giữa fair/repeat và baseline).
TICKET_SEED_STRIDE = 10_000_000
N_FAIR = 50
N_REPEAT = 500
RECENT_N = 20  # số kỳ gần nhất để tính thống kê


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


def _gen(method: str, idx: int, draw_id: int):
    """Bộ số của vé (method, idx) tại kỳ draw_id — tái lập được."""
    if method == "fair":
        t = _fair_from_seed(draw_id + idx * TICKET_SEED_STRIDE)
    else:  # repeat (có lặp)
        t = _repeat_from_seed(draw_id + REPEAT_SEED_OFFSET + idx * TICKET_SEED_STRIDE)
    return t["main"], t["special"]


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


def _recent_stats(method: str, idx: int, draws: dict, upto_draw: int, n: int) -> dict:
    """Thống kê vé (method, idx) qua n kỳ gần nhất <= upto_draw."""
    ids = sorted((d for d in draws if d <= upto_draw), reverse=True)[:n]
    total = sp = cnt = 0
    for d in ids:
        main, special = _gen(method, idx, d)
        c = _compare(main, special, d, draws)
        if c:
            total += c["main_hits"]
            sp += 1 if c["special_hit"] else 0
            cnt += 1
    return {
        "n": cnt,
        "avg_main_hits": round(total / cnt, 3) if cnt else 0.0,
        "special_hits": sp,
    }


def _build_ticket(method: str, idx: int, draw_id: int, prev_draw: int, draws: dict,
                  tid: str, recent_n: int) -> dict:
    main, sp = _gen(method, idx, draw_id)
    return {
        "id": tid,
        "seed": draw_id + (REPEAT_SEED_OFFSET if method == "repeat" else 0) + idx * TICKET_SEED_STRIDE,
        "numbers": main, "special": sp,
        "trace": f"L535-{draw_id}-{tid}",
        "last_result": _compare(*_gen(method, idx, prev_draw), prev_draw, draws),
        "recent": _recent_stats(method, idx, draws, prev_draw, recent_n),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/all.csv")
    ap.add_argument("--out", default="docs/random_tickets.json")
    ap.add_argument("--fair", type=int, default=N_FAIR, help="số vé không lặp")
    ap.add_argument("--repeat", type=int, default=N_REPEAT, help="số vé có lặp")
    ap.add_argument("--recent-n", type=int, default=RECENT_N, help="số kỳ tính thống kê")
    ap.add_argument("--draw", type=int, help="kỳ cần sinh vé (mặc định: kỳ mới nhất + 1)")
    a = ap.parse_args()

    draws = _load_draws(a.csv)
    if not draws:
        sys.exit(f"Không đọc được kỳ nào từ {a.csv}")
    next_draw = a.draw or max(draws) + 1
    prev_draw = next_draw - 1
    rn = a.recent_n

    # ── 2 mục ngẫu nhiên (baseline, idx=0) ──
    baselines = [
        {**_build_ticket("fair", 0, next_draw, prev_draw, draws, "FAIR", rn),
         "name": "Mốc so sánh công bằng (ngẫu nhiên, không lặp)", "badge": "RANDOM"},
        {**_build_ticket("repeat", 0, next_draw, prev_draw, draws, "REPEAT", rn),
         "name": "Chọn ngẫu nhiên (có thể lặp lại)", "badge": "RANDOM"},
    ]

    # ── Nhóm không lặp + có lặp ──
    fair_tickets = [
        _build_ticket("fair", i, next_draw, prev_draw, draws, f"F{i:03d}", rn)
        for i in range(1, a.fair + 1)
    ]
    repeat_tickets = [
        _build_ticket("repeat", i, next_draw, prev_draw, draws, f"R{i:03d}", rn)
        for i in range(1, a.repeat + 1)
    ]

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "next_draw": next_draw,
        "prev_draw": prev_draw,
        "recent_n": rn,
        "disclaimer": ("Mọi vé đều có xác suất trúng như nhau (1/324.632) — đây là các bộ "
                       "số ngẫu nhiên có seed để tái lập & đối chiếu trung thực, KHÔNG có "
                       "khả năng dự đoán. Chơi có trách nhiệm."),
        "baselines": baselines,
        "groups": [
            {"label": f"{len(fair_tickets)} vé ngẫu nhiên KHÔNG lặp", "method": "fair",
             "tickets": fair_tickets},
            {"label": f"{len(repeat_tickets)} vé ngẫu nhiên CÓ lặp", "method": "repeat",
             "tickets": repeat_tickets},
        ],
    }

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK: 2 baseline + {len(fair_tickets)} không lặp + {len(repeat_tickets)} có lặp "
          f"cho kỳ #{next_draw} -> {a.out}")


if __name__ == "__main__":
    main()
