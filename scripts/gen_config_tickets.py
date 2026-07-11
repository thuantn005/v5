#!/usr/bin/env python3
"""gen_config_tickets.py — sinh bo ve ky toi cua TAT CA jackpot config cho dashboard.

Chay trong CI sau buoc cap nhat data:
    python scripts/gen_config_tickets.py --csv data/all.csv --out docs/config_tickets.json

Moi ticket xuat ra them:
  - last_result: {draw_id, draw_date, actual, predicted, main_hits, special_hit}
    (ky lien truoc next_draw -- ky vua quay, so sanh ve da sinh voi ket qua thuc)
"""
import argparse, csv, json, sys, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "configs"))
from jackpot_family import ticket, special, verify  # noqa: E402


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


def _compare(seed: int, draw_id: int, draws: dict) -> dict | None:
    """Doi chieu ve cua config `seed` voi ket qua thuc tai ky `draw_id`."""
    if draw_id not in draws:
        return None
    actual = draws[draw_id]
    predicted_main = ticket(seed, draw_id)
    predicted_sp = special(seed, draw_id)
    main_hits = len(set(predicted_main) & set(actual["numbers"]))
    special_hit = (predicted_sp == actual["special"]) if actual["special"] is not None else False
    return {
        "draw_id": draw_id,
        "draw_date": actual["draw_date"],
        "actual": actual["numbers"],
        "actual_special": actual["special"],
        "predicted": predicted_main,
        "predicted_special": predicted_sp,
        "main_hits": main_hits,
        "special_hit": bool(special_hit),
    }


def _recent(seed: int, draws: dict, upto_draw: int, n: int = 12) -> dict:
    """So sanh ve cua config voi ket qua thuc cua N ky gan nhat (<= upto_draw).

    Moi ky ve KHAC nhau (ticket(seed, draw_id)), nen day la doi chieu trung
    thuc: config nay le ra 'du doan' gi cho tung ky da qua, khop bao nhieu."""
    ids = sorted((d for d in draws if d <= upto_draw), reverse=True)[:n]
    items = [_compare(seed, d, draws) for d in ids]
    items = [x for x in items if x]
    total = sum(x["main_hits"] for x in items)
    return {
        "n": len(items),
        "avg_main_hits": round(total / len(items), 3) if items else 0.0,
        "special_hits": sum(1 for x in items if x["special_hit"]),
        "items": items,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/all.csv")
    ap.add_argument("--configs", default="configs/jackpot_configs.json")
    ap.add_argument("--out", default="docs/config_tickets.json")
    ap.add_argument("--draw", type=int, help="ky can sinh ve (mac dinh: ky moi nhat + 1)")
    ap.add_argument("--reverify", action="store_true", help="verify lai lich su tren CSV")
    a = ap.parse_args()

    draws = _load_draws(a.csv)
    next_draw = a.draw or max(draws) + 1
    prev_draw = next_draw - 1

    cfg = json.load(open(a.configs, encoding="utf-8"))
    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "next_draw": next_draw,
        "prev_draw": prev_draw,
        "prize": "Jackpot 2 — khop 5/5 so chinh",
        "disclaimer": ("Cac config nay tung trung 3 lan Jackpot 2 (5/5 so chinh) trong "
                       "qua khu do quet ~4.2 ty seed (survivorship). Xac suat ky toi cua "
                       "moi ve van la 1/324,632 — khong co edge. Chi giai tri."),
        "tickets": [],
    }

    for c in cfg["algorithm_configs"]:
        s = int(c["seed"])
        if a.reverify:
            got = verify(s, {k: v["numbers"] for k, v in draws.items()})
            want = [j["draw_id"] for j in c["jackpots"]]
            if sorted(got) != sorted(want):
                print(f"WARNING: seed {s}: got {got}, expected {want}", file=sys.stderr)
        out["tickets"].append({
            "id": f"seed-{s}", "type": "splitmix64", "seed": s,
            "name": c.get("name", f"seed {s}"),
            "numbers": ticket(s, next_draw), "special": special(s, next_draw),
            "history": c["jackpots"],
            "last_result": _compare(s, prev_draw, draws),
            "recent": _recent(s, draws, prev_draw),
        })

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK: {len(out['tickets'])} ve cho ky #{next_draw} -> {a.out}")


if __name__ == "__main__":
    main()
