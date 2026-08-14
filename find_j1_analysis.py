#!/usr/bin/env python3
"""find_j1_analysis.py — 3 cách tìm seed mới trúng 3-4 lần J1 (5 số + ĐB)"""
import json
import csv
import sys
from math import comb
from collections import defaultdict
from time import time

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

def verify_seed(seed: int, draws: dict) -> list:
    """Tìm tất cả draw_id mà seed này khớp"""
    hits = []
    for draw_id in draws:
        if ticket(seed, draw_id) == draws[draw_id]["numbers"] and \
           special(seed, draw_id) == draws[draw_id]["special"]:
            hits.append(draw_id)
    return hits

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

print(f"✅ Tải {len(draws)} kỳ quay từ kỳ #{min(draws.keys())} đến #{max(draws.keys())}")
draws_list = sorted(draws.keys())

# ============================================================================ CÁCH 1: KIỂM CHỨNG 4 SEED HIỆN TẠI
print("\n" + "="*80)
print("CÁCH 1️⃣: KIỂM CHỨNG 4 SEED HIỆN TẠI + MỞ RỘNG")
print("="*80)

existing_seeds = {
    "Ramanujan": 10015838883,
    "Bhaskara I": 10036936239,
    "Narayana Pandita": 10168595334,
    "Shakuntala Devi": 10183485194,
}

existing_results = []
for name, seed in existing_seeds.items():
    hits = verify_seed(seed, draws)
    existing_results.append({
        "name": name,
        "seed": seed,
        "hits": len(hits),
        "draw_ids": hits
    })
    print(f"\n✓ {name} (seed {seed})")
    print(f"  Trúng: {len(hits)} lần")
    for did in hits:
        d = draws[did]
        print(f"    • Kỳ #{did} ({d['date']}): {d['numbers']} + ĐB {d['special']}")

# ============================================================================ CÁCH 2: QUÉT NHANH TOP 10M SEED
print("\n" + "="*80)
print("CÁCH 2️⃣: QUÉT NHANH TOP 10 TRIỆU SEED")
print("="*80)

print("\n🔍 Quét seed từ 10 tỷ → 10.01 tỷ (10 triệu seed)...")
t0 = time()
fast_found = []

for i, seed in enumerate(range(10_000_000_000, 10_010_000_000)):
    if i % 1_000_000 == 0 and i > 0:
        elapsed = time() - t0
        print(f"   [{i:,}/10,000,000] - {elapsed:.1f}s, tìm được {len(fast_found)} seed...")
    
    hits = verify_seed(seed, draws)
    if len(hits) >= 3:
        fast_found.append({
            "seed": seed,
            "hits": len(hits),
            "draw_ids": hits
        })

elapsed = time() - t0
print(f"\n✅ Quét xong trong {elapsed:.1f}s")
print(f"📊 Tìm được {len(fast_found)} seed trúng ≥3 lần")

for item in sorted(fast_found, key=lambda x: -x["hits"])[:5]:
    print(f"\n   Seed {item['seed']}: trúng {item['hits']} lần ở kỳ {item['draw_ids']}")

# ============================================================================ CÁCH 3: QUÉT TỐI ƯU 300M SEED
print("\n" + "="*80)
print("CÁCH 3️⃣: QUÉT TỐI ƯU TOÀN BỘ 300 TRIỆU SEED (CHỈ TIÊU ĐỀ)")
print("="*80)

print("""
⚠️  Quét đầy đủ 300M seed sẽ mất ~2-4 giờ tuỳ máy.

Thay vào đó, dùng kỹ thuật "tối ưu hóa ngược (reverse search)":
  1. Với mỗi tổ hợp (5 số + ĐB) xuất hiện 2+ lần trong lịch sử
  2. Tìm seed S sao cho: ticket(S, draw_id) = tổ hợp đó
  3. Giải phương trình: _mix(S*M1 + draw_id*M2) ≡ index (mod 324632)

Điều này giảm từ 300M × 814 kỳ = 244 tỷ phép toán xuống ~10.000 tổ hợp.
""")

# Tìm tổ hợp xuất hiện 2+ lần
combo_hits = defaultdict(list)
for draw_id in draws_list:
    nums = tuple(draws[draw_id]["numbers"])
    spec = draws[draw_id]["special"]
    key = (nums, spec)
    combo_hits[key].append(draw_id)

multi_combos = {k: v for k, v in combo_hits.items() if len(v) > 1}
print(f"\n📊 Số tổ hợp (5 số + ĐB) xuất hiện 2+ lần: {len(multi_combos)}")

for combo, draw_ids in sorted(multi_combos.items(), key=lambda x: -len(x[1]))[:5]:
    print(f"   {combo[0]} + ĐB {combo[1]}: {len(draw_ids)} lần ở kỳ {draw_ids}")

print("\n💡 Để tìm seed của các tổ hợp này, cần giải REVERSE:")
print("   Cho: ticket(S, d1) == ticket(S, d2) == tổ hợp X")
print("   Tìm: S sao cho điều kiện trên đúng")
print("\n⏱️  Quá trình này có thể mất 30-60 phút tùy thuộc độ phức tạp.")

# ============================================================================ OUTPUT

all_results = {
    "timestamp": time(),
    "total_draws": len(draws),
    "draw_range": f"#{min(draws_list)} - #{max(draws_list)}",
    "results": {
        "method1_verify_existing": existing_results,
        "method2_fast_scan_10m": fast_found,
        "method3_optimized_300m": {
            "status": "Pending - Requires reverse search solver",
            "multi_hit_combos_count": len(multi_combos),
            "sample_combos": [
                {
                    "combo": list(combo[0]),
                    "special": combo[1],
                    "occurrences": len(draw_ids),
                    "draw_ids": draw_ids
                }
                for combo, draw_ids in sorted(multi_combos.items(), key=lambda x: -len(x[1]))[:10]
            ]
        }
    }
}

with open("docs/j1_findings.json", "w", encoding="utf-8") as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)

print("\n✅ Lưu kết quả vào docs/j1_findings.json")

# ============================================================================ SUMMARY
print("\n" + "="*80)
print("📋 TÓM TẮT KẾT QUẢ")
print("="*80)
print(f"\n✓ CÁCH 1 (Kiểm chứng hiện tại):")
for r in existing_results:
    print(f"  • {r['name']}: {r['hits']} lần")

print(f"\n✓ CÁCH 2 (Quét nhanh 10M): Tìm được {len(fast_found)} seed mới")
if fast_found:
    top = sorted(fast_found, key=lambda x: -x["hits"])[0]
    print(f"  • Top: Seed {top['seed']} trúng {top['hits']} lần")

print(f"\n✓ CÁCH 3 (Tối ưu 300M): {len(multi_combos)} tổ hợp khả thi (cần giải reverse)")

print("\n🎯 Kết luận:")
print(f"   - 4 seed hiện tại: {sum(r['hits'] for r in existing_results)} lần trúng tổng cộng")
print(f"   - {len(fast_found)} seed mới từ top 10M")
print(f"   - Cần giải reverse để tìm seed từ {len(multi_combos)} tổ hợp 2+ lần")
print("\n" + "="*80 + "\n")
