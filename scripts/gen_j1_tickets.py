#!/usr/bin/env python3
"""gen_j1_tickets.py — sinh bo ve ky toi cho cac config J1-DOUBLE (repo v5).

J1-DOUBLE = seed tung trung TRON Jackpot 1 (5 so chinh + so dac biet) >=2 lan
trong lich su, tim boi quet ~300 trieu seed. Xac suat ky toi: 1/3,895,584.

    python scripts/gen_j1_tickets.py --csv data/all.csv --out docs/j1_tickets.json
"""
import argparse, json, sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "configs"))
from jackpot_family import ticket, special  # noqa: E402


def _compare(seed, d, res, spc, dates):
    """Doi chieu ve J1 (5 so + DB) cua config voi ket qua thuc ky `d`."""
    if d not in res:
        return None
    pmain, psp = ticket(seed, d), special(seed, d)
    return {
        "draw_id": d, "draw_date": dates.get(d, ""),
        "actual": res[d], "actual_special": spc.get(d),
        "predicted": pmain, "predicted_special": psp,
        "main_hits": len(set(pmain) & set(res[d])),
        "special_hit": bool(psp == spc.get(d)),
    }


def _recent(seed, upto, res, spc, dates, n=12):
    ids = sorted((d for d in res if d <= upto), reverse=True)[:n]
    items = [x for x in (_compare(seed, d, res, spc, dates) for d in ids) if x]
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
    ap.add_argument("--configs", default="configs/jackpot1_configs.json")
    ap.add_argument("--out", default="docs/j1_tickets.json")
    ap.add_argument("--draw", type=int)
    ap.add_argument("--reverify", action="store_true")
    a = ap.parse_args()

    import pandas as pd
    df = pd.read_csv(a.csv)
    res = {int(r.draw_id): sorted(json.loads(r.result_json)["numbers"]) for _, r in df.iterrows()}
    spc = {int(r.draw_id): json.loads(r.result_json)["special_numbers"][0] for _, r in df.iterrows()}
    dates = {int(r.draw_id): r.draw_date for _, r in df.iterrows()}
    nd = a.draw or max(res) + 1
    prev = nd - 1
    cfg = json.load(open(a.configs, encoding="utf-8"))

    out = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "next_draw": nd, "prev_draw": prev, "prize": "Jackpot 1 — 5 so chinh + so dac biet",
           "disclaimer": ("Config tung trung tron Jackpot 1 (5 so + DB) 2 lan do quet ~300 trieu "
                          "seed (survivorship). Xac suat ky toi moi ve: 1/3,895,584. Chi giai tri."),
           "tickets": []}
    for c in cfg["j1_double_configs"]:
        s = int(c["seed"])
        if a.reverify:
            for h in c["jackpot1_hits"]:
                d = h["draw_id"]
                assert ticket(s, d) == res[d] and special(s, d) == spc[d], f"seed {s} #{d}"
        out["tickets"].append({"id": f"j1-seed-{s}", "seed": s,
                               "name": c.get("name", f"seed {s}"),
                               "numbers": ticket(s, nd), "special": special(s, nd),
                               "history": c["jackpot1_hits"],
                               "last_result": _compare(s, prev, res, spc, dates),
                               "recent": _recent(s, prev, res, spc, dates)})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK: {len(out['tickets'])} ve J1 cho ky #{nd} -> {a.out}")


if __name__ == "__main__":
    main()
