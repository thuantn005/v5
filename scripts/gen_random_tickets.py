#!/usr/bin/env python3
"""gen_random_tickets.py — sinh các nhóm vé có seed cho dashboard.

Xuất docs/random_tickets.json gồm:
  - 2 mục ngẫu nhiên (baseline): fair (không lặp) + repeat (có lặp).
  - Nhóm "không lặp": N_FAIR vé, 5 số phân biệt (ngẫu nhiên đều).
  - Nhóm "có lặp":   N_REPEAT vé, 5 số cho phép trùng.
  - Nhóm "kết hợp 3 dấu hiệu lịch sử": N_SIGNAL vé, lấy mẫu theo trọng số kết
    hợp: (1) SỐ NÓNG (tần suất), (2) SỐ QUÁ HẠN (lâu chưa ra), (3) SỐ ĐỒNG HÀNH
    (hay xuất hiện cùng nhóm số của kỳ gần nhất). Tính walk-forward: mỗi kỳ chỉ
    dùng dữ liệu TRƯỚC kỳ đó -> thống kê/đối chiếu không nhìn trộm tương lai.

MỖI vé đều có:
  - last_result: đối chiếu kết quả kỳ VỪA QUAY (số đã chọn vs thực tế).
  - recent (THỐNG KÊ): qua N kỳ gần nhất — TB số chính khớp/kỳ + số lần trúng ĐB.

Lưu ý trung thực: mọi vé đều có xác suất trúng như nhau (1/324.632). Các "dấu
hiệu lịch sử" KHÔNG tạo lợi thế dự đoán (kỳ quay độc lập) — đây chỉ là cách chọn
số có hệ thống, tái lập & đối chiếu được, KHÔNG phải công cụ dự đoán.
"""
import argparse
import csv
import datetime
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from references import _fair_from_seed, REPEAT_SEED_OFFSET  # noqa: E402

TICKET_SEED_STRIDE = 10_000_000
SIGNAL_SEED_OFFSET = 3_000_000_000
N_FAIR = 500
N_REPEAT = 500
N_SIGNAL = 500
RECENT_N = 20  # số kỳ gần nhất để tính thống kê

MAIN_MIN, MAIN_MAX, MAIN_K = 1, 35, 5
SPECIAL_MIN, SPECIAL_MAX = 1, 12


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


# ── Vé ngẫu nhiên (LUÔN 5 số khác nhau — hợp lệ) ─────────────────────────────
def _gen_distinct(offset: int, idx: int, draw_id: int):
    """Vé 5 SỐ KHÁC NHAU, tái lập từ seed = draw_id + offset + idx*STRIDE.
    'Lặp lại' được điều khiển ở mức NHÓM (cho phép trùng vé hay không), KHÔNG
    phải bằng cách nhét số trùng vào một vé."""
    t = _fair_from_seed(draw_id + offset + idx * TICKET_SEED_STRIDE)
    return t["main"], t["special"]


# ── Kết hợp 3 dấu hiệu lịch sử ───────────────────────────────────────────────
def _norm(v):
    mx, mn = max(v), min(v)
    if mx == mn:
        return [1.0] * len(v)
    return [(x - mn) / (mx - mn) for x in v]


def _signal_weights(draws: dict, draw_id: int):
    """Trọng số mỗi số (1..35) kết hợp 3 dấu hiệu, CHỈ dùng dữ liệu < draw_id."""
    hist = [draws[d] for d in sorted(draws) if d < draw_id]
    if len(hist) < 30:
        return [1.0] * 35, [1.0] * 12  # chưa đủ lịch sử -> đều
    total = len(hist)
    freq = Counter()
    last_seen = {}
    for pos, dr in enumerate(hist):
        for n in dr["numbers"]:
            freq[n] += 1
            last_seen[n] = pos
    # 1) SỐ NÓNG: tần suất xuất hiện
    hot = [freq.get(n, 0) for n in range(MAIN_MIN, MAIN_MAX + 1)]
    # 2) SỐ QUÁ HẠN: số kỳ kể từ lần cuối xuất hiện (chưa từng ra = quá hạn tối đa)
    overdue = [(total - 1 - last_seen.get(n, -1)) for n in range(MAIN_MIN, MAIN_MAX + 1)]
    # 3) SỐ ĐỒNG HÀNH: hay xuất hiện cùng nhóm số của kỳ gần nhất
    recent_nums = set(hist[-1]["numbers"])
    comp = [0] * 35
    for dr in hist:
        if set(dr["numbers"]) & recent_nums:
            for n in dr["numbers"]:
                comp[n - 1] += 1
    h, o, c = _norm(hot), _norm(overdue), _norm(comp)
    # +0.1 sàn để mọi số vẫn có thể được chọn (không loại trừ hoàn toàn)
    w = [0.1 + h[i] + o[i] + c[i] for i in range(35)]
    # số đặc biệt: theo tần suất
    sfreq = Counter(dr["special"] for dr in hist if dr["special"] is not None)
    sw = [0.1 + sfreq.get(s, 0) for s in range(SPECIAL_MIN, SPECIAL_MAX + 1)]
    return w, sw


