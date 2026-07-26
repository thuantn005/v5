"""
special_search.py
-----------------
Dò tìm & xếp hạng các cách chọn SỐ ĐẶC BIỆT (pool 1-12) theo số lần trúng
đặc biệt nhiều nhất trong toàn bộ lịch sử. Ba nhóm ứng viên được so sánh:

  1. Mọi công thức trong STRATEGIES (special_fortune, neural_perceptron, ...)
  2. Hàng loạt SEED (salt) chạy qua cơ chế uniform_seeded / trace: mỗi kỳ
     rút một seed riêng = sha256(salt | draw_id | special), rồi lấy số có
     điểm ngẫu nhiên cao nhất.
  3. 12 lựa chọn CỐ ĐỊNH ("luôn đánh số N") — tương đương seed nguyên cố định,
     và là mốc trung thực: cái tốt nhất chỉ đơn giản là số đặc biệt hay ra nhất.

===================  CẢNH BÁO TRUNG THỰC  ===================
Đây là DÒ TÌM HỒI CỐ (overfitting). Xổ số là độc lập: một seed/công thức
"trúng nhiều nhất trong quá khứ" KHÔNG hề có nhiều khả năng trúng ở kỳ tới
hơn bất kỳ số nào khác — xác suất thật vẫn là 1/12. Con số "hit rate" cao
nhất tìm được ở đây chỉ là ĐỈNH NHIỄU: nếu bạn thử đủ nhiều seed ngẫu nhiên,
kiểu gì cũng có vài cái trông "thần kỳ" thuần do may rủi. Công cụ này in ra
cả mốc kỳ vọng của đỉnh nhiễu để bạn thấy rõ điều đó.
============================================================

Cách dùng:
    python3 scripts/special_search.py                 # mặc định 20000 seed
    python3 scripts/special_search.py --seeds 100000  # dò nhiều seed hơn
    python3 scripts/special_search.py --top 20 --json state/special_search.json
"""

from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import os
import random
import statistics
from collections import Counter

from model import (
    parse_draws, SPECIAL_MIN, SPECIAL_MAX,
)
from strategies import STRATEGIES, DEFAULT_PARAMS, pick_topk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_CSV = os.path.join(ROOT, "data", "all.csv")

MIN_HISTORY = 60                      # khớp với backtest_all.MIN_HISTORY
SPECIAL_RANDOM_RATE = 1 / (SPECIAL_MAX - SPECIAL_MIN + 1)   # ~0.0833


def load_draws() -> list:
    with open(DATA_CSV, newline="", encoding="utf-8") as f:
        return parse_draws(list(csv.DictReader(f)))


def _derive_seed(salt: str, draw_id: str) -> int:
    raw = f"{salt}|{draw_id}|special"
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16], 16)


POOL = list(range(SPECIAL_MIN, SPECIAL_MAX + 1))


def _pick_for_seed(seed: int) -> int:
    """Số đặc biệt mà một seed chọn, y hệt uniform_seeded: điểm ngẫu nhiên có
    seed cho từng số trong pool, chọn số điểm cao nhất (hoà thì số nhỏ thắng)."""
    rng = random.Random(seed)
    best_n, best_s = POOL[0], -1.0
    for n in POOL:
        s = rng.random()
        if s > best_s:            # strictly '>' → giữ số nhỏ khi hoà
            best_s, best_n = s, n
    return best_n


def seed_hits(draw_ids: list[str], actuals: list[int], salt: str) -> int:
    """Số kỳ mà salt này trúng số đặc biệt, tính trực tiếp (không cấp phát list)."""
    hits = 0
    for did, a in zip(draw_ids, actuals):
        if _pick_for_seed(_derive_seed(salt, did)) == a:
            hits += 1
    return hits


def actual_specials(draws) -> list[int]:
    return [d.special for idx, d in enumerate(draws) if idx >= MIN_HISTORY]


def hit_rate(preds: list[int], actuals: list[int]) -> tuple[int, float]:
    hits = sum(1 for p, a in zip(preds, actuals) if p == a)
    return hits, (hits / len(actuals) if actuals else 0.0)


# --------------------------------------------------------------------------
# 1. Backtest mọi công thức trên pool đặc biệt
# --------------------------------------------------------------------------
def eval_strategies(draws, actuals) -> list[dict]:
    out = []
    history = []
    # precompute predictions per strategy in one history sweep
    preds_by_strat = {name: [] for name in STRATEGIES}
    history = []
    for idx, d in enumerate(draws):
        if idx >= MIN_HISTORY:
            for name, fn in STRATEGIES.items():
                params = dict(DEFAULT_PARAMS.get(name, {}))
                params.setdefault("trace", f"backtest|{d.draw_id}|special")
                scores = fn(history, SPECIAL_MIN, SPECIAL_MAX, 1, True, params)
                preds_by_strat[name].append(pick_topk(scores, 1)[0])
        history.append(d)
    for name, preds in preds_by_strat.items():
        hits, rate = hit_rate(preds, actuals)
        out.append({"kind": "strategy", "name": name, "hits": hits, "rate": round(rate, 4)})
    return out


# --------------------------------------------------------------------------
# 2. Lựa chọn cố định "luôn đánh số N"
# --------------------------------------------------------------------------
def eval_constants(draws, actuals) -> list[dict]:
    freq = Counter(actuals)
    out = []
    for n in range(SPECIAL_MIN, SPECIAL_MAX + 1):
        hits = freq.get(n, 0)
        out.append({"kind": "constant", "name": f"luôn đánh {n:02d}",
                    "hits": hits, "rate": round(hits / len(actuals), 4) if actuals else 0.0})
    return out


