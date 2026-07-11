#!/usr/bin/env python3
"""gen_config_tickets.py — sinh bo ve ky toi cua TAT CA jackpot config cho dashboard.

Chay trong CI sau buoc cap nhat data:
    python scripts/gen_config_tickets.py --csv data/all.csv --out docs/config_tickets.json
"""
import argparse, csv, json, sys, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "configs"))
from jackpot_family import ticket, special, verify  # noqa: E402


def _load_draws(csv_path: str) -> dict[int, list[int]]:
    draws = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                draw_id = int(row["draw_id"])
                numbers = sorted(json.loads(row["result_json"])["numbers"])
                draws[draw_id] = numbers
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
    return draws


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

    cfg = json.load(open(a.configs, encoding="utf-8"))
    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "next_draw": next_draw,
        "disclaimer": ("Cac config nay tung trung >=2 jackpot trong qua khu do quet "
                       "hang chuc trieu seed (survivorship). Xac suat ky toi cua moi "
                       "ve: 1/324,632 — khong co edge. Chi giai tri."),
        "tickets": [],
    }

    for c in cfg["algorithm_configs"]:
        s = int(c["seed"])
        if a.reverify:
            got = verify(s, draws)
            want = [j["draw_id"] for j in c["jackpots"]]
            if sorted(got) != sorted(want):
                print(f"WARNING: seed {s}: got {got}, expected {want}", file=sys.stderr)
        out["tickets"].append({
            "id": f"seed-{s}", "type": "splitmix64", "seed": s,
            "numbers": ticket(s, next_draw), "special": special(s, next_draw),
            "history": c["jackpots"],
        })

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK: {len(out['tickets'])} ve cho ky #{next_draw} -> {a.out}")


if __name__ == "__main__":
    main()