def _wsample(rng: random.Random, weights, k: int):
    """Lấy mẫu k số phân biệt (1..len) theo trọng số, không lặp."""
    idxs = list(range(len(weights)))
    w = list(weights)
    chosen = []
    for _ in range(k):
        total = sum(w[i] for i in idxs)
        r = rng.random() * total
        acc = 0.0
        pick = idxs[-1]
        pos = len(idxs) - 1
        for j, i in enumerate(idxs):
            acc += w[i]
            if r <= acc:
                pick, pos = i, j
                break
        chosen.append(pick + 1)
        idxs.pop(pos)
    return sorted(chosen)


def _wchoice(rng: random.Random, weights):
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for i, wv in enumerate(weights):
        acc += wv
        if r <= acc:
            return i + 1
    return len(weights)


def _make_signal_gen(draws: dict, needed_draw_ids):
    """Trả về hàm gen(idx, draw_id) cho vé kết hợp dấu hiệu, có cache trọng số."""
    cache = {d: _signal_weights(draws, d) for d in needed_draw_ids}

    def gen(idx: int, draw_id: int):
        w, sw = cache.get(draw_id) or _signal_weights(draws, draw_id)
        rng = random.Random(draw_id + SIGNAL_SEED_OFFSET + idx * TICKET_SEED_STRIDE)
        return _wsample(rng, w, MAIN_K), _wchoice(rng, sw)

    return gen


# ── Đối chiếu & thống kê ─────────────────────────────────────────────────────
def _compare(predicted_main, predicted_special, draw_id: int, draws: dict) -> dict | None:
    if draw_id not in draws:
        return None
    actual = draws[draw_id]
    main_hits = len(set(predicted_main) & set(actual["numbers"]))
    special_hit = (predicted_special == actual["special"]) if actual["special"] is not None else False
    return {
        "draw_id": draw_id, "draw_date": actual["draw_date"],
        "actual": actual["numbers"], "actual_special": actual["special"],
        "predicted": predicted_main, "predicted_special": predicted_special,
        "main_hits": main_hits, "special_hit": bool(special_hit),
    }


def _recent_ids(draws: dict, upto_draw: int, n: int):
    return sorted((d for d in draws if d <= upto_draw), reverse=True)[:n]


def _recent_stats(gen_fn, idx: int, draws: dict, recent_ids) -> dict:
    """Thống kê chỉ tính TRÚNG khi khớp >=3 số chính (giải thấp nhất)."""
    cnt = sp = best = 0
    tier = {3: 0, 4: 0, 5: 0}
    for d in recent_ids:
        main, special = gen_fn(idx, d)
        c = _compare(main, special, d, draws)
        if c:
            cnt += 1
            mh = c["main_hits"]
            best = max(best, mh)
            if mh >= 3:
                tier[mh] = tier.get(mh, 0) + 1
            if c["special_hit"]:
                sp += 1
    return {
        "n": cnt,
        "wins": tier[3] + tier[4] + tier[5],  # số lần trúng >=3 số
        "tier3": tier[3], "tier4": tier[4], "tier5": tier[5],
        "best": best, "special_hits": sp,
    }


def _build_ticket(gen_fn, idx: int, next_draw: int, prev_draw: int, draws: dict,
                  tid: str, recent_ids, seed_val: int) -> dict:
    main, sp = gen_fn(idx, next_draw)
    return {
        "id": tid, "seed": seed_val,
        "numbers": main, "special": sp,
        "trace": f"L535-{next_draw}-{tid}",
        "last_result": _compare(*gen_fn(idx, prev_draw), prev_draw, draws),
        "recent": _recent_stats(gen_fn, idx, draws, recent_ids),
    }


