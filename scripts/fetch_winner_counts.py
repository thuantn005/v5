#!/usr/bin/env python3
"""fetch_winner_counts.py — cào SỐ NGƯỜI TRÚNG mỗi bậc giải từ minhchinh.com.

Vì sao dữ liệu này quý: nó là thứ DUY NHẤT đo được thiên lệch chọn số của đám
đông. Kết quả quay là ngẫu nhiên và không học được gì (đã chứng minh: 19 model,
684.000 vé-kỳ). Nhưng CÁCH NGƯỜI CHƠI CHỌN thì không ngẫu nhiên, và số người
trúng mỗi bậc để lộ điều đó.

Ví dụ đã đo (kỳ #00814):
    Giải Tư (3 số + ĐB) = 148   ·   Giải Năm (3 số, không ĐB) = 2.271
    Hai bậc đòi hỏi y hệt nhau về số chính → tỉ lệ đo thẳng % người chọn ĐB 01:
        148/(148+2271) = 6,12%   (đều phải là 8,33%)  →  né 27%, p = 5,5e-06

Nguồn: minhchinh.com — bên thứ ba, KHÔNG sau WAF của vietlott, nên đọc được từ
GitHub Actions (đã dò: vietlott.vn và vietlott-sms.vn đều trả 403 với IP máy
chủ; minhchinh trả 200 kèm đầy đủ bảng).

    python3 scripts/fetch_winner_counts.py            # cào, gộp vào state
    python3 scripts/fetch_winner_counts.py --show      # chỉ in bảng đã lưu
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STATE_PATH = "state/winner_counts.jsonl"
LIVE_URL = "https://www.minhchinh.com/truc-tiep-xo-so-tu-chon-lotto-535.html"
RESULT_URL = "https://www.minhchinh.com/xo-so-dien-toan-lotto-535.html"

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept-Language": "vi-VN,vi;q=0.9",
}

# Bậc giải theo thứ tự xuất hiện trong bảng; kèm điều kiện trúng để phân tích.
TIERS = [
    ("jackpot", "độc đắc",  5, True),
    ("first",   "nhất",     5, False),
    ("second",  "nhì",      4, True),
    ("third",   "ba",       4, False),
    ("fourth",  "tư",       3, True),
    ("fifth",   "năm",      3, False),
    ("kk",      "kk",       None, None),
]

_TAGS = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", re.I)
_KY = re.compile(r"#\s*(\d{3,6})")


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub(" ", html))


def _parse(html: str) -> dict | None:
    """Bóc {draw_id, counts:{tier:so_nguoi}} từ HTML bảng kết quả."""
    t = _text(html)
    ky = _KY.search(t)
    if not ky:
        return None
    draw_id = ky.group(1).rjust(5, "0")

    low = t.lower()
    counts = {}
    # Với mỗi bậc: tìm cụm "giải <tên> <số người> <giá trị>". Số người là số
    # nguyên đầu tiên sau tên bậc; giá trị là số có dấu phân cách ngay sau đó.
    for key, name, _, _ in TIERS:
        # Tiền tố "giải" là TUỲ CHỌN: hàng Độc Đắc trong bảng ghi "Độc đắc"
        # (đứng sau "Giá trị"), không có chữ "giải" như các bậc còn lại.
        m = re.search(r"(?:gi[ải]+\s+)?" + re.escape(name) +
                      r"\b[^\d]{0,20}([\d.,]+)\s+([\d.,]{4,})", low)
        if not m:
            continue
        n = int(re.sub(r"[^\d]", "", m.group(1)) or -1)
        if n >= 0:
            counts[key] = n
    return {"draw_id": draw_id, "counts": counts} if counts else None


def _fetch(url: str) -> str | None:
    import requests
    try:
        r = requests.get(url, headers=_HEADERS, timeout=30)
        return r.text if r.ok else None
    except Exception as e:
        print(f"  lỗi {url.split('/')[2]}: {e}")
        return None


def _load_all() -> dict[str, dict]:
    out = {}
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    out[e["draw_id"]] = e
                except Exception:
                    continue
    return out


def _save_all(rows: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        for k in sorted(rows):
            f.write(json.dumps(rows[k], ensure_ascii=False) + "\n")


def analyze(rows: dict[str, dict]) -> None:
    """Tổng hợp các kỳ đã có để đo thiên lệch chọn SỐ ĐẶC BIỆT.

    Giải Tư (3 số + ĐB) và Giải Năm (3 số, không ĐB) đòi hỏi y hệt về số chính.
    Gộp mọi kỳ: tổng Tư / (tổng Tư + tổng Năm) = tỉ lệ người chơi chọn ĐÚNG số
    đặc biệt của kỳ đó. So với 1/12 = 8,33%.
    """
    from math import sqrt, erfc
    a = sum(e["counts"].get("fourth", 0) for e in rows.values())
    b = sum(e["counts"].get("fifth", 0) for e in rows.values())
    if a + b == 0:
        print("Chưa đủ dữ liệu để phân tích.")
        return
    frac = a / (a + b)
    unif = 1 / 12
    se = sqrt(frac * (1 - frac) / (a + b))
    z = (frac - unif) / se if se else 0.0
    pv = erfc(abs(z) / sqrt(2)) if se else 1.0
    print(f"\n═══ THIÊN LỆCH SỐ ĐẶC BIỆT ({len(rows)} kỳ) ═══")
    print(f"  Giải Tư (3+ĐB) : {a:,}")
    print(f"  Giải Năm (3)   : {b:,}")
    print(f"  → người chơi chọn TRÚNG số ĐB của kỳ: {frac*100:.2f}%  (đều = 8,33%)")
    print(f"    z = {z:.2f} · p = {pv:.2e}")
    if pv < 0.05:
        d = (frac - unif) / unif * 100
        print(f"  Có ý nghĩa: đám đông {'né' if d < 0 else 'dồn'} số ĐB đúng "
              f"{abs(d):.0f}% so với ngẫu nhiên.")
    else:
        print("  Chưa đủ mạnh để kết luận — cần thêm kỳ.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="chỉ in dữ liệu đã lưu")
    a = ap.parse_args()

    rows = _load_all()

    if not a.show:
        for url in (LIVE_URL, RESULT_URL):
            html = _fetch(url)
            if not html:
                continue
            rec = _parse(html)
            if rec:
                rows[rec["draw_id"]] = {**rec, "source": url.split("/")[2]}
                print(f"✅ cào được kỳ #{rec['draw_id']}: {rec['counts']}")
                break
        else:
            print("❌ không cào được từ nguồn nào.")
        _save_all(rows)

    print(f"\nĐã lưu {len(rows)} kỳ tại {STATE_PATH}")
    for k in sorted(rows)[-5:]:
        c = rows[k]["counts"]
        print(f"  #{k}: " + "  ".join(f"{t}={c.get(t,'?')}"
              for t, *_ in TIERS if t in c))
    analyze(rows)


if __name__ == "__main__":
    main()
