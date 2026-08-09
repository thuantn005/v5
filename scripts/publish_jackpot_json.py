#!/usr/bin/env python3
"""publish_jackpot_json.py — công bố docs/jackpot.json cho app Android.

App Android cào thẳng vietlott.vn (IP điện thoại là IP dân cư nên WAF cho qua).
File này là lớp DỰ PHÒNG CUỐI: nếu điện thoại đang ở mạng bị chặn, hoặc trang
chính thức đổi cấu trúc HTML, app vẫn đọc được pot + trạng thái chia giải mà
pipeline đã kiểm định chéo nhiều nguồn.

Đọc từ state/ (đã có sẵn sau mỗi lần chạy pipeline), không gọi mạng.

    python3 scripts/publish_jackpot_json.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))
STATE_PATH = "state/jackpot_state.json"
LOG_PATH = "state/ensemble_log.jsonl"
OUT_PATH = "docs/jackpot.json"


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _latest_log_entry() -> dict:
    """Bản ghi mới nhất có jackpot_vnd hợp lệ trong ensemble_log."""
    if not os.path.exists(LOG_PATH):
        return {}
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            lines = [l for l in f.read().strip().split("\n") if l.strip()]
    except Exception:
        return {}
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("jackpot_vnd"):
            return e
    return {}


def main() -> None:
    state = _load_json(STATE_PATH, {})
    entry = _latest_log_entry()

    jackpot = entry.get("jackpot_vnd") or state.get("prev_jackpot") or 0
    payload = {
        "generated_at": datetime.now(VN_TZ).isoformat(),
        "jackpot_vnd": int(jackpot) if jackpot else 0,
        "draw_id": entry.get("draw_id") or entry.get("target_draw_id"),
        "jackpot_source": entry.get("jackpot_source"),
        # Trạng thái chia giải — app dùng để hiển thị ngay cả khi chưa cào được.
        "share_pending": bool(state.get("pending")),
        "share_date": state.get("share_date"),
        "peak_jackpot": int(state.get("peak_jackpot") or 0),
        "trigger_draw_id": state.get("trigger_draw_id"),
        "threshold_vnd": 12_000_000_000,
        "note": "Dự phòng cho app Android. Nguồn gốc vẫn là vietlott.vn — "
                "app ưu tiên cào thẳng trang chính thức trước khi dùng file này.",
    }

    os.makedirs("docs", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Đã ghi {OUT_PATH}: {payload['jackpot_vnd']:,} đ "
          f"(kỳ #{payload['draw_id'] or '?'}, "
          f"chia giải: {payload['share_date'] or 'chưa có'})")


if __name__ == "__main__":
    main()
