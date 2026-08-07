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
import math
import random
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from references import _fair_from_seed, REPEAT_SEED_OFFSET  # noqa: E402

TICKET_SEED_STRIDE = 10_000_000
SIGNAL_SEED_OFFSET = 3_000_000_000
MOMENTUM_SEED_OFFSET = 5_000_000_000
N_SIGNAL = 50  # (giữ để tương thích) — nay dùng POOL/SHOW bên dưới
POOL_DEFAULT = 5   # số vé mỗi nhóm (sinh idx 1..5, hiển thị hết — không lọc)
SHOW_DEFAULT = 10    # số vé HIỂN THỊ mỗi nhóm = top theo backtest
RANK_WINDOW = 60     # số kỳ gần nhất để XẾP HẠNG NHANH pool (top hiển thị vẫn
                     # tính stats TOÀN lịch sử ở giai đoạn 2)
N_METHOD = 1   # số vé mỗi phương pháp phụ (recent/uniform/hot/cold/overdue)
N_COMBOS = 0   # số vé chọn từ TẤT CẢ tổ hợp (0 = tắt; bật bằng --combos)
RECENT_N = 0  # 0 = thống kê TẤT CẢ kỳ quay (>0 = chỉ N kỳ gần nhất)

MAIN_MIN, MAIN_MAX, MAIN_K = 1, 35, 5
SPECIAL_MIN, SPECIAL_MAX = 1, 12

# Bộ số cố định "Số của tôi" — vé THẬT đã mua (BIDV SP535, kỳ #00783,
# MT 25/07/2026 13:00). 5 số chính + 1 ĐB.
MY_PICK_MAIN = [11, 16, 20, 23, 27]
MY_PICK_SPECIAL = 5


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


DYNAMIC_HALF_LIFE = 50  # kỳ -- tốc độ suy giảm CỐ ĐỊNH TRƯỚC (không tùy theo
                        # từng kỳ cụ thể), nên không phải kiểu "thích nghi sau
                        # khi biết đáp án" mà là dấu hiệu hợp lệ như các dấu
                        # hiệu khác -- backtest cho thấy nó cũng không vượt
                        # được mức ngẫu nhiên.


def _components(draws: dict, draw_id: int) -> dict:
    """Các thành phần thống kê (chỉ dùng dữ liệu < draw_id) để dựng trọng số."""
    hist = [draws[d] for d in sorted(draws) if d < draw_id]
    total = len(hist)
    freq = Counter()
    last_seen = {}
    lam = math.log(2) / DYNAMIC_HALF_LIFE
    dynamic = [0.0] * 35
    for pos, dr in enumerate(hist):
        age = total - 1 - pos  # 0 = kỳ ngay trước draw_id
        decay = math.exp(-lam * age)
        for n in dr["numbers"]:
            freq[n] += 1
            last_seen[n] = pos
            dynamic[n - 1] += decay
    hot = [freq.get(n, 0) for n in range(MAIN_MIN, MAIN_MAX + 1)]
    overdue = [(total - 1 - last_seen.get(n, -1)) if n in last_seen else total
               for n in range(MAIN_MIN, MAIN_MAX + 1)]
    recent_nums = set(hist[-1]["numbers"]) if hist else set()
    comp = [0] * 35
    for dr in hist:
        if set(dr["numbers"]) & recent_nums:
            for n in dr["numbers"]:
                comp[n - 1] += 1
    rc = Counter()
    for dr in hist[-200:]:   # "gần đây" = 200 kỳ
        rc.update(dr["numbers"])
    recent = [rc.get(n, 0) for n in range(MAIN_MIN, MAIN_MAX + 1)]
    sf = Counter(dr["special"] for dr in hist if dr["special"] is not None)
    sfreq = [sf.get(s, 0) for s in range(SPECIAL_MIN, SPECIAL_MAX + 1)]
    return {"hot": hot, "overdue": overdue, "companion": comp, "recent": recent,
            "dynamic": dynamic, "sfreq": sfreq}


