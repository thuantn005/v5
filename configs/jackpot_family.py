"""jackpot_family.py — ho thuat toan SplitMix64 cho cac 'jackpot config' (repo v5).

Moi config = 1 seed. Ve ky i = unrank_colex( splitmix64(seed*M1 + i*M2) mod C(35,5) ).
Cac config trong configs/jackpot_configs.json tung trung >=2 jackpot 5/5 trong lich su
753 ky dau — thuan survivorship tu viec quet hang chuc trieu seed.
Xac suat ky toi cua moi config: 1/324,632 (nhu moi ve bat ky).
"""
from math import comb

M1, M2 = 0x9E3779B97F4A7C15, 0xD1B54A32D192ED03
M3, M4 = 0xBF58476D1CE4E5B9, 0x94D049BB133111EB
MASK = (1 << 64) - 1
C = comb(35, 5)  # 324,632


def _mix(x: int) -> int:
    z = x & MASK
    z ^= z >> 30; z = (z * M3) & MASK
    z ^= z >> 27; z = (z * M4) & MASK
    return z ^ (z >> 31)


def _unrank(r: int) -> list[int]:
    out, rem = [], r
    for k in range(5, 0, -1):
        x = k - 1
        while comb(x + 1, k) <= rem:
            x += 1
        out.append(x + 1); rem -= comb(x, k)
    return sorted(out)


def ticket(seed: int, draw_id: int) -> list[int]:
    """5 so chinh cua config `seed` cho ky `draw_id`."""
    return _unrank(_mix(seed * M1 + draw_id * M2) % C)


def special(seed: int, draw_id: int) -> int:
    """So dac biet 1-12 (mo rong cung stream)."""
    return _mix(_mix(seed * M1 + draw_id * M2)) % 12 + 1


def verify(seed: int, draws: dict[int, list[int]]) -> list[int]:
    """Tra ve danh sach draw_id ma config trung 5/5 trong `draws`."""
    return [d for d, nums in draws.items() if ticket(seed, d) == sorted(nums)]
