#!/usr/bin/env python3
"""
scan_j1_triple.py — quét seed tìm J1 >= 3 lần.
Chạy trên GitHub Actions, kết quả lưu vào configs/jackpot1_triple.json.

Tối ưu: kiểm tra J2 (5/5) trước, chỉ khi đủ >= 3 J2 mới check ĐB.
"""
import csv, json, os, sys, time
from math import comb
from collections import defaultdict
from pathlib import Path

CSV_PATH = os.environ.get("CSV_PATH", "data/all.csv")
OUT_PATH = os.environ.get("OUT_PATH", "configs/jackpot1_triple.json")
START    = int(os.environ.get("SCAN_START", "1"))
END      = int(os.environ.get("SCAN_END",   "500000000"))
MIN_J1   = int(os.environ.get("MIN_J1",     "3"))

# ── Hàm jackpot_family ────────────────────────────────────────────────────────
M1,M2=0x9E3779B97F4A7C15,0xD1B54A32D192ED03
M3,M4=0xBF58476D1CE4E5B9,0x94D049BB133111EB
MASK=(1<<64)-1; C=comb(35,5)

def _mix(x):
    z=x&MASK; z^=z>>30; z=(z*M3)&MASK; z^=z>>27; z=(z*M4)&MASK; return z^(z>>31)
def _unrank(r):
    out,rem=[],r
    for k in range(5,0,-1):
        x=k-1
        while comb(x+1,k)<=rem: x+=1
        out.append(x+1); rem-=comb(x,k)
    return sorted(out)
def ticket(seed,d): return _unrank(_mix(seed*M1+d*M2)%C)
def special(seed,d): return _mix(_mix(seed*M1+d*M2))%12+1

# ── Load data ────────────────────────────────────────────────────────────────
res={}; spc={}; dates={}
with open(CSV_PATH,newline="",encoding="utf-8") as f:
    for row in csv.DictReader(f):
        try:
            d=int(row["draw_id"]); rj=json.loads(row["result_json"])
            res[d]=sorted(rj["numbers"]); spc[d]=rj["special_numbers"][0]
            dates[d]=row.get("draw_date","")
        except: continue

draw_ids=sorted(res.keys())
n=len(draw_ids)
print(f"Loaded {n} kỳ. Quét seed {START:,} → {END:,}, MIN_J1={MIN_J1}", flush=True)

# Index: tuple(5số) → list draw_id (tăng tốc check J2)
main_idx=defaultdict(list)
j1_idx=defaultdict(list)
for d in draw_ids:
    main_idx[tuple(res[d])].append(d)
    j1_idx[(tuple(res[d]),spc[d])].append(d)

# ── Quét ─────────────────────────────────────────────────────────────────────
found=[]
t0=time.time(); last_log=t0; checked=0

for seed in range(START,END+1):
    # Đếm J2 trước (nhanh hơn)
    j2_hits=[]
    for d in draw_ids:
        if ticket(seed,d)==res[d]:
            j2_hits.append(d)

    if len(j2_hits)<MIN_J1:
        checked+=1
        # Log tiến độ mỗi 10 giây
        now=time.time()
        if now-last_log>=10:
            rate=(seed-START+1)/(now-t0)
            eta=(END-seed)/rate if rate>0 else 0
            print(f"  {seed:,} ({rate:,.0f}/s) ETA {eta/3600:.1f}h J1found={len(found)}", flush=True)
            last_log=now
        continue

    # Có đủ J2 — check ĐB
    j1_hits=[d for d in j2_hits if special(seed,d)==spc[d]]
    if len(j1_hits)>=MIN_J1:
        entry={
            "seed": seed,
            "j1_count": len(j1_hits),
            "j2_count": len(j2_hits),
            "jackpot1_hits": [
                {"draw_id":d,"draw_date":dates[d],"numbers":res[d],"special":spc[d]}
                for d in j1_hits
            ],
            "jackpot2_hits": j2_hits,
        }
        found.append(entry)
        print(f"✅ seed={seed} J1={len(j1_hits)}x J2={len(j2_hits)}x kỳ={j1_hits}", flush=True)

    checked+=1
    now=time.time()
    if now-last_log>=10:
        rate=(seed-START+1)/(now-t0)
        eta=(END-seed)/rate if rate>0 else 0
        print(f"  {seed:,} ({rate:,.0f}/s) ETA {eta/3600:.1f}h J1found={len(found)}", flush=True)
        last_log=now

elapsed=time.time()-t0
print(f"\nXong: {checked:,} seed / {elapsed:.0f}s. Tìm thấy {len(found)} seed J1>={MIN_J1}")
Path(OUT_PATH).parent.mkdir(parents=True,exist_ok=True)
json.dump({"scan_start":START,"scan_end":END,"min_j1":MIN_J1,
           "elapsed_s":round(elapsed),"found":len(found),
           "results":sorted(found,key=lambda x:-x["j1_count"])},
          open(OUT_PATH,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
print(f"Saved → {OUT_PATH}")