def _method_weight(c: dict, kind: str):
    """Trọng số mỗi số theo từng phương pháp (đều >0 để mọi số còn cơ hội)."""
    if kind == "uniform":
        return [1.0] * 35, [1.0] * 12
    if kind == "hot":
        base = _norm(c["hot"])
    elif kind == "cold":
        mx = max(c["hot"])
        base = _norm([mx - x for x in c["hot"]])
    elif kind == "overdue":
        base = _norm(c["overdue"])
    elif kind == "companion":
        base = _norm(c["companion"])
    elif kind == "recent":
        base = _norm(c["recent"])
    elif kind == "dynamic":  # cửa sổ động: trọng số suy giảm mượt theo half-life
        base = _norm(c["dynamic"])
    elif kind == "momentum":
        # QUÁN TÍNH pha NGẪU NHIÊN: 40% đà gần đây (dynamic, suy giảm mượt) +
        # 60% nền phẳng — giữ đúng tinh thần momentum_seeded trong strategies.py.
        # Nền phẳng khiến việc bốc số vẫn trải rộng, chỉ nghiêng nhẹ về số
        # đang "có đà". Backtest: ngang ngẫu nhiên (p≈0.5), không có lợi thế.
        dyn = _norm(c["dynamic"])
        base = [0.4 * dyn[i] + 0.6 for i in range(35)]
    else:  # signal3 = kết hợp 3 dấu hiệu: tần suất gần đây + toàn lịch sử + số kỳ vắng mặt
        r, h, o = _norm(c["recent"]), _norm(c["hot"]), _norm(c["overdue"])
        base = [r[i] + h[i] + o[i] for i in range(35)]
    w = [0.1 + base[i] for i in range(35)]
    sw = [0.1 + c["sfreq"][i] for i in range(12)]
    return w, sw


# Nhiều CÔNG THỨC kết hợp 3 dấu hiệu (recent=gần đây, hot=toàn lịch sử, overdue=vắng mặt)
# (nhãn, (hệ số recent, hot, overdue), chế độ)
SIGNAL_FORMULAS = [
    ("Cân bằng (1·1·1)",              (1, 1, 1), "sum"),
    ("Ưu tiên gần đây (2·1·1)",       (2, 1, 1), "sum"),
    ("Ưu tiên lịch sử (1·2·1)",       (1, 2, 1), "sum"),
    ("Ưu tiên vắng mặt (1·1·2)",      (1, 1, 2), "sum"),
    ("Gần đây + vắng mặt (1·0·1)",    (1, 0, 1), "sum"),
    ("Lịch sử + vắng mặt (0·1·1)",    (0, 1, 1), "sum"),
    ("Gần đây + lịch sử (1·1·0)",     (1, 1, 0), "sum"),
    ("Chỉ gần đây (1·0·0)",           (1, 0, 0), "sum"),
    ("Chỉ vắng mặt (0·0·1)",          (0, 0, 1), "sum"),
    ("Nhân 3 dấu hiệu",               (1, 1, 1), "prod"),
    ("Nghịch vắng mặt (gần+lịch−vắng)", (1, 1, 1), "diff"),
    ("Gần đây rất mạnh (3·1·1)",      (3, 1, 1), "sum"),
]


def _formula_weight(c: dict, coeffs, mode: str):
    r, h, o = _norm(c["recent"]), _norm(c["hot"]), _norm(c["overdue"])
    a, b, k = coeffs
    if mode == "prod":
        base = [(0.05 + r[i]) ** a * (0.05 + h[i]) ** b * (0.05 + o[i]) ** k for i in range(35)]
    elif mode == "diff":
        base = [a * r[i] + b * h[i] - k * o[i] for i in range(35)]
    else:  # sum
        base = [a * r[i] + b * h[i] + k * o[i] for i in range(35)]
    mn = min(base)
    return [0.1 + (base[i] - mn) for i in range(35)]


