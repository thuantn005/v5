#!/usr/bin/env python3
"""monthly_plan.py — MODEL "mỗi tháng mua 5 vé, 1 lần".

Mỗi tháng sinh ĐÚNG 5 vé (tái lập được từ seed = tháng), để mua MỘT lần trong
tháng đó. Cùng một tháng luôn cho cùng 5 vé -> ai cũng kiểm chứng lại được.

CÁCH CHỌN SỐ: ưu tiên bộ "ÍT PHỔ BIẾN" (có số 32-35, không 2 số liên tiếp,
không dồn số nhỏ kiểu ngày sinh) và KHÔNG trùng nhau.

  Vì sao? Chọn số KHÔNG làm tăng cơ hội trúng (mọi bộ đều 1/324.632). Nhưng nếu
  trúng, tiền được CHIA ĐỀU cho những người cùng trúng bộ đó — nên bộ ít người
  đánh giúp bạn ít phải chia hơn. Đây là lợi ích THẬT duy nhất mà toán học ủng
  hộ; nó tăng SỐ TIỀN NHẬN NẾU TRÚNG, không tăng KHẢ NĂNG TRÚNG.

Dùng:
    python3 scripts/monthly_plan.py                 # tháng hiện tại
    python3 scripts/monthly_plan.py --month 2026-09
    python3 scripts/monthly_plan.py --price 10000   # giá 1 vé (VND)
"""
from __future__ import annotations
import argparse
import csv
import datetime
import hashlib
import json
import random
from math import comb
from pathlib import Path

MAIN_MIN, MAIN_MAX, MAIN_K = 1, 35, 5
SPECIAL_MIN, SPECIAL_MAX = 1, 12
N_TICKETS = 5

C_MAIN = comb(MAIN_MAX, MAIN_K)                 # 324.632
P_J2 = 1 / C_MAIN                               # đúng 5 số chính
P_J1 = 1 / (C_MAIN * SPECIAL_MAX)               # 5 số chính + ĐB
P_ANY = (comb(5, 3) * comb(30, 2) + comb(5, 4) * comb(30, 1) + 1) / C_MAIN  # >=3 số


def _month_seed(month: str) -> int:
    """Seed tất định từ chuỗi 'YYYY-MM' -> cùng tháng luôn ra cùng 5 vé."""
    h = hashlib.sha256(f"lotto535|monthly|{month}".encode()).hexdigest()
    return int(h[:16], 16)


def _past_combos(csv_path: str) -> set[tuple]:
    past = set()
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    past.add(tuple(sorted(json.loads(row["result_json"])["numbers"])))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return past


def _unpopular(c: tuple[int, ...]) -> bool:
    """Bộ số 'ít người đánh': có số cao, không liên tiếp, không dồn số nhỏ."""
    c = sorted(c)
    if any(c[i + 1] - c[i] == 1 for i in range(len(c) - 1)):
        return False                       # tránh 2 số liên tiếp
    if max(c) < 32:
        return False                       # cần ít nhất 1 số 32-35
    if sum(1 for x in c if x > 24) < 2:
        return False                       # đủ số lớn
    if sum(1 for x in c if x <= 12) > 2:
        return False                       # tránh dồn "ngày sinh"
    return True


def build_tickets(month: str, past: set[tuple], n: int = N_TICKETS) -> list[dict]:
    rng = random.Random(_month_seed(month))
    tickets, seen = [], set()
    guard = 0
    while len(tickets) < n and guard < 500_000:
        guard += 1
        main = tuple(sorted(rng.sample(range(MAIN_MIN, MAIN_MAX + 1), MAIN_K)))
        if main in seen or main in past or not _unpopular(main):
            continue
        seen.add(main)
        tickets.append({
            "id": f"M{len(tickets) + 1}",
            "numbers": list(main),
            "special": rng.randint(SPECIAL_MIN, SPECIAL_MAX),
        })
    return tickets


