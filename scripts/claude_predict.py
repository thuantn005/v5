"""
claude_predict.py
-------------------
Replaces the old 10-strategy ensemble with a single call to Claude (the
strongest available Anthropic model) to pick numbers for Lotto 5/35.

HONESTY NOTE (unchanged from the old ensemble/model.py docstrings): Lotto
5/35 draws are independent random events. No model -- statistical or
LLM-based -- can raise the true odds of matching the draw. This module
exists because the repo owner explicitly asked to use an LLM instead of
the old statistical ensemble, not because it changes the math. The one
real lever (pari-mutuel crowd-avoidance) is still handled the same way it
always was: by excluding numbers a public reference tool already
recommends (see jackpot_hunter.py), which this module supports via the
exclude_main/exclude_special params.

No new dependency is added -- like the rest of the repo, this calls the
Claude Messages API directly with `requests` rather than pulling in the
`anthropic` SDK.
"""

from __future__ import annotations
import json
import os
import re

import requests

from model import Draw, MAIN_MIN, MAIN_MAX, SPECIAL_MIN, SPECIAL_MAX

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-4-8"
ANTHROPIC_VERSION = "2023-06-01"
MAX_RETRIES = 2


def _counts_in_window(history: list[Draw], window: int | None, use_special: bool) -> dict[int, int]:
    recent = history[-window:] if window else history
    pool = range(SPECIAL_MIN, SPECIAL_MAX + 1) if use_special else range(MAIN_MIN, MAIN_MAX + 1)
    counts = {n: 0 for n in pool}
    for d in recent:
        vals = [d.special] if use_special else d.numbers
        for n in vals:
            if n in counts:
                counts[n] += 1
    return counts


def _gap_since_last_seen(history: list[Draw], use_special: bool) -> dict[int, int]:
    pool = range(SPECIAL_MIN, SPECIAL_MAX + 1) if use_special else range(MAIN_MIN, MAIN_MAX + 1)
    gap = {n: len(history) for n in pool}
    for idx, d in enumerate(reversed(history)):
        vals = [d.special] if use_special else d.numbers
        for n in vals:
            if n in gap and gap[n] == len(history):
                gap[n] = idx
        if all(g != len(history) for g in gap.values()):
            break
    return gap


def _build_stats_summary(history: list[Draw]) -> str:
    """Compact, human-readable stats block given to Claude as background
    context. Purely informational -- the prompt makes clear this is a
    truly random game and the stats don't predict anything."""
    last = history[-1]
    main_50 = _counts_in_window(history, 50, False)
    main_200 = _counts_in_window(history, 200, False)
    main_gap = _gap_since_last_seen(history, False)
    special_50 = _counts_in_window(history, 50, True)
    special_gap = _gap_since_last_seen(history, True)

    lines = [
        f"Tổng số kỳ quay trong lịch sử: {len(history)}",
        f"Kỳ gần nhất: #{last.draw_id} ({last.draw_date} {last.draw_time or ''}) "
        f"-> {'-'.join(f'{n:02d}' for n in last.numbers)} + đặc biệt {last.special:02d}",
        "",
        "Tần suất số chính (1-35) trong 50 kỳ gần nhất (số: lần):",
        ", ".join(f"{n}:{c}" for n, c in sorted(main_50.items())),
        "",
        "Tần suất số chính trong 200 kỳ gần nhất:",
        ", ".join(f"{n}:{c}" for n, c in sorted(main_200.items())),
        "",
        "Số kỳ đã trôi qua kể từ lần cuối mỗi số chính xuất hiện (0 = vừa ra ở kỳ gần nhất):",
        ", ".join(f"{n}:{g}" for n, g in sorted(main_gap.items())),
        "",
        "Tần suất số đặc biệt (1-12) trong 50 kỳ gần nhất:",
        ", ".join(f"{n}:{c}" for n, c in sorted(special_50.items())),
        "",
        "Số kỳ kể từ lần cuối mỗi số đặc biệt xuất hiện:",
        ", ".join(f"{n}:{g}" for n, g in sorted(special_gap.items())),
    ]
    return "\n".join(lines)