def _make_formula_gen(comps: dict, coeffs, mode: str, offset: int):
    def gen(idx: int, draw_id: int):
        c = comps[draw_id]
        w = _formula_weight(c, coeffs, mode)
        sw = [0.1 + c["sfreq"][i] for i in range(12)]
        rng = random.Random(draw_id + offset)
        return _wsample(rng, w, MAIN_K), _wchoice(rng, sw)
    return gen


def _make_method_gen(comps: dict, kind: str, offset: int):
    """gen(idx, draw_id) -> vé lấy mẫu ngẫu nhiên có seed, theo phương pháp kind."""
    def gen(idx: int, draw_id: int):
        c = comps[draw_id]
        w, sw = _method_weight(c, kind)
        rng = random.Random(draw_id + offset + idx * TICKET_SEED_STRIDE)
        return _wsample(rng, w, MAIN_K), _wchoice(rng, sw)
    return gen


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
    ids = sorted((d for d in draws if d <= upto_draw), reverse=True)
    return ids if n <= 0 else ids[:n]  # n<=0 -> tất cả kỳ


def _recent_stats(gen_fn, idx: int, draws: dict, recent_ids) -> dict:
    """Thống kê chỉ tính TRÚNG khi khớp >=3 số chính (giải thấp nhất).

    Phân biệt rõ:
      - tier5      = khớp ĐÚNG 5 số chính (Jackpot 2), KHÔNG cần ĐB.
      - jackpot1   = khớp 5 số chính VÀ ĐB (Jackpot 1 = 6 số), tập con của tier5.
    """
    cnt = sp = best = jp1 = 0
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
                if mh == 5:
                    jp1 += 1
    return {
        "n": cnt,
        "wins": tier[3] + tier[4] + tier[5],  # số lần trúng >=3 số
        "tier3": tier[3], "tier4": tier[4], "tier5": tier[5],
        "jackpot1": jp1,  # trúng 6 số (5 chính + ĐB), tập con của tier5
        "best": best, "special_hits": sp,
    }


def _jackpot_history(gen_fn, idx: int, draws: dict) -> list[dict]:
    """Các kỳ mà vé (idx) từng khớp ĐỦ 5 số chính (jackpot) trong lịch sử.
    tier='J1' nếu khớp cả ĐB (Jackpot 1), 'J2' nếu đúng 5 chính nhưng trượt ĐB."""
    out = []
    for d in sorted(draws):
        act = draws[d]
        if act.get("numbers") is None:
            continue
        main, sp = gen_fn(idx, d)
        if len(set(main) & set(act["numbers"])) == 5:
            j1 = (sp == act.get("special"))
            out.append({"draw_id": d, "draw_date": act.get("draw_date", ""),
                        "tier": "J1" if j1 else "J2", "special_hit": bool(j1),
                        "numbers": sorted(main), "special": sp})
    return out


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


def _rank_stats(r: dict):
    """Điểm xếp hạng HƯỚNG JACKPOT: chỉ nhắm giải cao nhất (5 số chính + ĐB).
    Thứ tự ưu tiên:
      1. jackpot1  — trúng 5 số chính VÀ ĐB (Jackpot 1, mục tiêu duy nhất)
      2. tier5     — trúng đúng 5 số chính (Jackpot 2, sát jackpot)
      3. tier4     — trúng 4 số chính (gần)
      4. special_hits — số lần trúng ĐB (phần ĐB của jackpot)
      5. best / tier3 — mức khớp tốt nhất & 3 số (phá hòa)"""
    return (r.get("jackpot1", 0), r.get("tier5", 0), r.get("tier4", 0),
            r.get("special_hits", 0), r.get("best", 0), r.get("tier3", 0))


def _rank(t):
    """Xếp hạng một VÉ (đã có sẵn thống kê 'recent')."""
    return _rank_stats(t.get("recent") or {})


