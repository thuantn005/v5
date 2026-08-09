#!/usr/bin/env python3
"""probe_report.py — xem các trang vừa dò có gì dùng được.

Ba thứ đi tìm, xếp theo mức hữu ích:

  1. SỐ NGƯỜI TRÚNG từng bậc giải — quý nhất. Đây là dữ liệu duy nhất cho
     phép ĐO thiên lệch chọn số của đám đông. Đã chứng minh trên kỳ #00814:
     tỉ lệ Giải Tư/Giải Năm cho ra "người chơi né ĐB 01 tới 27%" (p=5,5e-06).
  2. Dãy số kỳ quay — dạng `0116192933|01`.
  3. Giá trị Độc Đắc.

    python3 scripts/probe_report.py <thư_mục>
"""
from __future__ import annotations

import pathlib
import re
import sys

TAGS = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>",
                  re.IGNORECASE)
KY = re.compile(r"#\s*(\d{3,6})")
PIPE = re.compile(r"((?:\d\s*){10})\|\s*((?:\d\s*){2})")
MONEY = re.compile(r"\d[\d.,]{8,}")

# "Giải Nhất ... 1 ... 10.000.000" — tên giải, rồi số người, rồi tiền
TIERS = ("độc đắc", "nhất", "nhì", "ba", "tư", "năm", "khuyến khích")


def text_of(p: pathlib.Path) -> str:
    raw = p.read_text(encoding="utf-8", errors="replace")
    return re.sub(r"\s+", " ", TAGS.sub(" ", raw))


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "probe")
    files = sorted(root.glob("*.html"))
    if not files:
        print("Không có file nào để xem.")
        return

    print(f"\n{'FILE':<12}{'BYTES':>10}{'KỲ':>8}{'DÃY SỐ':>9}{'ĐỘC ĐẮC':>10}"
          f"{'SỐ NGƯỜI TRÚNG':>16}")
    print("-" * 66)
    for f in files:
        t = text_of(f)
        low = t.lower()
        ky = KY.search(t)
        pipe = PIPE.search(t)
        has_money = bool(MONEY.search(t))
        # đếm xem có bao nhiêu tên bậc giải xuất hiện — bảng giải đầy đủ
        n_tiers = sum(1 for x in TIERS if x in low)
        print(f"{f.name:<12}{f.stat().st_size:>10,}"
              f"{('#' + ky.group(1)) if ky else '—':>8}"
              f"{'CÓ' if pipe else '—':>9}"
              f"{'CÓ' if has_money else '—':>10}"
              f"{(str(n_tiers) + '/7 bậc') if n_tiers >= 4 else '—':>16}")

    print("-" * 66)
    best = None
    for f in files:
        t = text_of(f)
        if sum(1 for x in TIERS if x in t.lower()) >= 5:
            best = f
            break

    if best:
        print(f"\n✅ {best.name} CÓ bảng số người trúng — đây là nguồn đo đám đông.")
        t = text_of(best)
        i = t.lower().find("độc đắc")
        print("   trích:", t[max(0, i - 60):i + 400].strip()[:420])
    else:
        print("\n❌ Không trang nào có bảng số người trúng ở dạng công khai.")
        print("   → muốn đo đám đông thì phải lấy từ app trên điện thoại")
        print("     (IP dân cư đọc được vietlott.vn), không lấy từ CI được.")


if __name__ == "__main__":
    main()
