#!/usr/bin/env python3
"""backtest_zoo.py — backtest tiến (walk-forward) TẤT CẢ model trong model_zoo.py.

Luật chơi nghiêm ngặt: dự đoán kỳ t CHỈ được dùng dữ liệu tới kỳ t-1. Model có
giám sát huấn luyện lại theo chu kỳ trên cửa sổ trượt; model tự thân tính lại
từ đầu ở mỗi kỳ.

Thước đo: số trúng trung bình trên 5 số chính. Mốc ngẫu nhiên LÝ THUYẾT là
5·5/35 = 0,7143 (siêu bội). Kèm p-value hai phía và — quan trọng nhất — ngưỡng
"đỉnh nhiễu": khi so N model, model tốt nhất TẤT NHIÊN cao hơn mốc dù không có
kỹ năng nào. Vượt ngưỡng đó mới đáng nói.

Chọn số: mặc định TẤT ĐỊNH (`--mode top`) — mỗi model lấy đúng 5 số điểm cao
nhất, một vé duy nhất cho mỗi kỳ, tái lập 100%. Chế độ bốc ngẫu nhiên theo
trọng số vẫn còn ở `--mode sample` để đối chứng.

    python3 scripts/backtest_zoo.py                  # mặc định (tất định)
    python3 scripts/backtest_zoo.py --mode sample    # đối chứng ngẫu nhiên
    python3 scripts/backtest_zoo.py --test 150       # nhiều kỳ kiểm tra hơn
    python3 scripts/backtest_zoo.py --models knn,mlp # chỉ vài model
    python3 scripts/backtest_zoo.py --predict        # + dự đoán kỳ tới

Kết quả: state/model_zoo_leaderboard.json (và docs/model_zoo.json nếu --predict)
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
OUT_PATH = "state/model_zoo_leaderboard.json"
PREDICT_PATH = "docs/model_zoo.json"

POOL_N, DRAWN_K, PICK_K = 35, 5, 5
EXPECTED_RANDOM_HITS = PICK_K * DRAWN_K / POOL_N                   # 0.714285…
SPECIAL_RANDOM_RATE = 1 / 12


def _hypergeom_var(N=POOL_N, K=DRAWN_K, n=PICK_K) -> float:
    p = K / N
    return n * p * (1 - p) * (N - n) / (N - 1)


VAR_RANDOM = _hypergeom_var()


def _p_value(mean: float, n: int, mu: float, var: float) -> float:
    """p hai phía, xấp xỉ chuẩn (dùng erfc — không cần scipy)."""
    if n <= 1:
        return 1.0
    se = math.sqrt(var / n)
    if se == 0:
        return 1.0
    return math.erfc(abs(mean - mu) / se / math.sqrt(2))


def _noise_max(n_models: int, n_draws: int, var: float) -> float:
    """Kỳ vọng GIÁ TRỊ LỚN NHẤT trong n_models mẫu nhiễu — mốc phải vượt qua
    thì mới được coi là có tín hiệu, chứ không phải mốc 0,7143."""
    if n_models < 2 or n_draws < 2:
        return EXPECTED_RANDOM_HITS
    se = math.sqrt(var / n_draws)
    return EXPECTED_RANDOM_HITS + math.sqrt(2 * math.log(n_models)) * se


def load_draws():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        return parse_draws(list(csv.DictReader(f)))


def _run_supervised(name, factory, draws, cache, cache_sp, test_ids, window, refit,
                    mode, temp):
    """Huấn luyện lại mỗi `refit` kỳ trên cửa sổ trượt, rồi chấm điểm kỳ t.

    Chấm CẢ 5 số chính lẫn số đặc biệt — có số đặc biệt mới đo được Jackpot 1.
    """
    picks = {}
    model = mean = std = None
    model_sp = mean_sp = std_sp = None
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
        main = Z.choose(model.predict(Z.apply_standardise(rows, mean, std)),
                        5, Z.MAIN_MIN, t, mode, temp)
        sp = Z.choose(model_sp.predict(Z.apply_standardise(rows_sp, mean_sp, std_sp)),
                      1, Z.SPECIAL_MIN, t + 7_000_000, mode, temp)[0]
        picks[t] = (main, sp)
    return picks


def _run_custom(name, fn, draws, test_ids, window, mode, temp):
    picks = {}
    for t in test_ids:
        lo = max(0, t - window)
        main = Z.choose(fn(draws, t, lo, Z.MAIN_MIN, Z.MAIN_MAX, False, seed=t),
                        5, Z.MAIN_MIN, t, mode, temp)
        sp = Z.choose(fn(draws, t, lo, Z.SPECIAL_MIN, Z.SPECIAL_MAX, True, seed=t),
                      1, Z.SPECIAL_MIN, t + 7_000_000, mode, temp)[0]
        picks[t] = (main, sp)
    return picks


def _run_random(draws, test_ids, seed=2024):
    import random
    picks = {}
    for t in test_ids:
        rng = random.Random(seed + t)
        picks[t] = (sorted(rng.sample(range(Z.MAIN_MIN, Z.MAIN_MAX + 1), 5)),
                    rng.randint(Z.SPECIAL_MIN, Z.SPECIAL_MAX))
    return picks


def _evaluate(picks, draws):
    hits, dist = [], [0] * 6
    jackpot1 = jackpot2 = special_hits = 0
    for t, (pick, sp) in picks.items():
        actual = set(draws[t].numbers)
        h = len(actual & set(pick))
        hits.append(h)
        dist[h] += 1
        hit_sp = (sp == draws[t].special)
        special_hits += 1 if hit_sp else 0
        if h == 5:
            jackpot2 += 1
            if hit_sp:
                jackpot1 += 1
    if not hits:
        return None
    n = len(hits)
    mean = sum(hits) / n
    return {
        "n_draws": n,
        "avg_hits": round(mean, 4),
        "dist": dist,
        "jackpot1": jackpot1,
        "jackpot2": jackpot2,
        "special_hits": special_hits,
        "special_rate": round(special_hits / n, 4),
        "p_value": round(_p_value(mean, n, EXPECTED_RANDOM_HITS, VAR_RANDOM), 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", type=int, default=80, help="số kỳ dùng để kiểm tra")
    ap.add_argument("--window", type=int, default=150, help="cửa sổ huấn luyện (kỳ)")
    ap.add_argument("--refit", type=int, default=10, help="huấn luyện lại mỗi N kỳ")
    ap.add_argument("--models", default="", help="lọc theo tên, cách nhau bởi dấu phẩy")
    ap.add_argument("--predict", action="store_true", help="xuất dự đoán kỳ tới")
    ap.add_argument("--mode", choices=("top", "sample"), default="top",
                    help="top = TẤT ĐỊNH, lấy 5 số điểm cao nhất (mặc định); "
                         "sample = bốc ngẫu nhiên theo trọng số")
    ap.add_argument("--temp", type=float, default=Z.DEFAULT_TEMPERATURE,
                    help="nhiệt độ khi bốc: nhỏ = bám model, lớn = ngẫu nhiên hơn")
    ap.add_argument("--tickets", type=int, default=5,
                    help="số vé mỗi model xuất ra khi --predict (chỉ ở mode sample)")
    a = ap.parse_args()

    draws = load_draws()
    T = len(draws)
    if T < a.window + a.test + 5:
        a.test = max(20, T - a.window - 5)
    test_ids = list(range(T - a.test, T))
    first = max(0, test_ids[0] - a.window - 1)

    wanted = [m.strip() for m in a.models.split(",") if m.strip()] or Z.ALL_MODELS
    unknown = [m for m in wanted if m not in Z.ALL_MODELS]
    if unknown:
        sys.exit(f"Không có model: {', '.join(unknown)}\nCó: {', '.join(Z.ALL_MODELS)}")

    print(f"BACKTEST MODEL ZOO — {len(wanted)} model")
    print(f"  dữ liệu: {T} kỳ (#{draws[0].draw_id}–#{draws[-1].draw_id})")
    print(f"  kiểm tra: {a.test} kỳ cuối · cửa sổ {a.window} · refit mỗi {a.refit} kỳ")
    print(f"  chế độ chọn số: {a.mode}" + (f" (nhiệt độ {a.temp})" if a.mode == "sample" else ""))
    print(f"  mốc ngẫu nhiên lý thuyết: {EXPECTED_RANDOM_HITS:.4f} số trúng/kỳ\n")

    t0 = time.time()
    cache = Z.build_feature_cache(draws, Z.MAIN_MIN, Z.MAIN_MAX, False, first)
    cache_sp = Z.build_feature_cache(draws, Z.SPECIAL_MIN, Z.SPECIAL_MAX, True, first)
    print(f"  đặc trưng: xong trong {time.time() - t0:.1f}s\n")

    results = []
    for name in wanted:
        t1 = time.time()
        if name in Z.SUPERVISED_MODELS:
            _, factory = Z.SUPERVISED_MODELS[name]
            picks = _run_supervised(name, factory, draws, cache, cache_sp,
                                    test_ids, a.window, a.refit, a.mode, a.temp)
            family = "supervised"
        else:
            _, fn = Z.CUSTOM_MODELS[name]
            picks = _run_custom(name, fn, draws, test_ids, a.window, a.mode, a.temp)
            family = "custom"
        ev = _evaluate(picks, draws)
        if ev is None:
            continue
        ev.update(model=name, label=Z.model_label(name), family=family,
                  seconds=round(time.time() - t1, 1))
        results.append(ev)
        print(f"  · {name:<22} {ev['avg_hits']:.4f}  p={ev['p_value']:.3f}  "
              f"J1={ev['jackpot1']} J2={ev['jackpot2']}  ({ev['seconds']}s)")

    ev = _evaluate(_run_random(draws, test_ids), draws)
    ev.update(model="random_baseline", label="Ngẫu nhiên (mốc thật)",
              family="baseline", seconds=0.0)
    results.append(ev)
    print(f"  · {'random_baseline':<22} {ev['avg_hits']:.4f}  p={ev['p_value']:.3f}  "
          f"J1={ev['jackpot1']} J2={ev['jackpot2']}\n")

    results.sort(key=lambda r: -r["avg_hits"])
    thr = _noise_max(len(wanted), a.test, VAR_RANDOM)

    print("═" * 76)
    print(f"{'#':<3}{'MODEL':<24}{'TRÚNG TB':>10}{'p':>8}{'ĐB':>7}{'J2':>4}{'J1':>4}  HỌ")
    print("─" * 76)
    for i, r in enumerate(results, 1):
        flag = "★" if r["avg_hits"] > thr and r["family"] != "baseline" else " "
        print(f"{i:<3}{r['model']:<24}{r['avg_hits']:>10.4f}{r['p_value']:>8.3f}"
              f"{r['special_rate']:>7.3f}{r['jackpot2']:>4}{r['jackpot1']:>4}  "
              f"{r['family']}{flag}")
    print("═" * 76)

    # ── Kết luận về JACKPOT: câu hỏi thật sự người chơi quan tâm ──
    n_arms = len(results)
    tickets = sum(r["n_draws"] for r in results)
    tot_j1 = sum(r["jackpot1"] for r in results)
    tot_j2 = sum(r["jackpot2"] for r in results)
    exp_j1 = tickets / 3_895_584
    exp_j2 = tickets / 324_632
    print(f"\n─── JACKPOT ───")
    print(f"Tổng lượt chơi thử : {tickets:,} vé-kỳ ({n_arms} nhánh × {a.test} kỳ)")
    print(f"Jackpot 1 (5+ĐB)   : {tot_j1}   (kỳ vọng nếu thuần may rủi: {exp_j1:.4f})")
    print(f"Jackpot 2 (5 chính): {tot_j2}   (kỳ vọng nếu thuần may rủi: {exp_j2:.4f})")
    print(f"Tỉ lệ trúng số ĐB  : mốc lý thuyết {SPECIAL_RANDOM_RATE:.4f}")
    print(f"\n   Với {tickets:,} vé-kỳ, ngay cả một model HOÀN HẢO-may-mắn cũng chỉ")
    print(f"   kỳ vọng {exp_j1:.4f} lần J1. Số 0 ở trên KHÔNG chứng minh model kém —")
    print(f"   nó cho thấy backtest KHÔNG THỂ đo được kỹ năng trúng jackpot. Muốn")
    print(f"   phân biệt model tốt gấp đôi với may rủi cần cỡ hàng nghìn năm chơi.")

    best = max((r for r in results if r["family"] != "baseline"),
               key=lambda r: r["avg_hits"])
    print(f"\nMốc ngẫu nhiên lý thuyết : {EXPECTED_RANDOM_HITS:.4f}")
    print(f"Ngưỡng ĐỈNH NHIỄU ({len(wanted)} model): {thr:.4f}")
    print(f"Model cao nhất           : {best['model']} = {best['avg_hits']:.4f}")
    if best["avg_hits"] <= thr:
        print("\n=> Model cao nhất VẪN DƯỚI ngưỡng đỉnh nhiễu. Nghĩa là: chênh lệch")
        print("   này là thứ ta LUÔN thấy khi so nhiều model không có kỹ năng gì.")
        print("   KHÔNG model nào ở đây có lợi thế thật.")
    else:
        print("\n=> Vượt ngưỡng đỉnh nhiễu. Vẫn PHẢI kiểm chứng lại trên dữ liệu")
        print("   HOÀN TOÀN MỚI (kỳ chưa xảy ra) trước khi tin — vượt ngưỡng một")
        print("   lần trên dữ liệu quá khứ là chuyện thường gặp do thiên lệch chọn.")
    print(f"\nTổng: {time.time() - t0:.1f}s")

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_draws_total": T,
        "test_draws": a.test,
        "window": a.window,
        "refit": a.refit,
        "mode": a.mode,
        "temperature": a.temp,
        "expected_random_hits": round(EXPECTED_RANDOM_HITS, 4),
        "noise_max_threshold": round(thr, 4),
        "results": results,
    }
    os.makedirs("state", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Đã ghi {OUT_PATH}")

    if a.predict:
        _write_predictions(draws, cache, wanted, a)


def _write_predictions(draws, cache, wanted, a):
    """Dự đoán kỳ TIẾP THEO (chưa quay) bằng từng model — 5 số chính + số đặc biệt."""
    T = len(draws)
    next_id = int(draws[-1].draw_id) + 1
    lo = max(0, T - a.window)

    # Đặc trưng cho kỳ T (chưa có kết quả) — cache chỉ tới T-1, nên dựng thêm.
    cache_main = Z.build_feature_cache(draws, Z.MAIN_MIN, Z.MAIN_MAX, False, lo)
    cache_sp = Z.build_feature_cache(draws, Z.SPECIAL_MIN, Z.SPECIAL_MAX, True, lo)
    rows_main = Z.build_feature_cache(draws + [draws[-1]], Z.MAIN_MIN, Z.MAIN_MAX,
                                      False, T)[T]
    rows_sp = Z.build_feature_cache(draws + [draws[-1]], Z.SPECIAL_MIN, Z.SPECIAL_MAX,
                                    True, T)[T]

    out = []
    for name in wanted:
        # Chấm điểm MỘT lần cho mỗi model, rồi bốc `--tickets` vé từ cùng bộ điểm
        # với seed khác nhau (chế độ sample). Chế độ top chỉ có 1 vé duy nhất.
        if name in Z.SUPERVISED_MODELS:
            _, factory = Z.SUPERVISED_MODELS[name]
            X, y = Z.build_dataset(draws, cache_main, lo, T, Z.MAIN_MIN, Z.MAIN_MAX, False)
            Xs, mu, sd = Z.standardise(X)
            m = factory().fit(Xs, y)
            s_main = m.predict(Z.apply_standardise(rows_main, mu, sd))
            Xp, yp = Z.build_dataset(draws, cache_sp, lo, T,
                                     Z.SPECIAL_MIN, Z.SPECIAL_MAX, True)
            Xps, mu2, sd2 = Z.standardise(Xp)
            m2 = factory().fit(Xps, yp)
            s_sp = m2.predict(Z.apply_standardise(rows_sp, mu2, sd2))
        else:
            _, fn = Z.CUSTOM_MODELS[name]
            s_main = fn(draws, T, lo, Z.MAIN_MIN, Z.MAIN_MAX, False, seed=next_id)
            s_sp = fn(draws, T, lo, Z.SPECIAL_MIN, Z.SPECIAL_MAX, True, seed=next_id)

        n_tickets = 1 if a.mode == "top" else max(1, a.tickets)
        tickets = []
        for v in range(1, n_tickets + 1):
            seed = next_id * 1000 + v
            tickets.append({
                "index": v,
                "numbers": Z.choose(s_main, 5, Z.MAIN_MIN, seed, a.mode, a.temp),
                "special": Z.choose(s_sp, 1, Z.SPECIAL_MIN, seed + 7_000_000,
                                    a.mode, a.temp)[0],
                "trace": f"zoo-{next_id}-{name}-{a.mode}-{v:02d}",
            })
        out.append({"model": name, "label": Z.model_label(name),
                    "mode": a.mode, "temperature": a.temp, "tickets": tickets})
        shown = "   ".join(f"{' '.join(f'{n:02d}' for n in t['numbers'])}+{t['special']:02d}"
                           for t in tickets[:3])
        more = f"  (+{len(tickets) - 3} vé)" if len(tickets) > 3 else ""
        print(f"  {name:<22} {shown}{more}")

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "next_draw": next_id,
        "mode": a.mode,
        "temperature": a.temp,
        "tickets_per_model": 1 if a.mode == "top" else max(1, a.tickets),
        "disclaimer": "Mỗi vé đều 1/324.632 (J2) và 1/3.895.584 (J1) — bằng nhau, "
                      "bất kể model nào sinh ra. Backtest cho thấy không model nào "
                      "vượt ngẫu nhiên.",
        "predictions": out,
    }
    os.makedirs("docs", exist_ok=True)
    with open(PREDICT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Đã ghi {PREDICT_PATH}")


if __name__ == "__main__":
    main()