def _top_combo_tickets(draws: dict, next_draw: int, prev_draw: int, top_n: int) -> list[dict]:
    """Quét TẤT CẢ tổ hợp 5/35, đối chiếu với mọi kỳ lịch sử, chọn top_n tổ hợp
    khớp >=3 số nhiều nhất. LƯU Ý: đây là survivorship (chọn theo quá khứ) —
    KHÔNG tăng cơ hội kỳ tới; mọi tổ hợp vẫn 1/324.632."""
    hist_ids = [d for d in sorted(draws) if d <= prev_draw]
    universe = list(range(MAIN_MIN, MAIN_MAX + 1))
    tier: dict[tuple, list] = {}          # combo -> [t3, t4, t5]
    sfreq = Counter()
    for d in hist_ids:
        rec = draws[d]
        D = rec["numbers"]
        if rec["special"] is not None:
            sfreq[rec["special"]] += 1
        Dset = set(D)
        non = [n for n in universe if n not in Dset]
        # khớp đúng 5
        e = tier.get(tuple(D))
        if e:
            e[2] += 1
        else:
            tier[tuple(D)] = [0, 0, 1]
        # khớp đúng 4: 4 số của kỳ + 1 số ngoài
        for s4 in combinations(D, 4):
            for x in non:
                k = tuple(sorted(s4 + (x,)))
                e = tier.get(k)
                if e:
                    e[1] += 1
                else:
                    tier[k] = [0, 1, 0]
        # khớp đúng 3: 3 số của kỳ + 2 số ngoài
        for s3 in combinations(D, 3):
            for e2 in combinations(non, 2):
                k = tuple(sorted(s3 + e2))
                e = tier.get(k)
                if e:
                    e[0] += 1
                else:
                    tier[k] = [1, 0, 0]

    ranked = sorted(
        tier.items(),
        key=lambda it: (sum(it[1]), it[1][2] * 1000 + it[1][1] * 100 + it[1][0] * 10),
        reverse=True,
    )[:top_n]
    top_combos = [c for c, _ in ranked]

    # Chọn số ĐB cho mỗi tổ hợp: số ĐB hay xuất hiện nhất trong các kỳ mà tổ hợp
    # khớp >=3 (độc lập với số chính).
    combo_sets = [(c, set(c)) for c in top_combos]
    spec_tally = {c: Counter() for c in top_combos}
    for d in hist_ids:
        Dset = set(draws[d]["numbers"])
        sp = draws[d]["special"]
        for c, cs in combo_sets:
            if len(cs & Dset) >= 3:
                spec_tally[c][sp] += 1

    hottest_sp = sfreq.most_common(1)[0][0] if sfreq else 1
    tickets = []
    for rank, (c, (t3, t4, t5)) in enumerate(ranked, 1):
        st = spec_tally[c]
        special = st.most_common(1)[0][0] if st and st.most_common(1)[0][0] is not None else hottest_sp
        best = 5 if t5 else 4 if t4 else 3 if t3 else 0
        tickets.append({
            "id": f"C{rank:02d}",
            "numbers": list(c), "special": special,
            "trace": f"L535-{next_draw}-C{rank:02d}",
            "recent": {"n": len(hist_ids), "wins": t3 + t4 + t5,
                       "tier3": t3, "tier4": t4, "tier5": t5,
                       "best": best, "special_hits": sfreq.get(special, 0)},
            "last_result": _compare(list(c), special, prev_draw, draws),
        })
    return tickets


