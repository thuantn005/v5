#!/usr/bin/env python3
"""publish_history_json.py — công bố TOÀN BỘ lịch sử kỳ quay cho app Android.

App cào trang chính thức, nhưng trang đó chỉ đăng KỲ GẦN NHẤT. Muốn app có đủ
lịch sử — và vá được lỗ hổng khi máy mất mạng nhiều ngày — phải có một nơi
chứa trọn bộ. `docs/data.json` chỉ giữ 50 kỳ gần nhất nên không đủ.

File này KHÔNG phải nguồn chính: app vẫn ưu tiên vietlott.vn cho kỳ mới và giá
trị Độc Đắc. Nó chỉ được gọi khi app phát hiện thiếu kỳ.

    python3 scripts/publish_history_json.py
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))
DATA_PATH = "data/all.csv"
OUT_PATH = "docs/history.json"


def main() -> None:
    draws = []
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                result = json.loads(row["result_json"])
                numbers = sorted(int(n) for n in result["numbers"])
                specials = result.get("special_numbers") or []
                if len(numbers) != 5 or not specials:
                    continue
                draws.append({
                    "id": row["draw_id"],
                    "d": row["draw_date"],
                    "n": numbers,
                    "s": int(specials[0]),
                })
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue

    draws.sort(key=lambda x: x["id"])

    payload = {
        "generated_at": datetime.now(VN_TZ).isoformat(),
        "count": len(draws),
        "first": draws[0]["id"] if draws else None,
        "last": draws[-1]["id"] if draws else None,
        "note": "Lịch sử đầy đủ để app Android vá lỗ hổng. Nguồn chính của app "
                "vẫn là vietlott.vn — file này chỉ dùng khi thiếu kỳ.",
        "draws": draws,
    }

    os.makedirs("docs", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(OUT_PATH)
    print(f"Đã ghi {OUT_PATH}: {len(draws)} kỳ "
          f"(#{payload['first']}–#{payload['last']}), {size:,} bytes")


if __name__ == "__main__":
    main()