def _build_prompt(history: list[Draw], n_sets: int, exclude_main: set[int], exclude_special: set[int]) -> tuple[str, str]:
    stats = _build_stats_summary(history)

    exclude_note = ""
    if exclude_main or exclude_special:
        exclude_note = (
            f"\nBẮT BUỘC loại trừ hoàn toàn các số chính sau (không dùng trong bất kỳ bộ nào): "
            f"{sorted(exclude_main) or 'không có'}.\n"
            f"BẮT BUỘC loại trừ số đặc biệt sau: {sorted(exclude_special) or 'không có'}.\n"
            f"Lý do: đây là các số một công cụ dự đoán công khai khác đã khuyến nghị cho kỳ này -- "
            f"tránh trùng để giảm rủi ro phải CHIA giải nếu trúng (Vietlott chia đều giải Độc Đắc "
            f"pari-mutuel giữa các vé cùng trúng)."
        )

    system = (
        "Bạn đang hỗ trợ một dự án cá nhân, phi thương mại về xổ số Vietlott Lotto 5/35 "
        "(chọn 5 số từ 1-35, cộng 1 số đặc biệt từ 1-12). SỰ THẬT QUAN TRỌNG BẠN PHẢI TÔN TRỌNG: "
        "đây là trò chơi hoàn toàn ngẫu nhiên, mỗi kỳ quay độc lập tuyệt đối với các kỳ trước. "
        "Xác suất trúng Độc Đắc cố định ở 1/324.632 bất kể chọn số nào, và KHÔNG có mô hình, "
        "thống kê, hay AI nào -- kể cả bạn -- có thể thực sự tăng xác suất đó. Số liệu thống kê "
        "cung cấp dưới đây chỉ để bạn tạo ra lựa chọn có 'câu chuyện' thú vị cho người dùng đọc, "
        "không phải vì nó có giá trị dự đoán thật. Không được tuyên bố hay ngụ ý rằng lựa chọn của "
        "bạn có xác suất trúng cao hơn ngẫu nhiên."
    )

    user = (
        f"Dữ liệu thống kê lịch sử (chỉ tham khảo, KHÔNG có giá trị dự đoán thật):\n{stats}\n"
        f"{exclude_note}\n\n"
        f"Hãy chọn {n_sets} bộ số khác nhau cho kỳ quay tiếp theo. Mỗi bộ gồm 5 số chính "
        f"phân biệt trong khoảng 1-35, và 1 số đặc biệt trong khoảng 1-12. Nếu {n_sets} > 1, "
        f"hãy làm các bộ đa dạng với nhau (tránh trùng lặp nhiều số giữa các bộ).\n\n"
        f"CHỈ trả lời bằng JSON hợp lệ, không thêm text nào khác, không dùng markdown code fence. "
        f"Định dạng chính xác:\n"
        f'[{{"main": [n1,n2,n3,n4,n5], "special": n, "rationale": "1-2 câu tiếng Việt ngắn gọn"}}, ...]\n'
        f"Mảng phải có đúng {n_sets} phần tử."
    )
    return system, user


def _extract_json(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def _validate_set(obj: dict, exclude_main: set[int], exclude_special: set[int]) -> dict | None:
    try:
        main = sorted(int(n) for n in obj["main"])
        special = int(obj["special"])
        rationale = str(obj.get("rationale", ""))
    except (KeyError, TypeError, ValueError):
        return None
    if len(main) != 5 or len(set(main)) != 5:
        return None
    if any(n < MAIN_MIN or n > MAIN_MAX for n in main):
        return None
    if special < SPECIAL_MIN or special > SPECIAL_MAX:
        return None
    if set(main) & exclude_main:
        return None
    if special in exclude_special:
        return None
    return {"main": main, "special": special, "rationale": rationale}


def _call_claude(system: str, user: str, api_key: str) -> str | None:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": 2048,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: Claude API call failed: {e}")
        return None
    data = resp.json()
    try:
        return "".join(block["text"] for block in data["content"] if block.get("type") == "text")
    except (KeyError, TypeError):
        print(f"WARNING: unexpected Claude API response shape: {data}")
        return None


def claude_pick(
    history: list[Draw],
    n_sets: int = 1,
    exclude_main: set[int] | None = None,
    exclude_special: set[int] | None = None,
) -> list[dict] | None:
    """Ask Claude for n_sets number sets. Returns a list of
    {"main": [5 ints], "special": int, "rationale": str}, or None if the
    API call/parse failed after retries -- callers must handle None by
    skipping that run's notification rather than guessing."""
    exclude_main = exclude_main or set()
    exclude_special = exclude_special or set()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY not set -- skipping Claude prediction.")
        return None

    system, user = _build_prompt(history, n_sets, exclude_main, exclude_special)

    for attempt in range(1, MAX_RETRIES + 1):
        raw = _call_claude(system, user, api_key)
        if raw is None:
            continue
        try:
            parsed = json.loads(_extract_json(raw))
        except json.JSONDecodeError as e:
            print(f"WARNING: Claude response was not valid JSON (attempt {attempt}): {e}\nRaw: {raw[:500]}")
            continue
        if not isinstance(parsed, list) or not parsed:
            print(f"WARNING: Claude response JSON was not a non-empty array (attempt {attempt}).")
            continue

        validated = []
        for obj in parsed:
            v = _validate_set(obj, exclude_main, exclude_special)
            if v is not None:
                validated.append(v)

        if len(validated) >= min(n_sets, len(parsed)) and validated:
            return validated[:n_sets] if len(validated) >= n_sets else validated
        print(f"WARNING: Claude response failed validation (attempt {attempt}): {parsed}")

    print("ERROR: Claude prediction failed after retries -- skipping this run's prediction.")
    return None


if __name__ == "__main__":
    import csv
    from model import parse_draws

    with open("data/all.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    draws = parse_draws(rows)
    result = claude_pick(draws, n_sets=1)
    print(json.dumps(result, ensure_ascii=False, indent=2))