def _ai_models(next_draw: int) -> list[dict]:
    """Đọc dự đoán model AI (Neural, LSTM NumPy, LSTM TF) cho kỳ tới từ
    state/ensemble_log.jsonl (do run_pipeline ghi sẵn — out-of-sample thật), kèm
    đối chiếu kỳ resolved gần nhất. Lưu ý: backtest cho thấy đều ~ ngẫu nhiên."""
    try:
        from multi_log import load_log
        entries = load_log()
    except Exception:
        entries = []
    if not entries:
        return []
    latest = next((e for e in reversed(entries)
                   if str(e.get("target_draw_id")).isdigit()
                   and int(e["target_draw_id"]) == next_draw), None) or entries[-1]
    resolved = [e for e in entries if e.get("resolved") and e.get("actual")]
    prev = resolved[-1] if resolved else None
    labels = {"ticket_neural": "Mạng nơ-ron (Perceptron)"}
    out = []
    ps = latest.get("per_strategy") or {}
    for key, label in labels.items():
        pk = ps.get(key)
        if not pk or not pk.get("main"):
            continue
        lr = None
        if prev:
            pp = (prev.get("per_strategy") or {}).get(key)
            act = prev.get("actual") or {}
            h = (prev.get("hits") or {}).get(key) or {}
            if pp and pp.get("main") and act:
                lr = {
                    "draw_id": int(prev["target_draw_id"]), "draw_date": act.get("draw_date"),
                    "actual": act["main"], "actual_special": act["special"],
                    "predicted": pp["main"], "predicted_special": pp["special"],
                    "main_hits": h.get("main_hits", len(set(pp["main"]) & set(act["main"]))),
                    "special_hit": bool(h.get("special_hit", pp["special"] == act["special"])),
                }
        out.append({"id": label, "label": label, "numbers": pk["main"],
                    "special": pk["special"], "trace": pk.get("trace"), "last_result": lr})
    return out


def _r_model(draws: dict, next_draw: int, prev_draw: int, csv_path: str) -> dict | None:
    """Chạy mô hình R (scripts/r_model.R) để lấy dự đoán kỳ tới + đối chiếu kỳ
    trước. Graceful: nếu không có Rscript hoặc lỗi thì trả None (bỏ qua model)."""
    import shutil
    import subprocess
    if not shutil.which("Rscript"):
        return None
    r_script = str(Path(__file__).resolve().parent / "r_model.R")

    def run(target: int):
        try:
            r = subprocess.run(
                ["Rscript", r_script, "--csv", csv_path, "--draw", str(target)],
                capture_output=True, text=True, timeout=90)
            if r.returncode != 0 or not r.stdout.strip():
                return None
            pred = json.loads(r.stdout.strip().splitlines()[-1])
            if not pred.get("main") or len(set(pred["main"])) != 5:
                return None
            return pred
        except Exception:
            return None

    pred = run(next_draw)
    if not pred:
        return None
    lr = None
    prevp = run(prev_draw)
    if prevp and prev_draw in draws:
        lr = _compare(sorted(prevp["main"]), prevp["special"], prev_draw, draws)
    label = "Random Forest (R)"
    return {"id": label, "label": label, "numbers": sorted(pred["main"]),
            "special": pred["special"], "trace": pred.get("trace"), "last_result": lr}


def _fixed_ticket(main: list, special: int, draws: dict, next_draw: int, prev_draw: int) -> dict:
    """Vé cố định (số không đổi mỗi kỳ) — thống kê qua toàn bộ lịch sử."""
    mset = set(main)
    hist_ids = [d for d in sorted(draws) if d <= prev_draw]
    tier = {3: 0, 4: 0, 5: 0}
    sp_hits = jackpot1 = best = 0
    for d in hist_ids:
        act = draws[d]
        mh = len(mset & set(act["numbers"]))
        best = max(best, mh)
        if mh >= 3:
            tier[mh] = tier.get(mh, 0) + 1
        if act["special"] == special:
            sp_hits += 1
            if mh == 5:
                jackpot1 += 1
    return {
        "id": "MY", "numbers": list(main), "special": special,
        "trace": f"L535-{next_draw}-MY",
        "recent": {"n": len(hist_ids), "wins": tier[3] + tier[4] + tier[5],
                   "tier3": tier[3], "tier4": tier[4], "tier5": tier[5],
                   "best": best, "special_hits": sp_hits, "jackpot1": jackpot1},
        "last_result": _compare(list(main), special, prev_draw, draws),
    }