def main():
    today = datetime.date.today()
    ap = argparse.ArgumentParser(description="Model: mỗi tháng mua 5 vé, 1 lần")
    ap.add_argument("--month", default=f"{today:%Y-%m}", help="tháng YYYY-MM")
    ap.add_argument("--csv", default="data/all.csv")
    ap.add_argument("--price", type=int, default=10_000, help="giá 1 vé (VND)")
    ap.add_argument("--n", type=int, default=N_TICKETS, help="số vé mỗi tháng")
    ap.add_argument("--json", help="ghi kết quả ra file JSON")
    ap.add_argument("--min-jackpot", type=float, default=20e9,
                    help="CHỈ hiện vé khi Độc Đắc >= mức này (VND, mặc định 20 tỷ)")
    ap.add_argument("--state", default="state/jackpot_state.json",
                    help="file trạng thái để đọc giá trị Độc Đắc hiện tại")
    ap.add_argument("--force", action="store_true", help="bỏ qua cổng lọc, hiện vé luôn")
    a = ap.parse_args()

    # ── CỔNG LỌC EV: chỉ mua khi pot lớn ────────────────────────────────────
    # Xác suất KHÔNG đổi (luôn 1/3.895.584 cho J1). Nhưng pot càng lớn thì mỗi
    # vé càng ĐÁNG GIÁ hơn: EV(J1) = pot / 3.895.584. Nên mua khi pot cao là
    # lựa chọn hợp lý về giá trị — KHÔNG phải vì "dễ trúng hơn".
    jackpot = 0
    try:
        jackpot = int(json.load(open(a.state, encoding="utf-8")).get("peak_jackpot") or 0)
    except Exception:
        pass
    ev_j1 = jackpot * P_J1
    if jackpot and not a.force and jackpot < a.min_jackpot:
        print(f"⏸️  CHƯA MUA THÁNG NÀY — Độc Đắc {jackpot/1e9:.2f} tỷ "
              f"< ngưỡng {a.min_jackpot/1e9:.0f} tỷ")
        print(f"    EV từ J1 hiện chỉ {ev_j1:,.0f} đ/vé (giá vé {a.price:,} đ) — chờ pot lớn hơn.")
        print(f"    Muốn xem vé bất chấp: thêm --force  ·  đổi ngưỡng: --min-jackpot 12e9")
        print("\n    Lưu ý: chờ pot lớn KHÔNG làm tăng xác suất trúng (luôn 1/3.895.584);")
        print("    nó chỉ làm mỗi đồng bỏ ra đáng giá hơn NẾU trúng.")
        return

    past = _past_combos(a.csv)
    tickets = build_tickets(a.month, past, a.n)
    n = len(tickets)
    cost_month = n * a.price

    print(f"═══ MODEL: MUA {n} VÉ / THÁNG (1 lần) — tháng {a.month} ═══\n")
    if jackpot:
        below = jackpot < a.min_jackpot
        head = (f"⚠️  HIỆN VÉ DÙ CHƯA ĐẠT NGƯỠNG (--force) — Độc Đắc {jackpot/1e9:.2f} tỷ "
                f"< {a.min_jackpot/1e9:.0f} tỷ") if below else \
               (f"✅ MỞ MUA — Độc Đắc {jackpot/1e9:.2f} tỷ (>= ngưỡng {a.min_jackpot/1e9:.0f} tỷ)")
        print(head)
        print(f"   EV từ J1: {ev_j1:,.0f} đ/vé so với giá {a.price:,} đ "
              f"({ev_j1/a.price*100:.0f}% giá vé)\n")
    print(f"{'Vé':<4} {'5 số chính':<22} {'ĐB'}")
    for t in tickets:
        nums = "  ".join(f"{x:02d}" for x in t["numbers"])
        print(f"{t['id']:<4} {nums:<22} {t['special']:02d}")

    p_any = 1 - (1 - P_ANY) ** n
    p_j2 = 1 - (1 - P_J2) ** n
    p_j1 = 1 - (1 - P_J1) ** n

    print(f"\n── Chi phí ──")
    print(f"  {n} vé × {a.price:,} đ = {cost_month:,} đ/tháng  ·  {cost_month * 12:,} đ/năm")

    print(f"\n── Cơ hội của LẦN MUA này ({n} vé, 1 kỳ) ──")
    print(f"  Trúng bất kỳ giải (>=3 số) : {p_any * 100:6.3f} %   (~1/{1 / p_any:,.0f})")
    print(f"  Jackpot 2 (5 số chính)     : {p_j2 * 100:6.5f} %   (~1/{1 / p_j2:,.0f})")
    print(f"  Jackpot 1 (5 số + ĐB)      : {p_j1 * 100:6.5f} %   (~1/{1 / p_j1:,.0f})")

    print(f"\n── Nếu duy trì 1 năm (12 lần mua = {n * 12} vé) ──")
    for label, p in (("Trúng bất kỳ giải", P_ANY), ("Jackpot 2", P_J2), ("Jackpot 1", P_J1)):
        py = 1 - (1 - p) ** (n * 12)
        print(f"  {label:<20}: {py * 100:6.3f} %  (~1/{1 / py:,.0f})")
    print(f"  Kỳ vọng số lần trúng >=3 số/năm: {n * 12 * P_ANY:.2f}")

    print("\n⚠️  SỰ THẬT: chọn số KHÔNG tăng cơ hội trúng — mọi bộ đều 1/324.632 (J2)")
    print("    và 1/3.895.584 (J1) mỗi kỳ. Lợi ích duy nhất của bộ 'ít phổ biến' là")
    print("    NẾU trúng thì ít phải chia giải hơn. Kỳ vọng tiền vẫn ÂM — hãy coi")
    print(f"    {cost_month:,} đ/tháng là tiền GIẢI TRÍ, chỉ chi số tiền sẵn sàng mất.")

    if a.json:
        out = {"month": a.month, "tickets": tickets, "price": a.price,
               "cost_month": cost_month, "cost_year": cost_month * 12,
               "p_any_draw": p_any, "p_jackpot2": p_j2, "p_jackpot1": p_j1}
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n💾 Đã lưu: {a.json}")


if __name__ == "__main__":
    main()
