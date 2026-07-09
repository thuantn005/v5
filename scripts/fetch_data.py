"""
fetch_data.py
-------------
Downloads the latest Lotto 5/35 historical draw CSV from the public
NhanAZ-Data/vietlott-data-research dataset repo and saves it locally.

Tries multiple sources in order (GitHub raw, then jsdelivr/statically CDN
mirrors of the same repo -- different infrastructure, so if one is down
or rate-limited the other often still works). If EVERY source fails, this
does NOT overwrite the existing data/all.csv -- the pipeline just keeps
running on the last known-good data rather than crashing or wiping it out.

IMPORTANT TIMING NOTE: NhanAZ-Data's dataset typically isn't updated until
roughly 2-4h after a draw happens (observed from its own fetched_at
timestamps). That's too slow if a result is needed within ~1h of the draw.
So AFTER the primary fetch (whether it succeeded or not), this always also
runs fallback_scraper.py, which scrapes minhchinh.com's live results page
directly -- that page updates much faster, usually within minutes of a
draw. fallback_scraper.py only APPENDS genuinely new draws it finds (never
overwrites), so running it every time is safe and just means "use whichever
source has the fastest fresh result."

If you have your own scraper/data source, add it to SOURCE_URLS -- 
everything downstream only needs a CSV with a `draw_id` and `result_json`
column in the same shape as this dataset.
"""

import os
import sys
import requests

_REPO_PATH = "NhanAZ-Data/vietlott-data-research/main/datasets/draws/lotto535/all.csv"
SOURCE_URLS = [
    f"https://raw.githubusercontent.com/{_REPO_PATH}",
    f"https://cdn.jsdelivr.net/gh/{_REPO_PATH.replace('/main/', '@main/')}",
    f"https://cdn.statically.io/gh/{_REPO_PATH}",
]
OUTPUT_PATH = "data/all.csv"


def _try_fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        content = resp.text
        if not content.splitlines() or "draw_id" not in content.splitlines()[0]:
            print(f"WARNING: {url} did not return the expected CSV header", file=sys.stderr)
            return None
        return content
    except requests.RequestException as e:
        print(f"WARNING: fetch failed for {url}: {e}", file=sys.stderr)
        return None


def _run_fast_fallback_patch():
    """Always try the fast independent scraper too, so we use whichever
    source (slow-but-complete primary, or fast-but-recent-only fallback)
    actually has the newest result first. Safe to call unconditionally --
    it only appends draws not already present."""
    try:
        import fallback_scraper
        appended = fallback_scraper.scrape_and_append()
        if appended:
            print(f"Fast fallback scraper (minhchinh.com) patched in {appended} "
                  f"newer draw(s) not yet in the primary dataset.")
    except Exception as e:
        print(f"WARNING: fast fallback scraper check failed (non-fatal): {e}", file=sys.stderr)


def main():
    for url in SOURCE_URLS:
        content = _try_fetch(url)
        if content is not None:
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                f.write(content)
            line_count = content.count("\n")
            print(f"Saved {OUTPUT_PATH} ({line_count} lines) from {url}")
            _run_fast_fallback_patch()
            return

    # Every primary mirror failed -- do NOT wipe out existing data.
    if os.path.exists(OUTPUT_PATH):
        print(f"ERROR: all {len(SOURCE_URLS)} primary data sources failed. "
              f"Trying independent fallback scraper to patch in new draws...",
              file=sys.stderr)
        _run_fast_fallback_patch()
    else:
        print(f"ERROR: all {len(SOURCE_URLS)} data sources failed and no existing "
              f"{OUTPUT_PATH} to fall back on. Cannot proceed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