def _special_backtest(specials: list, warmup: int = 50) -> dict:
    """Backtest walk-forward các chiến lược chọn ĐB: mỗi kỳ chỉ dùng dữ liệu
    TRƯỚC kỳ đó để chọn, rồi xem có trúng ĐB kỳ đó không. So với mức 1/12."""
    n = len(specials)
    if n <= warmup + 5:
        return {}
    freq = Counter()
    last = {}
    hit = {"nóng": 0, "quá hạn": 0, "cân bằng": 0, "lạnh": 0}
    tested = 0
    for i, actual in enumerate(specials):
        if i >= warmup:
            counts = [freq.get(k, 0) for k in range(SPECIAL_MIN, SPECIAL_MAX + 1)]
            gaps = [(i - 1 - last[k]) if k in last else i
                    for k in range(SPECIAL_MIN, SPECIAL_MAX + 1)]
            hot = SPECIAL_MIN + max(range(len(counts)), key=lambda k: (counts[k], -k))
            cold = SPECIAL_MIN + min(range(len(counts)), key=lambda k: (counts[k], k))
            overdue = SPECIAL_MIN + max(range(len(gaps)), key=lambda k: (gaps[k], -k))
            nc, ng = _norm(counts), _norm(gaps)
            bal = SPECIAL_MIN + max(range(len(counts)), key=lambda k: nc[k] + ng[k])
            if hot == actual: hit["nóng"] += 1
            if overdue == actual: hit["quá hạn"] += 1
            if bal == actual: hit["cân bằng"] += 1
            if cold == actual: hit["lạnh"] += 1
            tested += 1
        freq[actual] += 1
        last[actual] = i
    return {
        "tested": tested,
        "expected_pct": round(100 / (SPECIAL_MAX - SPECIAL_MIN + 1), 2),
        "pct": {k: round(100 * v / tested, 2) for k, v in hit.items()},
    }


