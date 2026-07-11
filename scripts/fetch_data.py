"""
fetch_data.py
-------------
Tải toàn bộ dữ liệu lịch sử Lotto 5/35 từ dataset chính thức:
  https://github.com/NhanAZ-Data/vietlott-data-research

CSV nguồn có cùng schema với data/all.csv → ghi đè thẳng, không cần parse.
Nếu tải thất bại → giữ nguyên file cũ, pipeline vẫn chạy được.
"""

from __future__ import annotations

import io
import sys
import os
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DATA_PATH = "data/all.csv"
TIMEOUT = 30

# URL raw của CSV từ NhanAZ-Data (nguồn chính thức, luôn được cập nhật)
NHANAZ_CSV_URL = (
    "https://raw.githubusercontent.com/"
    "NhanAZ-Data/vietlott-data-research/main/datasets/draws/lotto535/all.csv"
)

# CDN fallback (jsDelivr cache GitHub raw)
NHANAZ_CDN_URL = (
    "https://cdn.jsdelivr.net/gh/"
    "NhanAZ-Data/vietlott-data-research@main/datasets/draws/lotto535/all.csv"
)


def _make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent": "lotto535-fetch/1.0"})
    return s


def _count_rows(text: str) -> int:
    """Đếm số dòng dữ liệu (không tính header)."""
    return max(0, text.strip().count("\n"))


def _fetch_csv() -> str | None:
    """Tải CSV từ NhanAZ-Data, thử CDN nếu URL chính lỗi. Trả về nội dung CSV hoặc None."""
    s = _make_session()
    for label, url in [("NhanAZ-Data (raw)", NHANAZ_CSV_URL), ("NhanAZ-Data (CDN)", NHANAZ_CDN_URL)]:
        try:
            r = s.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            text = r.text
            # Kiểm tra tối thiểu: phải có header và ít nhất 100 dòng
            if "draw_id" in text and _count_rows(text) >= 100:
                print(f"{label}: OK — {_count_rows(text)} kỳ quay")
                return text
            else:
                print(f"WARNING: {label}: nội dung không hợp lệ ({_count_rows(text)} dòng)", file=sys.stderr)
        except requests.RequestException as e:
            print(f"WARNING: {label} thất bại: {e}", file=sys.stderr)
    return None


def main():
    os.makedirs(os.path.dirname(DATA_PATH) if os.path.dirname(DATA_PATH) else ".", exist_ok=True)

    csv_text = _fetch_csv()

    if csv_text is None:
        if os.path.exists(DATA_PATH):
            print("WARNING: tất cả nguồn lỗi — giữ nguyên data/all.csv. Pipeline vẫn chạy trên dữ liệu cũ.", file=sys.stderr)
        else:
            print("ERROR: không tải được dữ liệu và data/all.csv không tồn tại.", file=sys.stderr)
            sys.exit(1)
        return

    # Ghi đè data/all.csv bằng dữ liệu mới nhất từ NhanAZ
    with open(DATA_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(csv_text)

    print(f"data/all.csv đã cập nhật: {_count_rows(csv_text)} kỳ quay (tính đến {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")


if __name__ == "__main__":
    main()
