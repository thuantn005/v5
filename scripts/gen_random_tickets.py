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
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from references import _fair_from_seed, REPEAT_SEED_OFFSET  # noqa: E402

TICKET_SEED_STRIDE = 10_000_000
SIGNAL_SEED_OFFSET = 3_000_000_000
N_FAIR = 0     # nhóm random không lặp (0 = tắt)
N_REPEAT = 1   # 1 vé seed gốc "có lặp"
N_SIGNAL = 1   # 1 vé seed gốc "dấu hiệu"
N_COMBOS = 0   # số vé chọn từ TẤT CẢ tổ hợp (0 = tắt; bật bằng --combos)
RECENT_N = 0  # 0 = thống kê TẤT CẢ kỳ quay (>0 = chỉ N kỳ gần nhất)

MAIN_MIN, MAIN_MAX, MAIN_K = 1, 35, 5
SPECIAL_MIN, SPECIAL_MAX = 1, 12

# Bộ số cố định "Số của tôi" — ghim đầu dashboard (5 số chính + 1 ĐB).
MY_PICK_MAIN = [12, 13, 14, 21, 30]
MY_PICK_SPECIAL = 7


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
    ids = sorted((d for d in draws if d <= upto_draw), reverse=True)
    return ids if n <= 0 else ids[:n]  # n<=0 -> tất cả kỳ


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
    labels = {"ticket_neural": "Mạng nơ-ron (Perceptron)",
              "lstm_numpy": "LSTM NumPy", "lstm_tf": "LSTM TensorFlow"}
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
    ap.add_argument("--fair", type=int, default=N_FAIR)
    ap.add_argument("--repeat", type=int, default=N_REPEAT)
    ap.add_argument("--signal", type=int, default=N_SIGNAL)
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
    combo_tickets = _top_combo_tickets(draws, next_draw, prev_draw, a.combos) if a.combos > 0 else []

    # Chỉ giữ seed gốc (1 vé/nhóm ở trên) + các model AI; bỏ 2 mốc baseline.
    baselines = []
    models = _ai_models(next_draw)

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
        "groups": [g for g in [
            {"label": f"{len(combo_tickets)} vé chọn từ TẤT CẢ tổ hợp",
             "note": "quét toàn bộ 324.632 tổ hợp · chọn khớp ≥3 số nhiều nhất trong lịch sử "
                     "(survivorship — KHÔNG tăng cơ hội kỳ tới)",
             "method": "combos", "tickets": combo_tickets},
            {"label": f"{len(signal_tickets)} vé kết hợp 3 dấu hiệu lịch sử",
             "note": "nóng (tần suất) · quá hạn (lâu chưa ra) · đồng hành (hay ra cùng kỳ gần nhất)",
             "method": "signal", "tickets": signal_tickets},
            {"label": f"{len(repeat_tickets)} vé ngẫu nhiên (cho phép TRÙNG VÉ)", "method": "repeat",
             "note": "cho phép 2 vé trùng nhau · mỗi vé vẫn 5 số khác nhau", "tickets": repeat_tickets},
            {"label": f"{len(fair_tickets)} vé KHÔNG trùng nhau", "method": "fair",
             "note": "vé khác nhau · mỗi vé 5 số khác nhau", "tickets": fair_tickets},
        ] if g["tickets"]],
    }

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK: {len(models)} model AI + {len(signal_tickets)} dấu hiệu + {len(repeat_tickets)} có lặp "
          f"(seed gốc) cho kỳ #{next_draw} -> {a.out}")


if __name__ == "__main__":
    main()