def _special_advice(draws: dict, prev_draw: int) -> dict:
    """Tham mưu chọn số đặc biệt (1..12): tần suất, số kỳ chưa ra (quá hạn), và
    gợi ý theo 2 hướng (nóng nhất / quá hạn nhất). LƯU Ý: mọi số ĐB đều 1/12 —
    đây chỉ là phân tích mô tả quá khứ, KHÔNG tăng cơ hội trúng."""
    hist = [draws[d] for d in sorted(draws) if d <= prev_draw]
    total = len(hist)
    freq = Counter()
    last_pos = {}
    for pos, dr in enumerate(hist):
        s = dr.get("special")
        if s is not None:
            freq[s] += 1
            last_pos[s] = pos
    table = []
    for n in range(SPECIAL_MIN, SPECIAL_MAX + 1):
        cnt = freq.get(n, 0)
        gap = (total - 1 - last_pos[n]) if n in last_pos else total  # số kỳ chưa ra
        table.append({
            "n": n, "count": cnt,
            "pct": round(100 * cnt / total, 1) if total else 0.0,
            "gap": gap,
        })
    hot = max(table, key=lambda x: (x["count"], -x["n"]))["n"]
    overdue = max(table, key=lambda x: (x["gap"], -x["n"]))["n"]
    # điểm cân bằng: chuẩn hoá tần suất + quá hạn rồi cộng
    cs = [t["count"] for t in table]
    gs = [t["gap"] for t in table]
    ncs, ngs = _norm(cs), _norm(gs)
    balanced = max(range(len(table)), key=lambda i: ncs[i] + ngs[i])
    specials = [dr["special"] for dr in hist if dr.get("special") is not None]
    return {
        "total": total,
        "expected_pct": round(100 / (SPECIAL_MAX - SPECIAL_MIN + 1), 1),  # 8.3%
        "table": table,
        "hot": hot,           # ra nhiều nhất
        "overdue": overdue,   # lâu chưa ra nhất
        "balanced": table[balanced]["n"],  # cân bằng nóng + quá hạn
        "backtest": _special_backtest(specials),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/all.csv")
    ap.add_argument("--out", default="docs/random_tickets.json")
    ap.add_argument("--signal", type=int, default=N_SIGNAL,
                    help="(cũ, không dùng) — thay bằng --pool/--show")
    ap.add_argument("--pool", type=int, default=POOL_DEFAULT,
                    help="số vé ỨNG VIÊN sinh ra mỗi nhóm (chỉ để lọc)")
    ap.add_argument("--show", type=int, default=SHOW_DEFAULT,
                    help="số vé HIỂN THỊ mỗi nhóm = top theo backtest")
    ap.add_argument("--per-method", type=int, default=N_METHOD,
                    help="số vé mỗi phương pháp phụ")
    ap.add_argument("--combos", type=int, default=N_COMBOS,
                    help="số vé chọn từ tất cả tổ hợp (trúng >=3 số nhiều nhất)")
    ap.add_argument("--recent-n", type=int, default=RECENT_N)
    ap.add_argument("--draw", type=int, help="kỳ cần sinh vé (mặc định: kỳ mới nhất + 1)")
    a = ap.parse_args()

    draws = _load_draws(a.csv)
    if not draws:
        sys.exit(f"Không đọc được kỳ nào từ {a.csv}")
    next_draw = a.draw or max(draws) + 1
    prev_draw = next_draw - 1
    recent_ids = _recent_ids(draws, prev_draw, a.recent_n)

    rank_ids = recent_ids if len(recent_ids) <= RANK_WINDOW else recent_ids[:RANK_WINDOW]

    def _mk(gen_fn, idx, tid, offset_base):
        seed = next_draw + offset_base + idx * TICKET_SEED_STRIDE
        return _build_ticket(gen_fn, idx, next_draw, prev_draw, draws, tid, recent_ids, seed)

    def build_group(gen_fn, pool, prefix, offset_base):
        """Trả về ĐÚNG `pool` vé gốc (idx 1..pool) — KHÔNG quét/lọc pool lớn.

        Mỗi vé là một VÉ GỐC của phương pháp: số đổi theo kỳ theo công thức +
        seed riêng, tái lập được. Không có bước 'giai đoạn 2' lọc từ hàng nghìn
        ứng viên nữa (lọc theo backtest là survivorship, không tăng cơ hội).
        """
        tickets = []
        for i in range(1, pool + 1):
            t = _mk(gen_fn, i, f"{prefix}{i:03d}", offset_base)
            t["name"] = f"🎯 Vé gốc {i}"
            t["badge"] = "GỐC"
            t["jackpot_history"] = _jackpot_history(gen_fn, i, draws)
            tickets.append(t)
        return tickets

    # Tính trước các thành phần (dùng chung cho mọi phương pháp lấy mẫu)
    comps = {d: _components(draws, d) for d in (set(recent_ids) | {next_draw})}

    # NHIỀU PHƯƠNG PHÁP — tất cả đều LẤY MẪU NGẪU NHIÊN CÓ SEED
    method_groups = []

    # NHÓM "Kết hợp 3 dấu hiệu": nhiều VÉ GỐC (S001, S002...) — CÙNG 1 công thức,
    # mỗi vé 1 seed, số đổi mỗi kỳ theo seed (KHÔNG phải vé cố định).
    sig_gen = _make_method_gen(comps, "signal3", SIGNAL_SEED_OFFSET)
    sig_tickets = build_group(sig_gen, a.pool, "S", SIGNAL_SEED_OFFSET)
    # Vé gốc (S001) của signal3 chính là dự đoán tất định (đã trúng J1 kỳ #374).
    if sig_tickets:
        sig_tickets[0]["name"] = "🔮 Vé gốc — Dự đoán (S001)"
    method_groups.append({
        "label": f"Kết hợp 3 dấu hiệu lịch sử — {a.pool} vé gốc (S001…S{a.pool:03d})",
        "note": "gần đây (200 kỳ) + toàn lịch sử + số kỳ vắng mặt · mỗi vé 1 seed, "
                "số đổi theo kỳ theo công thức. LƯU Ý: mọi vé đều 1/324.632 (J2) và "
                "1/3.895.584 (J1) như nhau — lịch sử jackpot bên dưới là quá khứ, "
                "KHÔNG làm vé dễ trúng kỳ tới hơn.",
        "method": "signal3", "tickets": sig_tickets,
    })

    # "Chọn ngẫu nhiên có thể lặp lại" (mốc so sánh) — cũng NHIỀU vé gốc, bằng số
    # với nhóm chính để so sánh công bằng.
    uni_gen = _make_method_gen(comps, "uniform", 9_000_000_000)
    uni_tickets = build_group(uni_gen, a.pool, "U", 9_000_000_000)
    method_groups.append({
        "label": f"Chọn ngẫu nhiên có thể lặp lại — {a.pool} vé gốc (U001…U{a.pool:03d})",
        "note": "mốc so sánh công bằng — thuần ngẫu nhiên, mỗi vé 1 seed tái lập",
        "method": "uniform", "tickets": uni_tickets,
    })

    # "Ngẫu nhiên quán tính": vẫn bốc ngẫu nhiên có seed, chỉ nghiêng nhẹ về
    # những số đang "có đà" (cửa sổ động, suy giảm mượt).
    mom_gen = _make_method_gen(comps, "momentum", MOMENTUM_SEED_OFFSET)
    mom_tickets = build_group(mom_gen, a.pool, "M", MOMENTUM_SEED_OFFSET)
    method_groups.append({
        "label": f"Chọn ngẫu nhiên quán tính — {a.pool} vé gốc (M001…M{a.pool:03d})",
        "note": "40% đà gần đây (cửa sổ động) + 60% nền phẳng · mỗi vé 1 seed tái lập. "
                "LƯU Ý: backtest cho thấy quán tính NGANG ngẫu nhiên thuần "
                "(p≈0.5, không có ý nghĩa thống kê) — đây là cách bốc số khác, "
                "KHÔNG phải lợi thế.",
        "method": "momentum", "tickets": mom_tickets,
    })

    # (Chỉ giữ 3 nhóm: signal3 + uniform + momentum. Các nhóm recent/hot/cold/
    #  overdue/companion/dynamic đã bỏ theo yêu cầu.)

    combo_tickets = _top_combo_tickets(draws, next_draw, prev_draw, a.combos) if a.combos > 0 else []

    # Chỉ giữ seed gốc (1 vé/nhóm ở trên) + các model AI; bỏ 2 mốc baseline.
    baselines = []
    models = _ai_models(next_draw)
    r_model = _r_model(draws, next_draw, prev_draw, a.csv)
    if r_model:
        models.append(r_model)

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "next_draw": next_draw, "prev_draw": prev_draw, "recent_n": a.recent_n,
        "disclaimer": ("Mọi vé đều gồm 5 SỐ KHÁC NHAU (hợp lệ). Nhóm '50 vé từ tất cả tổ hợp' "
                       "được chọn vì TRÚNG NHIỀU TRONG QUÁ KHỨ (survivorship) — điều này KHÔNG "
                       "làm chúng dễ trúng kỳ tới hơn; mọi tổ hợp vẫn 1/324.632. Chơi có trách nhiệm."),
        "my_pick": _fixed_ticket(MY_PICK_MAIN, MY_PICK_SPECIAL, draws, next_draw, prev_draw),
        "models": models,
        "special_advice": _special_advice(draws, prev_draw),
        "baselines": baselines,
        "groups": [g for g in (
            ([{"label": f"{len(combo_tickets)} vé chọn từ TẤT CẢ tổ hợp",
               "note": "quét toàn bộ 324.632 tổ hợp (survivorship — KHÔNG tăng cơ hội kỳ tới)",
               "method": "combos", "tickets": combo_tickets}] if combo_tickets else [])
            + method_groups
        ) if g["tickets"]],
    }

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK: {len(models)} model AI + {len(method_groups)} phương pháp "
          f"cho kỳ #{next_draw} -> {a.out}")


if __name__ == "__main__":
    main()
