#!/usr/bin/env python3
"""check_sources.py — kiểm tra sức khoẻ TẤT CẢ nguồn dữ liệu.

Khác với pipeline (dừng ngay khi một nguồn thành công), script này thử ĐỘC LẬP
từng nguồn và báo cáo đầy đủ: HTTP status, có parse được dữ liệu không, số kỳ /
giá trị Độc Đắc lấy được. Dùng để biết chính xác nguồn nào sống/chết.

    python3 scripts/check_sources.py
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "configs"))

import requests  # noqa: E402

import fetch_data as F          # noqa: E402
import jackpot_check as J       # noqa: E402

TIMEOUT = 25
OK, BAD, WARN = "✅", "❌", "⚠️ "


def _probe(url: str, proxy: str | None = None) -> tuple[str, str]:
    """Trả (trạng thái, ghi chú) sau khi GET thẳng một URL."""
    try:
        proxies = {"http": proxy, "https": proxy} if proxy else None
        r = requests.get(url, timeout=TIMEOUT, headers=F._session().headers,
                         proxies=proxies)
        note = f"HTTP {r.status_code}, {len(r.content):,} bytes"
        return (OK if r.ok else BAD), note
    except requests.RequestException as e:
        return BAD, str(e)[:90]


def check_draw_sources() -> None:
    print("\n═══ NGUỒN KẾT QUẢ SỐ ═══")
    rows = []

    # NhanAZ (CSV trực tiếp)
    for label, url in (("NhanAZ raw", F.NHANAZ_CSV_URL), ("NhanAZ CDN", F.NHANAZ_CDN_URL)):
        st, note = _probe(url)
        rows.append((label, st, note))

    # Các scraper — gọi đúng hàm của pipeline để biết có parse được kỳ nào không
    for label, fn in (("Vietlott (AJAX)", F._fetch_vietlott),
                      ("lotto-8.com", F._fetch_lotto8),
                      ("xosominhngoc", F._fetch_xosominhngoc)):
        t = time.time()
        try:
            draws = fn() or []
        except Exception as e:                       # nguồn lỗi không phá script
            rows.append((label, BAD, f"lỗi: {str(e)[:70]}"))
            continue
        dt = time.time() - t
        if draws:
            ids = sorted(int(d["draw_id"]) for d in draws)
            rows.append((label, OK, f"{len(draws)} kỳ (#{ids[0]}–#{ids[-1]}), {dt:.1f}s"))
        else:
            rows.append((label, BAD, f"0 kỳ, {dt:.1f}s"))

    # Nguồn cào số ỨNG VIÊN — chưa dùng trong pipeline, dò để xác minh parser.
    for name, url in getattr(F, "CANDIDATE_DRAW_SOURCES", []):
        t = time.time()
        try:
            draws = F._fetch_vn_generic(url, name) or []
        except Exception as e:
            rows.append((f"[ứng viên] {name}", BAD, f"lỗi: {str(e)[:60]}"))
            continue
        dt = time.time() - t
        if draws:
            ids = sorted(int(d["draw_id"]) for d in draws)
            rows.append((f"[ứng viên] {name}", OK,
                         f"{len(draws)} kỳ (#{ids[0]}–#{ids[-1]}), {dt:.1f}s"))
        else:
            rows.append((f"[ứng viên] {name}", BAD, f"0 kỳ, {dt:.1f}s"))

    for label, st, note in rows:
        print(f"  {st} {label:<26} {note}")


def check_jackpot_sources() -> None:
    print("\n═══ NGUỒN GIÁ TRỊ ĐỘC ĐẮC ═══")
    proxy = J._vietlott_proxy()
    print(f"  (VIETLOTT_PROXY: {'CÓ' if proxy else 'chưa đặt'})")

    # Thử TẤT CẢ, kể cả vietlott.vn dù chuỗi thật đang bỏ qua khi không proxy.
    urls = [(u, "vietlott.vn (chính thức)") for u in J.VIETLOTT_JACKPOT_SOURCES]
    urls += [(u, u.split("/")[2]) for u in J.JACKPOT_SOURCES
             if u not in J.VIETLOTT_JACKPOT_SOURCES]
    urls += [(u, u.split("/")[2]) for u in J.EXTRA_JACKPOT_SOURCES]
    urls.append((J.GOOGLE_JACKPOT_URL, "google.com"))
    # Ứng viên chưa kiểm chứng — dò để biết cái nào đáng đưa vào pipeline.
    urls += [(u, f"[ứng viên] {u.split('/')[2]}")
             for u in getattr(J, "CANDIDATE_JACKPOT_SOURCES", [])]

    for url, label in urls:
        p = proxy if (proxy and "vietlott.vn" in url) else None
        try:
            r = requests.get(url, timeout=TIMEOUT, headers=J._HEADERS,
                             proxies=({"http": p, "https": p} if p else None))
            if not r.ok:
                print(f"  {BAD} {label:<26} HTTP {r.status_code}")
                continue
            amount, ky = J._extract_jackpot(r.text)
            if amount:
                print(f"  {OK} {label:<26} {amount:,} đ (kỳ #{ky or '?'})")
            else:
                print(f"  {WARN}{label:<26} HTTP 200 nhưng KHÔNG có số Độc Đắc")
        except requests.RequestException as e:
            print(f"  {BAD} {label:<26} {str(e)[:70]}")


def check_notify() -> None:
    print("\n═══ THÔNG BÁO (ntfy) ═══")
    topic = os.environ.get("NTFY_TOPIC", "lotto535-thuan")
    st, note = _probe(f"https://ntfy.sh/{topic}/json?poll=1")
    print(f"  {st} ntfy.sh/{topic:<14} {note}")


def main() -> None:
    print(f"KIỂM TRA NGUỒN — {time.strftime('%H:%M %d/%m/%Y')} (giờ máy)")
    check_draw_sources()
    check_jackpot_sources()
    check_notify()
    print("\nXong. Nguồn ❌ không nhất thiết là lỗi hệ thống — pipeline chỉ cần "
          "MỘT nguồn sống ở mỗi nhóm.")


if __name__ == "__main__":
    main()
