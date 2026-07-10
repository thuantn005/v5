#!/usr/bin/env bash
# apply_anti_split.sh — them anti_split.py vao repo v5, commit va push
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Hay chay script nay ben trong thu muc repo v5 (da git clone)."; exit 1
fi

cat > anti_split.py << 'ANTI_SPLIT_EOF'
"""
anti_split.py — Anti-split ticket generator for Vietlott Lotto 5/35 (repo: v5)

Mục đích: KHÔNG dự đoán số (bất khả thi — mọi tổ hợp có xác suất y hệt
1/324,632 cho 5 số, 1/3,895,584 cho Jackpot 1). Module này tối ưu thứ duy
nhất tối ưu được: kỳ vọng tiền nhận ĐƯỢC KHI trúng, bằng cách chọn các tổ
hợp ít người chơi khác chọn (giảm rủi ro chia giải pari-mutuel).

Popularity model (các nguồn bias hành vi người chơi đã được nghiên cứu):
  1. Birthday bias  : 1–31 bị chơi nhiều (mạnh nhất 1–12 = ngày & tháng)
  2. Lucky digits VN: 6/8/9 và số kết thúc bằng 6/8/9 (lộc/phát) bị chơi nhiều
  3. Unlucky VN     : 4 ("tử"), 13 → ÍT người chơi → ta ƯU TIÊN
  4. Round numbers  : bội số của 5 hơi phổ biến
  5. Patterns       : dãy liên tiếp, cấp số cộng, cùng chữ số cuối → phổ biến
  6. Recency        : số trùng 1–3 kỳ gần nhất hay bị chơi lại

Usage:
    python anti_split.py --csv data/all.csv --n 5 --seed 42
    from anti_split import generate_tickets
"""

from __future__ import annotations
import argparse, json, sys
import numpy as np

MAIN_MAX, PICK, SPECIAL_MAX = 35, 5, 12

# ---------------------------------------------------------------- weights ---
LUCKY_WHOLE   = {8: 0.30, 9: 0.20}          # extra on top of digit boost
UNLUCKY_WHOLE = {4: -0.80, 13: -0.50}       # underplayed -> we prefer these
DIGIT_BOOST   = {8: 0.40, 9: 0.25, 6: 0.20} # last-digit lucky boost


def number_weights() -> np.ndarray:
    """Popularity weight per number 1..35 (higher = more popular)."""
    w = np.zeros(MAIN_MAX + 1)
    for n in range(1, MAIN_MAX + 1):
        if n <= 12:
            w[n] += 1.20                     # day + month birthdays
        elif n <= 31:
            w[n] += 0.70                     # day-only birthdays
        w[n] += DIGIT_BOOST.get(n % 10, 0.0)
        w[n] += LUCKY_WHOLE.get(n, 0.0)
        w[n] += UNLUCKY_WHOLE.get(n, 0.0)
        if n % 5 == 0:
            w[n] += 0.20                     # round-number preference
    return w


SPECIAL_W = {1: .30, 2: .20, 3: .30, 4: -.80, 5: .20, 6: .40,
             7: .35, 8: .70, 9: .50, 10: .10, 11: .00, 12: .15}


# ---------------------------------------------------------------- scoring ---
def pattern_penalty(t: np.ndarray) -> float:
    """Extra popularity for human-favored patterns. t is sorted (5,)."""
    p = 0.0
    d = np.diff(t)
    p += 0.30 * int((d == 1).sum())                      # consecutive pairs
    run = 1
    for g in d:
        run = run + 1 if g == 1 else 1
        if run >= 3:
            p += 0.80                                    # long runs
    if len(set(d)) == 1:
        p += 1.50                                        # arithmetic progression
    digits = np.bincount(t % 10, minlength=10)
    if digits.max() >= 3:
        p += 0.60                                        # same last digit
    if t.max() <= 31:
        p += 0.60                                        # fully birthday-playable
        if t.max() <= 12:
            p += 1.20
    if np.all(t % 5 == 0):
        p += 1.50                                        # all round numbers
    return p