def _rank(t):
    """Xếp hạng: SỐ LẦN trúng >=3 số nhiều nhất lên đầu, rồi tới hạng giải cao,
    rồi số khớp tốt nhất và trúng ĐB."""
    r = t.get("recent") or {}
    tierscore = r.get("tier5", 0) * 1000 + r.get("tier4", 0) * 100 + r.get("tier3", 0) * 10
    return (r.get("wins", 0), tierscore, r.get("best", 0), r.get("special_hits", 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/all.csv")
    ap.add_argument("--out", default="docs/random_tickets.json")
    ap.add_argument("--fair", type=int, default=N_FAIR)
    ap.add_argument("--repeat", type=int, default=N_REPEAT)
    ap.add_argument("--signal", type=int, default=N_SIGNAL)
    ap.add_argument("--recent-n", type=int, default=RECENT_N)
    ap.add_argument("--draw", type=int, help="kỳ cần sinh vé (mặc định: kỳ mới nhất + 1)")
    a = ap.parse_args()

    draws = _load_draws(a.csv)
    if not draws:
        sys.exit(f"Không đọc được kỳ nào từ {a.csv}")
    next_draw = a.draw or max(draws) + 1
    prev_draw = next_draw - 1
    recent_ids = _recent_ids(draws, prev_draw, a.recent_n)

    def distinct_gen(offset):
        return lambda idx, d: _gen_distinct(offset, idx, d)

    fair_gen = distinct_gen(0)                     # nhóm KHÔNG trùng vé
    repeat_gen = distinct_gen(REPEAT_SEED_OFFSET)  # nhóm CHO PHÉP trùng vé
    # vé dấu hiệu cần trọng số ở next_draw + tất cả kỳ dùng cho thống kê
    signal_gen = _make_signal_gen(draws, set([next_draw]) | set(recent_ids))

    def build_group(gen_fn, count, prefix, offset_base, *, unique):
        """unique=True: bỏ các vé TRÙNG NHAU (theo bộ số kỳ tới) -> 500 vé khác
        nhau. unique=False: giữ nguyên, cho phép trùng vé."""
        items, seen, i = [], set(), 0
        while len(items) < count and i < count * 20:
            i += 1
            main, sp = gen_fn(i, next_draw)
            if unique:
                key = (tuple(main), sp)
                if key in seen:
                    continue
                seen.add(key)
            tid = f"{prefix}{len(items) + 1:03d}"
            items.append(_build_ticket(gen_fn, i, next_draw, prev_draw, draws, tid,
                                       recent_ids, next_draw + offset_base + i * TICKET_SEED_STRIDE))
        items.sort(key=_rank, reverse=True)  # vé trúng nhiều lên đầu
        return items

    fair_tickets = build_group(fair_gen, a.fair, "F", 0, unique=True)
    repeat_tickets = build_group(repeat_gen, a.repeat, "R", REPEAT_SEED_OFFSET, unique=False)
    signal_tickets = build_group(signal_gen, a.signal, "S", SIGNAL_SEED_OFFSET, unique=False)

    # baseline (idx=0) — cũng là 5 số khác nhau hợp lệ
    baselines = [
        {**_build_ticket(fair_gen, 0, next_draw, prev_draw, draws, "FAIR", recent_ids, next_draw),
         "name": "Mốc so sánh công bằng (5 số khác nhau)", "badge": "RANDOM"},
        {**_build_ticket(repeat_gen, 0, next_draw, prev_draw, draws, "REPEAT", recent_ids,
                         next_draw + REPEAT_SEED_OFFSET),
         "name": "Chọn ngẫu nhiên (có thể trùng vé)", "badge": "RANDOM"},
    ]

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "next_draw": next_draw, "prev_draw": prev_draw, "recent_n": a.recent_n,
        "disclaimer": ("Mọi vé đều gồm 5 SỐ KHÁC NHAU (hợp lệ) — 'lặp lại' nghĩa là có thể "
                       "trùng VÉ, KHÔNG phải trùng số trong một vé. Mọi vé có xác suất trúng "
                       "như nhau (1/324.632); các 'dấu hiệu lịch sử' KHÔNG tạo lợi thế dự đoán "
                       "(kỳ quay độc lập). Chơi có trách nhiệm."),
        "baselines": baselines,
        "groups": [
            {"label": f"{len(fair_tickets)} vé KHÔNG trùng nhau", "method": "fair",
             "note": "500 vé khác nhau · mỗi vé 5 số khác nhau", "tickets": fair_tickets},
            {"label": f"{len(repeat_tickets)} vé ngẫu nhiên (cho phép TRÙNG VÉ)", "method": "repeat",
             "note": "cho phép 2 vé trùng nhau · mỗi vé vẫn 5 số khác nhau", "tickets": repeat_tickets},
            {"label": f"{len(signal_tickets)} vé kết hợp 3 dấu hiệu lịch sử",
             "note": "nóng (tần suất) · quá hạn (lâu chưa ra) · đồng hành (hay ra cùng kỳ gần nhất)",
             "method": "signal", "tickets": signal_tickets},
        ],
    }

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK: 2 baseline + {len(fair_tickets)} không lặp + {len(repeat_tickets)} có lặp + "
          f"{len(signal_tickets)} dấu hiệu cho kỳ #{next_draw} -> {a.out}")


if __name__ == "__main__":
    main()
