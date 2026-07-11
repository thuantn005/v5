#!/usr/bin/env python3
"""notify_config_wins.py — báo ntfy khi VÉ CỦA CONFIG trúng giải.

Sau mỗi kỳ quay, sinh vé của cả 12 config (8 Jackpot-2 + 4 Jackpot-1, đặt tên
nhà toán học Ấn Độ) cho ĐÚNG kỳ vừa quay và đối chiếu với kết quả thực. Nếu một
config trúng giải (>=4/5 số chính) thì đẩy thông báo ntfy — mỗi lần trúng chỉ
báo đúng 1 lần nhờ state/config_wins_notified.json.

    python scripts/notify_config_wins.py --csv data/all.csv --topic lotto535-thuan

Bậc giải (Lotto 5/35):
  5 số chính + số đặc biệt → 🏆 JACKPOT 1   (1/3.895.584)
  5 số chính               → 🥈 JACKPOT 2   (1/324.632)
  4 số chính               → 🎉 trúng 4/5   (giải phụ)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "configs"))
from jackpot_family import ticket, special  # noqa: E402

import notify_ntfy

STATE_PATH = "state/config_wins_notified.json"
WINS_PATH = "docs/jackpot_wins.json"   # "bảng vàng" jackpot để ghim đầu dashboard
NOTIFY_MIN_MAIN_HITS = 4      # báo khi trúng >= 4/5 số chính
JACKPOT_MAIN_HITS = 5         # trúng jackpot = đủ 5/5 số chính (ghim đầu trang)
LOOKBACK_DRAWS = 10           # quét lại 10 kỳ gần nhất phòng khi bỏ lỡ một lần chạy

J2_CONFIGS = "configs/jackpot_configs.json"
J1_CONFIGS = "configs/jackpot1_configs.json"


def _load_draws(csv_path: str) -> dict[int, dict]:
    draws: dict[int, dict] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                did = int(row["draw_id"])
                r = json.loads(row["result_json"])
                draws[did] = {
                    "numbers": sorted(r["numbers"]),
                    "special": r["special_numbers"][0] if r.get("special_numbers") else None,
                    "draw_date": row.get("draw_date", ""),
                }
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
    return draws


def _load_configs() -> list[dict]:
    """Danh sách config thống nhất: {name, seed, collection}."""
    out: list[dict] = []
    for path, key, coll in ((J2_CONFIGS, "algorithm_configs", "J2"),
                            (J1_CONFIGS, "j1_double_configs", "J1")):
        if not os.path.exists(path):
            continue
        d = json.load(open(path, encoding="utf-8"))
        for c in d.get(key, []):
            out.append({"name": c.get("name", f"seed {c['seed']}"),
                        "seed": int(c["seed"]), "collection": coll})
    return out


def _load_state() -> set[str]:
    if os.path.exists(STATE_PATH):
        try:
            return set(json.load(open(STATE_PATH, encoding="utf-8")).get("notified", []))
        except Exception:
            pass
    return set()


def _save_state(notified: set[str]) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    json.dump({"notified": sorted(notified)}, open(STATE_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def _record_jackpots(jackpot_wins: list[dict]) -> None:
    """Ghi các cú trúng JACKPOT (5/5) vào 'bảng vàng' docs/jackpot_wins.json để
    dashboard ghim banner đầu trang. Dedup theo (draw_id, seed); giữ lịch sử."""
    import datetime
    existing = {"wins": []}
    if os.path.exists(WINS_PATH):
        try:
            existing = json.load(open(WINS_PATH, encoding="utf-8"))
        except Exception:
            existing = {"wins": []}
    seen = {(w.get("draw_id"), w.get("seed")) for w in existing.get("wins", [])}
    added = False
    for w in jackpot_wins:
        if (w["draw_id"], w["seed"]) in seen:
            continue
        existing.setdefault("wins", []).append({
            "draw_id": w["draw_id"], "draw_date": w["draw_date"],
            "name": w["name"], "seed": w["seed"], "collection": w["collection"],
            "tier": "jackpot1" if w["special_hit"] else "jackpot2",
            "prize_label": w["prize_label"],
            "numbers": w["predicted"], "special": w["predicted_special"],
            "special_hit": w["special_hit"],
            "actual": w["actual"], "actual_special": w["actual_special"],
            "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        })
        seen.add((w["draw_id"], w["seed"]))
        added = True
    if added:
        # Mới nhất lên đầu.
        existing["wins"].sort(key=lambda x: (x["draw_id"], x["seed"]), reverse=True)
        os.makedirs(os.path.dirname(WINS_PATH), exist_ok=True)
        json.dump(existing, open(WINS_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"[config-win] ghi {sum(1 for _ in jackpot_wins)} jackpot vào {WINS_PATH}")


def _prize(main_hits: int, special_hit: bool) -> tuple[str, str, str] | None:
    """(nhãn giải, emoji, tags) hoặc None nếu không trúng đủ bậc để báo."""
    if main_hits == 5 and special_hit:
        return "🏆 JACKPOT 1 (5 số chính + ĐB)", "🏆", "trophy,tada,moneybag"
    if main_hits == 5:
        return "🥈 JACKPOT 2 (5/5 số chính)", "🥈", "second_place_medal,moneybag"
    if main_hits == 4:
        return "🎉 Trúng 4/5 số chính", "🎉", "tada"
    return None


def _fmt(nums) -> str:
    return " ".join(f"{n:02d}" for n in nums)


def check(csv_path: str, topic: str, dry_run: bool = False) -> list[dict]:
    draws = _load_draws(csv_path)
    if not draws:
        print("Không có dữ liệu kỳ quay.", file=sys.stderr)
        return []
    configs = _load_configs()
    notified = _load_state()

    latest = max(draws)
    targets = [d for d in sorted(draws) if d > latest - LOOKBACK_DRAWS]

    wins: list[dict] = []
    for did in targets:
        actual = draws[did]
        for cfg in configs:
            key = f"{did}:{cfg['seed']}"
            if key in notified:
                continue
            pmain = ticket(cfg["seed"], did)
            psp = special(cfg["seed"], did)
            main_hits = len(set(pmain) & set(actual["numbers"]))
            special_hit = actual["special"] is not None and psp == actual["special"]
            if main_hits < NOTIFY_MIN_MAIN_HITS:
                continue
            prize = _prize(main_hits, special_hit)
            if prize is None:
                continue
            wins.append({
                "key": key, "draw_id": did, "draw_date": actual["draw_date"],
                "name": cfg["name"], "seed": cfg["seed"], "collection": cfg["collection"],
                "main_hits": main_hits, "special_hit": special_hit,
                "predicted": pmain, "predicted_special": psp,
                "actual": actual["numbers"], "actual_special": actual["special"],
                "prize_label": prize[0], "prize_emoji": prize[1], "prize_tags": prize[2],
            })

    if not wins:
        print("Không có config nào trúng giải (>=4/5) ở các kỳ chưa báo.")
        return []

    # Gom theo kỳ, một thông báo mỗi kỳ (nêu bậc giải cao nhất ở tiêu đề).
    by_draw: dict[int, list[dict]] = {}
    for w in wins:
        by_draw.setdefault(w["draw_id"], []).append(w)

    for did, items in sorted(by_draw.items()):
        items.sort(key=lambda w: (-w["main_hits"], not w["special_hit"]))
        top = items[0]
        actual = items[0]
        lines = []
        for w in items:
            hit_set = set(w["actual"])
            marked = " ".join(
                (f"[{n:02d}]" if n in hit_set else f"{n:02d}") for n in w["predicted"])
            sp = f" | ĐB {w['predicted_special']:02d}" + ("✓" if w["special_hit"] else "")
            lines.append(f"• {w['name']} (seed {w['seed']}, {w['collection']}): "
                         f"{w['prize_emoji']} {w['main_hits']}/5 — {marked}{sp}")
        message = (
            f"Kỳ #{did} ({actual['draw_date']})\n"
            f"Kết quả: {_fmt(actual['actual'])} + ĐB {actual['actual_special']:02d}\n\n"
            + "\n".join(lines) +
            "\n\nLưu ý trung thực: đây là trùng khớp may mắn, KHÔNG phải bằng chứng "
            "config dự đoán được — xác suất mỗi vé vẫn như mọi vé khác. Hãy kiểm tra "
            "lại vé thật và chơi có trách nhiệm."
        )
        title = f"{top['prize_emoji']} Config TRÚNG! {top['prize_label']} — {top['name']}"
        priority = "max" if top["main_hits"] == 5 else "high"
        print(f"[config-win] kỳ #{did}: {len(items)} config trúng → ntfy")
        print(title)
        print(message)
        if not dry_run:
            try:
                notify_ntfy.send(topic, title=title, message=message,
                                 priority=priority, tags=top["prize_tags"])
            except Exception as e:  # noqa: BLE001 — thông báo là best-effort
                print(f"WARNING: gửi ntfy thất bại (vẫn đánh dấu đã báo): {e}", file=sys.stderr)

    # Ghim jackpot (5/5) lên đầu dashboard qua bảng vàng.
    jackpots = [w for w in wins if w["main_hits"] >= JACKPOT_MAIN_HITS]
    if jackpots and not dry_run:
        _record_jackpots(jackpots)

    # Đánh dấu đã báo (kể cả khi ntfy lỗi, để không spam lại mỗi lần chạy).
    for w in wins:
        notified.add(w["key"])
    if not dry_run:
        _save_state(notified)
    return wins


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/all.csv")
    ap.add_argument("--topic", default=os.environ.get("NTFY_TOPIC", "lotto535-thuan"))
    ap.add_argument("--dry-run", action="store_true", help="in ra, không gửi ntfy / không lưu state")
    a = ap.parse_args()
    check(a.csv, a.topic, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