# --------------------------------------------------------------------------
# 3. Dò hàng loạt seed
# --------------------------------------------------------------------------
def eval_seeds(draws, actuals, n_seeds: int, progress: bool) -> list[dict]:
    draw_ids = [d.draw_id for idx, d in enumerate(draws) if idx >= MIN_HISTORY]
    n = len(actuals)
    out = []
    step = max(1, n_seeds // 20)
    for i in range(n_seeds):
        salt = f"seed-{i}"
        hits = seed_hits(draw_ids, actuals, salt)
        out.append({"kind": "seed", "name": salt, "hits": hits, "rate": round(hits / n, 4)})
        if progress and (i + 1) % step == 0:
            print(f"  ...đã dò {i + 1}/{n_seeds} seed", flush=True)
    return out


def expected_max_of_noise(n_seeds: int, n_draws: int) -> float:
    """Kỳ vọng tỉ lệ trúng của seed 'may nhất' trong n_seeds seed thuần nhiễu.
    Xấp xỉ bằng trung bình + z * độ lệch chuẩn, với z là kỳ vọng cực đại của
    n_seeds biến chuẩn (~sqrt(2 ln n))."""
    p = SPECIAL_RANDOM_RATE
    mean = p
    sd = math.sqrt(p * (1 - p) / n_draws)
    z = math.sqrt(2 * math.log(n_seeds)) if n_seeds > 1 else 0.0
    return mean + z * sd


def main():
    ap = argparse.ArgumentParser(description="Dò công thức/seed trúng số đặc biệt nhiều nhất")
    ap.add_argument("--seeds", type=int, default=5000, help="số seed cần dò (mặc định 5000)")
    ap.add_argument("--top", type=int, default=15, help="in bao nhiêu ứng viên hàng đầu")
    ap.add_argument("--json", default=os.path.join(ROOT, "state", "special_search.json"),
                    help="đường dẫn file JSON kết quả")
    ap.add_argument("--quiet", action="store_true", help="tắt log tiến độ")
    args = ap.parse_args()

    draws = load_draws()
    actuals = actual_specials(draws)
    n = len(actuals)
    print(f"📊 Lịch sử: {len(draws)} kỳ | backtest {n} kỳ (bỏ {MIN_HISTORY} kỳ khởi động)")
    print(f"🎲 Mốc ngẫu nhiên (1/12): {SPECIAL_RANDOM_RATE:.4f}\n")

    print("🔎 Backtest các công thức...")
    strat = eval_strategies(draws, actuals)
    print("🔎 Đánh giá 12 lựa chọn cố định...")
    consts = eval_constants(draws, actuals)
    print(f"🔎 Dò {args.seeds} seed...")
    seeds = eval_seeds(draws, actuals, args.seeds, progress=not args.quiet)

    everything = strat + consts + seeds
    everything.sort(key=lambda r: (-r["hits"], r["name"]))

    exp_noise = expected_max_of_noise(args.seeds, n)

    print("\n================ XẾP HẠNG TRÚNG SỐ ĐẶC BIỆT ================")
    print(f"{'#':>2}  {'loại':<9} {'tên':<22} {'trúng':>6} {'tỉ lệ':>8}")
    for rank, r in enumerate(everything[:args.top], 1):
        print(f"{rank:>2}  {r['kind']:<9} {r['name']:<22} {r['hits']:>6} {r['rate']:>8.4f}")

    # top thuần từ mỗi nhóm
    best_strat = max(strat, key=lambda r: r["hits"])
    best_seed = max(seeds, key=lambda r: r["hits"]) if seeds else None
    best_const = max(consts, key=lambda r: r["hits"])

    print("\n---------------- TỐT NHẤT MỖI NHÓM ----------------")
    print(f"Công thức : {best_strat['name']:<20} {best_strat['hits']} trúng ({best_strat['rate']:.4f})")
    if best_seed:
        print(f"Seed      : {best_seed['name']:<20} {best_seed['hits']} trúng ({best_seed['rate']:.4f})")
    print(f"Cố định   : {best_const['name']:<20} {best_const['hits']} trúng ({best_const['rate']:.4f})")

    print("\n⚠️  ĐỌC KỸ: đây là dò tìm hồi cố (overfitting).")
    print(f"    Nếu {args.seeds} seed đều thuần nhiễu, seed 'may nhất' vẫn dự kiến đạt")
    print(f"    ~{exp_noise:.4f} ({exp_noise * n:.0f} trúng) chỉ do may rủi — cao hơn mốc 1/12.")
    print(f"    Seed tốt nhất tìm được ({best_seed['rate'] if best_seed else 0:.4f}) "
          f"{'KHÔNG vượt' if best_seed and best_seed['rate'] <= exp_noise else 'nhỉnh hơn'} mốc nhiễu này")
    print("    → không có bằng chứng nào cho thấy nó sẽ trúng ở kỳ tới. Xác suất thật vẫn 1/12.")

    result = {
        "n_backtested": n,
        "random_rate": round(SPECIAL_RANDOM_RATE, 4),
        "n_seeds_searched": args.seeds,
        "expected_noise_max_rate": round(exp_noise, 4),
        "top": everything[:args.top],
        "best_by_group": {
            "strategy": best_strat,
            "seed": best_seed,
            "constant": best_const,
        },
        "all_strategies": sorted(strat, key=lambda r: -r["hits"]),
    }
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Đã lưu kết quả: {os.path.relpath(args.json, ROOT)}")


if __name__ == "__main__":
    main()