def recency_penalty(t: np.ndarray, recent: list[set[int]]) -> float:
    """People replay recent results; overlap with last draws = more popular."""
    p, w = 0.0, 0.45
    for draw in recent:                                   # most recent first
        p += w * len(set(t.tolist()) & draw)
        w *= 0.6
    return p


def popularity(tickets: np.ndarray, w: np.ndarray,
               recent: list[set[int]]) -> np.ndarray:
    base = w[tickets].sum(axis=1)
    extra = np.array([pattern_penalty(np.sort(t)) +
                      recency_penalty(t, recent) for t in tickets])
    return base + extra


# -------------------------------------------------------------- generator ---
def generate_tickets(n_tickets: int = 5, candidates: int = 200_000,
                     seed: int | None = None,
                     recent_draws: list[list[int]] | None = None,
                     max_overlap: int = 2) -> list[dict]:
    """
    Sinh n_tickets vé có popularity thấp nhất trong `candidates` vé ngẫu nhiên,
    ràng buộc đa dạng: hai vé bất kỳ trùng nhau tối đa `max_overlap` số.
    Trả về list dict: numbers, special, popularity, percentile.
    """
    rng = np.random.default_rng(seed)
    recent = [set(d) for d in (recent_draws or [])][:3]

    cand = np.argsort(rng.random((candidates, MAIN_MAX)), axis=1)[:, :PICK] + 1
    cand = np.sort(cand, axis=1)
    cand = np.unique(cand, axis=0)

    w = number_weights()
    scores = popularity(cand, w, recent)
    order = np.argsort(scores)

    chosen, chosen_sets = [], []
    for idx in order:
        s = set(cand[idx].tolist())
        if all(len(s & c) <= max_overlap for c in chosen_sets):
            chosen.append(idx)
            chosen_sets.append(s)
            if len(chosen) == n_tickets:
                break

    specials = sorted(range(1, SPECIAL_MAX + 1), key=lambda k: SPECIAL_W[k])
    out = []
    for rank, idx in enumerate(chosen):
        out.append({
            "numbers": cand[idx].tolist(),
            "special": specials[rank % len(specials)],
            "popularity": round(float(scores[idx]), 3),
            "percentile_vs_random": round(
                float((scores < scores[idx]).mean() * 100), 2),
        })
    return out


# ------------------------------------------------------------------- data ---
def load_recent_draws(csv_path: str, k: int = 3) -> list[list[int]]:
    import pandas as pd
    df = pd.read_csv(csv_path)
    df = df.sort_values("draw_id").tail(k)
    rows = [json.loads(r)["numbers"] for r in df["result_json"]]
    return rows[::-1]                                     # most recent first


# -------------------------------------------------------------------- cli ---
def main() -> None:
    ap = argparse.ArgumentParser(description="Anti-split ticket generator")
    ap.add_argument("--csv", help="draw history CSV (result_json column)")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--candidates", type=int, default=200_000)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--json-out", help="write result JSON to file")
    a = ap.parse_args()

    recent = load_recent_draws(a.csv) if a.csv else None
    tickets = generate_tickets(a.n, a.candidates, a.seed, recent)

    print("Anti-split tickets (xác suất trúng = mọi vé khác; "
          "tối ưu tránh chia giải):")
    for i, t in enumerate(tickets, 1):
        nums = " ".join(f"{x:02d}" for x in t["numbers"])
        print(f"  #{i}: {nums} | ĐB {t['special']:02d} | "
              f"popularity {t['popularity']} "
              f"(thấp hơn {100 - t['percentile_vs_random']:.1f}% vé ngẫu nhiên)")

    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump({"tickets": tickets}, f, ensure_ascii=False, indent=2)
        print(f"-> {a.json_out}")


if __name__ == "__main__":
    main()
ANTI_SPLIT_EOF

git add anti_split.py
git commit -m "Add anti_split: low-popularity ticket generator (anti jackpot splitting)"
git push
echo "Da push anti_split.py len remote."
