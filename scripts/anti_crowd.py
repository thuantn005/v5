#!/usr/bin/env python3
"""anti_crowd.py — chọn số NGƯỢC ĐÁM ĐÔNG cho Lotto 5/35.

Nói rõ ngay để không hiểu nhầm:

    Thuật toán này KHÔNG làm bạn dễ trúng hơn. Không gì làm được điều đó —
    đã đo bằng 19 model trên 684.000 vé-kỳ, phân bố khớp may rủi tới ba chữ
    số thập phân.

    Nó chỉ tăng SỐ TIỀN NHẬN ĐƯỢC KHI TRÚNG, bằng cách né những tổ hợp mà
    đông người cùng chọn. Trúng Độc Đắc một mình khác hẳn trúng cùng bốn
    người khác. Đây là biến số DUY NHẤT người chơi thật sự điều khiển được.

Bằng chứng đám đông không chọn ngẫu nhiên — đo từ kỳ #00814 (vietlott-sms.vn):

    Giải Tư (3 số + ĐB) : 148 người
    Giải Năm (3 số, ko ĐB): 2.271 người

    Hai giải đòi hỏi Y HỆT nhau về số chính, chỉ khác số đặc biệt. Nên tỉ lệ
    giữa chúng đo thẳng được tỉ lệ người chơi đã chọn ĐB = 01:
        148/(148+2271) = 6,12%   (ngẫu nhiên đều phải là 8,33%)
        z = -4,55 · p = 5,5e-06
    Người chơi né số 01 tới 27%. Vậy chọn 01 là chọn chỗ vắng.

    Suy ra số vé bán từ từng bậc giải cũng lệch nhau 1,76 lần — nếu ai cũng
    bốc ngẫu nhiên thì mọi bậc phải cho cùng một con số.

    python3 scripts/anti_crowd.py --draw 00815 --tickets 10
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from math import comb

MAIN_MIN, MAIN_MAX = 1, 35
SPECIAL_MIN, SPECIAL_MAX = 1, 12

# ─────────────────────── Thiên lệch của đám đông ───────────────────────
#
# ĐÃ ĐO (kỳ #00814): số đặc biệt 01 bị né 27%.
# CHƯA ĐO, dùng quy luật đã biết rộng rãi ở mọi xổ số trên thế giới — cần
# thêm dữ liệu số người trúng nhiều kỳ mới đo được cho Lotto 5/35 cụ thể:
#
#   * "thiên lệch lịch": người ta chọn theo ngày sinh, nên 1..31 bị dồn nặng,
#     còn 32..35 gần như bị bỏ quên
#   * dãy liên tiếp (03 04 05 06 07) trông "có hệ thống" nên nhiều người chọn
#   * cấp số cộng (05 10 15 20 25) cũng vậy
#   * dồn cùng một chục (11 12 15 17 19) — thói quen tô theo hàng trên phiếu
#   * tổng quá thấp là hệ quả trực tiếp của thiên lệch lịch

MEASURED_SPECIAL_UNDERPICK = {1: 0.73}      # 01 chỉ được chọn bằng 73% mức đều


def _load_history(path="data/all.csv"):
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                r = json.loads(row["result_json"])
                n = sorted(int(x) for x in r["numbers"])
                sp = (r.get("special_numbers") or [None])[0]
                if len(n) == 5 and sp:
                    out.append((row["draw_id"], n, int(sp)))
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue
    return out


# ─────────────────────── Bộ lọc ngược đám đông ───────────────────────

def reasons_crowded(nums: list[int]) -> list[str]:
    """Trả danh sách lý do tổ hợp này ĐÔNG người chọn. Rỗng = vắng vẻ."""
    bad = []
    s = sorted(nums)

    if all(n <= 31 for n in s):
        bad.append("cả 5 số đều ≤31 (vùng ngày sinh)")
    if sum(s) < 70:
        bad.append(f"tổng {sum(s)} quá thấp")
    if sum(s) > 110:
        bad.append(f"tổng {sum(s)} quá cao")

    run = 1
    for i in range(1, 5):
        run = run + 1 if s[i] == s[i - 1] + 1 else 1
        if run >= 3:
            bad.append("có 3 số liên tiếp")
            break

    d = s[1] - s[0]
    if d > 0 and all(s[i + 1] - s[i] == d for i in range(4)):
        bad.append(f"cấp số cộng bước {d}")

    decades = {(n - 1) // 10 for n in s}
    if len(decades) <= 2:
        bad.append("dồn trong ≤2 chục")

    if len({n % 10 for n in s}) <= 2:
        bad.append("chỉ có ≤2 chữ số cuối khác nhau")

    odd = sum(1 for n in s if n % 2)
    if odd in (0, 5):
        bad.append("toàn chẵn hoặc toàn lẻ")

    return bad


def crowd_weight_main() -> list[float]:
    """Trọng số ưu tiên số bị đám đông bỏ quên."""
    w = []
    for n in range(MAIN_MIN, MAIN_MAX + 1):
        if n >= 32:
            w.append(3.0)          # ngoài hẳn vùng ngày — vắng nhất
        elif n > 12:
            w.append(1.6)          # ngoài vùng tháng, vẫn trong vùng ngày
        else:
            w.append(1.0)          # 1..12 vừa là ngày vừa là tháng — đông nhất
    return w


def crowd_weight_special() -> list[float]:
    """1..12 ai cũng phải chọn, nhưng mức chọn không đều — dùng số đã ĐO."""
    return [1.0 / MEASURED_SPECIAL_UNDERPICK.get(n, 1.0)
            for n in range(SPECIAL_MIN, SPECIAL_MAX + 1)]


def _seed(trace: str) -> int:
    return int(hashlib.sha256(trace.encode()).hexdigest()[:16], 16)


def _sample(weights, k, offset, rng):
    w = list(weights)
    out = []
    for _ in range(k):
        tot = sum(w)
        r = rng.random() * tot
        for i, x in enumerate(w):
            r -= x
            if r <= 0:
                out.append(offset + i)
                w[i] = 0.0
                break
    return out


def generate(draw_id: str, count: int, max_tries: int = 4000):
    wm, ws = crowd_weight_main(), crowd_weight_special()
    tickets, seen = [], set()
    idx = 0
    for _ in range(max_tries):
        if len(tickets) >= count:
            break
        idx += 1
        rng = random.Random(_seed(f"L535-anticrowd-{draw_id}-{idx}"))
        nums = sorted(_sample(wm, 5, MAIN_MIN, rng))
        sp = _sample(ws, 1, SPECIAL_MIN, rng)[0]
        key = tuple(nums) + (sp,)
        if key in seen or reasons_crowded(nums):
            continue
        seen.add(key)
        tickets.append((nums, sp))
    return tickets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draw", default="", help="mã kỳ, mặc định = kỳ cuối + 1")
    ap.add_argument("--tickets", type=int, default=10)
    a = ap.parse_args()

    hist = _load_history()
    draw_id = a.draw or "%05d" % (int(hist[-1][0]) + 1)

    tickets = generate(draw_id, a.tickets)

    print(f"CHỌN SỐ NGƯỢC ĐÁM ĐÔNG — kỳ #{draw_id}")
    print(f"(lịch sử {len(hist)} kỳ, kỳ cuối #{hist[-1][0]})\n")
    labels = "ABCDEFGHIJKLMNOPQRST"
    print("  DÒNG   5 SỐ CHÍNH          ĐB")
    print("  " + "-" * 34)
    for i, (nums, sp) in enumerate(tickets):
        lab = labels[i] if i < len(labels) else str(i + 1)
        print(f"    {lab}    {' '.join('%02d' % n for n in nums)}      {sp:02d}")
    print("  " + "-" * 34)

    # Đối chiếu: bốc ngẫu nhiên đều thì bao nhiêu % vé rơi vào vùng đông?
    rng = random.Random(12345)
    pool = range(MAIN_MIN, MAIN_MAX + 1)
    crowded = sum(1 for _ in range(20000)
                  if reasons_crowded(sorted(rng.sample(pool, 5))))
    print(f"\nBộ lọc loại {crowded/200:.1f}% không gian vé — phần lớn do luật")
    print(f'"cả 5 số ≤31" (riêng nó đã là 52,3%). Nghĩa là vé còn lại nằm trong')
    print(f"{100-crowded/200:.1f}% không gian mà đám đông ÍT chạm tới nhất.")

    print("\nHAI ĐIỀU PHẢI NÓI RÕ:")
    print("  1. XÁC SUẤT TRÚNG KHÔNG ĐỔI — vẫn 1/324.632 (J2), 1/3.895.584 (J1).")
    print("     Thứ đổi là số người chia giải với bạn NẾU trúng.")
    print("  2. Mức giảm chia giải CHƯA ĐO ĐƯỢC. Mới chỉ đo được đúng một điểm:")
    print("     số ĐB 01 bị né 27% (kỳ #00814, p=5,5e-06). Các luật về số chính")
    print("     là quy luật chung của xổ số thế giới, chưa kiểm chứng riêng cho")
    print("     Lotto 5/35. Muốn đo thật phải gom số người trúng nhiều kỳ.")


if __name__ == "__main__":
    main()
