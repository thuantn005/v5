#!/usr/bin/env python3
"""jackpot_hunt.py — CÓ JACKPOT KHÔNG? Chơi thử ở quy mô lớn để trả lời dứt điểm.

backtest_zoo.py cho mỗi model đúng 1 vé/kỳ, tổng ~12.000 vé-kỳ — quá ít để
jackpot kịp xuất hiện dù model có giỏi hay không. Script này cho MỖI model bốc
nhiều vé ở MỖI kỳ, đẩy tổng lượt chơi lên hàng trăm nghìn, rồi đếm:

  * phân bố số trúng 0–5 so với xác suất LÝ THUYẾT (siêu bội)
  * Jackpot 2 (5 số chính)     — 1/324.632
  * Jackpot 1 (5 chính + ĐB)   — 1/3.895.584

Nếu model có kỹ năng thật, phân bố phải LỆCH khỏi lý thuyết. Nếu không, nó sẽ
khớp lý thuyết đến từng bậc — và jackpot chỉ xuất hiện đúng bằng tần suất may
rủi, không sớm hơn.

    python3 scripts/jackpot_hunt.py                    # 20 vé/model/kỳ
    python3 scripts/jackpot_hunt.py --tickets 50       # đẩy quy mô lên nữa
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model import parse_draws                                     # noqa: E402
import model_zoo as Z                                             # noqa: E402

DATA_PATH = "data/all.csv"
OUT_PATH = "state/jackpot_hunt.json"

C35_5 = 324632
J1_ODDS = C35_5 * 12                                              # 3.895.584


def _comb(n, k):
    return math.comb(n, k)


# Xác suất trúng đúng h số chính khi bốc 5 số từ 35 (phân phối siêu bội)
TIER_P = [_comb(5, h) * _comb(30, 5 - h) / C35_5 for h in range(6)]


def load_draws():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        return parse_draws(list(csv.DictReader(f)))


def _score_stream(name, draws, cache, cache_sp, test_ids, window, refit):
    """Sinh (t, điểm 5 số chính, điểm số ĐB) cho từng kỳ kiểm tra."""
    if name in Z.SUPERVISED_MODELS:
        _, factory = Z.SUPERVISED_MODELS[name]
        model = mean = std = model_sp = mean_sp = std_sp = None
        for step, t in enumerate(test_ids):
            if step % refit == 0 or model is None:
                lo = max(0, t - window)
                X, y = Z.build_dataset(draws, cache, lo, t, Z.MAIN_MIN, Z.MAIN_MAX, False)
                if not X:
                    continue
                Xs, mean, std = Z.standardise(X)
                model = factory().fit(Xs, y)
                Xp, yp = Z.build_dataset(draws, cache_sp, lo, t,
                                         Z.SPECIAL_MIN, Z.SPECIAL_MAX, True)
                Xps, mean_sp, std_sp = Z.standardise(Xp)
                model_sp = factory().fit(Xps, yp)
            rows, rows_sp = cache.get(t), cache_sp.get(t)
            if rows is None or rows_sp is None:
                continue
            yield (t,
                   model.predict(Z.apply_standardise(rows, mean, std)),
                   model_sp.predict(Z.apply_standardise(rows_sp, mean_sp, std_sp)))
    else:
        _, fn = Z.CUSTOM_MODELS[name]
        for t in test_ids:
            lo = max(0, t - window)
            yield (t,
                   fn(draws, t, lo, Z.MAIN_MIN, Z.MAIN_MAX, False, seed=t),
                   fn(draws, t, lo, Z.SPECIAL_MIN, Z.SPECIAL_MAX, True, seed=t))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickets", type=int, default=20, help="số vé mỗi model mỗi kỳ")
    ap.add_argument("--test", type=int, default=600, help="số kỳ kiểm tra")
    ap.add_argument("--window", type=int, default=200)
    ap.add_argument("--refit", type=int, default=5)
    ap.add_argument("--temp", type=float, default=Z.DEFAULT_TEMPERATURE)
    a = ap.parse_args()

    draws = load_draws()
    T = len(draws)
    if T < a.window + a.test + 5:
        a.test = max(20, T - a.window - 5)
    test_ids = list(range(T - a.test, T))
    first = max(0, test_ids[0] - a.window - 1)

    print("SĂN JACKPOT — chơi thử quy mô lớn")
    print(f"  {len(Z.ALL_MODELS)} model × {a.test} kỳ × {a.tickets} vé "
          f"= {len(Z.ALL_MODELS) * a.test * a.tickets:,} vé-kỳ\n")

    t0 = time.time()
    cache = Z.build_feature_cache(draws, Z.MAIN_MIN, Z.MAIN_MAX, False, first)
    cache_sp = Z.build_feature_cache(draws, Z.SPECIAL_MIN, Z.SPECIAL_MAX, True, first)

    per_model = {}
    grand = [0] * 6
    grand_j1 = grand_sp = 0
    j1_log, j2_log = [], []

    for name in Z.ALL_MODELS:
        t1 = time.time()
        dist = [0] * 6
        j1 = sp_hits = 0
        for t, s_main, s_sp in _score_stream(name, draws, cache, cache_sp,
                                             test_ids, a.window, a.refit):
            actual = set(draws[t].numbers)
            actual_sp = draws[t].special
            for v in range(a.tickets):
                seed = t * 100_003 + v
                pick = Z.sample_k(s_main, 5, Z.MAIN_MIN, seed, a.temp)
                psp = Z.sample_k(s_sp, 1, Z.SPECIAL_MIN, seed + 7_000_000, a.temp)[0]
                h = len(actual & set(pick))
                dist[h] += 1
                if psp == actual_sp:
                    sp_hits += 1
                if h == 5:
                    j2_log.append({"model": name, "draw": draws[t].draw_id,
                                   "numbers": pick, "special": psp})
                    if psp == actual_sp:
                        j1 += 1
                        j1_log.append({"model": name, "draw": draws[t].draw_id,
                                       "numbers": pick, "special": psp})
        n = sum(dist)
        per_model[name] = {"n": n, "dist": dist, "jackpot2": dist[5],
                           "jackpot1": j1, "special_hits": sp_hits}
        for h in range(6):
            grand[h] += dist[h]
        grand_j1 += j1
        grand_sp += sp_hits
        print(f"  · {name:<22} {n:>7,} vé  J2={dist[5]}  J1={j1}  ({time.time() - t1:.0f}s)")

    N = sum(grand)
    print("\n" + "═" * 72)
    print(f"{'TRÚNG':<8}{'THỰC TẾ':>12}{'LÝ THUYẾT':>14}{'TỈ LỆ':>10}{'XÁC SUẤT 1/n':>16}")
    print("─" * 72)
    for h in range(6):
        exp = TIER_P[h] * N
        ratio = (grand[h] / exp) if exp > 0 else 0.0
        print(f"{h:<8}{grand[h]:>12,}{exp:>14,.1f}{ratio:>10.3f}"
              f"{'1/' + format(round(1 / TIER_P[h]), ','):>16}")
    print("═" * 72)

    exp_j2 = N / C35_5
    exp_j1 = N / J1_ODDS
    exp_sp = N / 12
    print(f"\nTổng vé-kỳ chơi thử : {N:,}")
    print(f"Trúng số ĐB         : {grand_sp:,}  (lý thuyết {exp_sp:,.0f}, "
          f"tỉ lệ {grand_sp / exp_sp:.3f})")
    print(f"JACKPOT 2 (5 chính) : {grand[5]}  (lý thuyết {exp_j2:.3f})")
    print(f"JACKPOT 1 (5 + ĐB)  : {grand_j1}  (lý thuyết {exp_j1:.4f})")

    print("\n─── TRẢ LỜI ───")
    if grand_j1 == 0 and grand[5] == 0:
        print(f"KHÔNG có jackpot nào — cả J1 lẫn J2, trên {N:,} vé-kỳ.")
    elif grand_j1 == 0:
        print(f"Có {grand[5]} lần J2, KHÔNG có lần J1 nào trên {N:,} vé-kỳ.")
    else:
        print(f"Có {grand_j1} lần J1 và {grand[5]} lần J2 trên {N:,} vé-kỳ.")

    need_j1 = J1_ODDS
    draws_per_year = 156                                          # 3 kỳ/tuần
    print(f"\nĐể KỲ VỌNG trúng J1 một lần cần {need_j1:,} vé.")
    print(f"  · mua 1 vé/kỳ  → {need_j1 / draws_per_year:,.0f} năm")
    print(f"  · mua 10 vé/kỳ → {need_j1 / 10 / draws_per_year:,.0f} năm")
    print(f"  · mua 100 vé/kỳ→ {need_j1 / 100 / draws_per_year:,.0f} năm")
    print(f"\nCột 'TỈ LỆ' ở trên là thước đo thật: bằng 1,000 nghĩa là model bốc số")
    print("y hệt may rủi. Lệch khỏi 1,000 mới là dấu hiệu có kỹ năng.")

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tickets_per_model_per_draw": a.tickets,
        "test_draws": a.test,
        "total_ticket_draws": N,
        "temperature": a.temp,
        "tier_distribution": grand,
        "tier_expected": [round(TIER_P[h] * N, 2) for h in range(6)],
        "jackpot2": grand[5],
        "jackpot2_expected": round(exp_j2, 4),
        "jackpot1": grand_j1,
        "jackpot1_expected": round(exp_j1, 6),
        "special_hits": grand_sp,
        "special_expected": round(exp_sp, 1),
        "per_model": per_model,
        "jackpot2_log": j2_log,
        "jackpot1_log": j1_log,
    }
    os.makedirs("state", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nĐã ghi {OUT_PATH}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
