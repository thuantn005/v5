#!/usr/bin/env python3
"""
scan_tier3.py — Tìm seed trúng >=3/5 số chính nhiều kỳ nhất.
"""
import csv,json,os,sys,time
from math import comb

CSV_PATH  = os.environ.get("CSV_PATH","data/all.csv")
OUT_PATH  = os.environ.get("OUT_PATH","configs/tier3_top.json")
START     = int(os.environ.get("SCAN_START","1"))
END       = int(os.environ.get("SCAN_END","50000000"))
TOP_N     = int(os.environ.get("TOP_N","20"))

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

res={}
with open(CSV_PATH,newline="",encoding="utf-8") as f:
    for row in csv.DictReader(f):
        try:
            d=int(row["draw_id"]); rj=json.loads(row["result_json"])
            res[d]=set(rj["numbers"])
        except: continue

draw_ids=sorted(res.keys()); n=len(draw_ids)
print(f"Loaded {n} kỳ. Quét seed {START:,}→{END:,}",flush=True)

# Top heap
top=[]  # (count, seed)
t0=time.time(); last_log=t0
MIN_COUNT=0  # ngưỡng tối thiểu để vào top

for seed in range(START,END+1):
    count=0
    for d in draw_ids:
        t=ticket(seed,d)
        if len(set(t)&res[d])>=3:
            count+=1

    if count>MIN_COUNT:
        top.append((count,seed))
        top.sort(reverse=True)
        if len(top)>TOP_N:
            top=top[:TOP_N]
            MIN_COUNT=top[-1][0]

    now=time.time()
    if now-last_log>=15:
        rate=(seed-START+1)/(now-t0)
        print(f"  {seed:,} ({rate:,.0f}/s) top1={top[0][0] if top else 0} min={MIN_COUNT}",flush=True)
        last_log=now

import os; os.makedirs(os.path.dirname(OUT_PATH) if os.path.dirname(OUT_PATH) else ".",exist_ok=True)
results=[{"seed":s,"tier3_count":c,"ticket_kỳ_tới":ticket(s,draw_ids[-1]+1)} for c,s in top]
json.dump({"scan_start":START,"scan_end":END,"total_draws":n,
           "expected_random":round(n*comb(5,3)*comb(30,2)/comb(35,5),1),
           "results":results},
          open(OUT_PATH,"w"),ensure_ascii=False,indent=1)
print(f"\nTop {TOP_N} seeds:")
for c,s in top[:10]:
    print(f"  seed={s} tier3={c}/{n} ({c/n*100:.1f}%)")
