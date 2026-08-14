#!/usr/bin/env python3
"""run_j1_search.py — Tìm seed mới trúng 3-4 lần J1 từ CSV"""
import json
import csv
from math import comb
from collections import defaultdict
from pathlib import Path
import time

# ============================================================================ CONFIG
M1, M2 = 0x9E3779B97F4A7C15, 0xD1B54A32D192ED03
M3, M4 = 0xBF58476D1CE4E5B9, 0x94D049BB133111EB
MASK = (1 << 64) - 1
C = comb(35, 5)  # 324,632

# ============================================================================ FUNC

def _mix(x: int) -> int:
    z = x & MASK
    z ^= z >> 30; z = (z * M3) & MASK
    z ^= z >> 27; z = (z * M4) & MASK
    return z ^ (z >> 31)

def _unrank(r: int) -> list:
    out, rem = [], r
    for k in range(5, 0, -1):
        x = k - 1
        while comb(x + 1, k) <= rem:
            x += 1
        out.append(x + 1); rem -= comb(x, k)
    return sorted(out)

def ticket(seed: int, draw_id: int) -> list:
    return _unrank(_mix(seed * M1 + draw_id * M2) % C)

def special(seed: int, draw_id: int) -> int:
    return _mix(_mix(seed * M1 + draw_id * M2)) % 12 + 1

# ============================================================================ LOAD
print("📥 Load dữ liệu CSV...")
draws = {}
with open("data/all.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        try:
            did = int(row["draw_id"])
            r = json.loads(row["result_json"])
            draws[did] = {
                "numbers": sorted(r["numbers"]),
                "special": r["special_numbers"][0] if r.get("special_numbers") else None,
                "date": row.get("draw_date", "")
            }
        except:
            continue

print(f"✅ Tải {len(draws)} kỳ quay")
draws_list = sorted(draws.keys())

# ============================================================================ CÁCH 1: KIM CHÍ HỆ 4 SEED HIỆN TẠI

print("\n" + "="*80)
print("CÁCH 1️⃣: KIỂM CHỨNG 4 SEED HIỆN TẠI")
print("="*80)

existing_seeds = {
    "Ramanujan": 10015838883,
    "Bhaskara I": 10036936239,
    "Narayana Pandita": 10168595334,
    "Shakuntala Devi": 10183485194,
}

for name, seed in existing_seeds.items():
    hits = []
    for draw_id in draws_list:
        if ticket(seed, draw_id) == draws[draw_id]["numbers"] and \
           special(seed, draw_id) == draws[draw_id]["special"]:
            hits.append(draw_id)
    
    print(f"\n✓ {name} (seed {seed}): {len(hits)} lần")
    for did in hits:
        d = draws[did]
        print(f"   Kỳ #{did} ({d['date']}): {d['numbers']} + ĐB {d['special']}")

# ============================================================================ CÁCH 2: QUÉT TOP 1M SEED (NHANH)

print("\n" + "="*80)
print("CÁCH 2️⃣: QUÉT NHANH TOP 1 TRIỆU SEED")
print("="*80)

print("\n🔍 Quét seed từ 10 tỷ → 10.001 tỷ...")
t0 = time.time()
found = []

for i, seed in enumerate(range(10_000_000_000, 10_001_000_000)):
    if i % 100_000 == 0 and i > 0:
        elapsed = time.time() - t0
        rate = i / elapsed
        print(f"   [{i:,}/1,000,000] - {elapsed:.1f}s ({rate:,.0f} seed/s), tìm {len(found)} seed")
    
    hits = []
    for draw_id in draws_list:
        if ticket(seed, draw_id) == draws[draw_id]["numbers"] and \
           special(seed, draw_id) == draws[draw_id]["special"]:
            hits.append(draw_id)
    
    if len(hits) >= 3:
        found.append({
            "seed": seed,
            "hits": len(hits),
            "draw_ids": hits
        })
        print(f"\n   🎯 Seed {seed}: trúng {len(hits)} lần ở kỳ {hits}")

elapsed = time.time() - t0
print(f"\n✅ Quét xong trong {elapsed:.1f}s")
print(f"📊 Tìm được {len(found)} seed trúng ≥3 lần")

if found:
    print("\n📋 Top Results:")
    for item in sorted(found, key=lambda x: -x["hits"])[:10]:
        print(f"\n   Seed {item['seed']}: {item['hits']} lần")
        for did in item['draw_ids']:
            d = draws[did]
            print(f"      • Kỳ #{did} ({d['date']}): {d['numbers']} + ĐB {d['special']}")

# ============================================================================ OUTPUT

output = {
    "timestamp": time.time(),
    "total_draws": len(draws),
    "scan_range": "10,000,000,000 - 10,001,000,000",
    "seeds_found": len(found),
    "results": sorted(found, key=lambda x: -x["hits"])
}

Path("docs").mkdir(exist_ok=True)
with open("docs/new_j1_seeds_found.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n\n✅ Kết quả lưu vào docs/new_j1_seeds_found.json")
print(f"\n🎯 Tóm tắt: {len(found)} seed mới trúng 3+ lần J1 được tìm thấy!")
