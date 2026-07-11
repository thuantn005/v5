"""
jackpot_watch.py
-----------------
State machine theo dõi kỳ CHIA GIẢI ĐỘC ĐẮC Lotto 5/35.

Port từ V51/share_draw.py — logic đầy đủ hơn jackpot_watch cũ:
  - scheduled  : jackpot vừa vượt 12 tỷ → đã xác định kỳ chia giải (21:00 ngày mai)
  - reminder   : hôm nay là ngày chia giải → nhắc "TỐI NAY 21:00"
  - cancelled  : có người trúng Độc Đắc trước kỳ chia giải → huỷ
  - completed  : kỳ chia giải đã diễn ra, pot về mốc khởi điểm
  - scrape_fail: không lấy được jackpot từ bất kỳ nguồn nào → cảnh báo 1 lần

State lưu tại state/jackpot_state.json, tự reset khi pot giảm (chu kỳ mới).

Thể lệ Vietlott (đã đối chiếu):
  Sau khi kết thúc một kỳ quay bất kỳ, nếu giá trị Giải Độc Đắc VƯỢT 12 tỷ đồng
  và không có người trúng, thì kỳ quay CUỐI CÙNG (21:00) của NGÀY LIỀN KẾ TIẾP THEO
  được xác định là kỳ "Chia Giải Độc Đắc".
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

STATE_PATH = "state/jackpot_state.json"
JACKPOT_THRESHOLD = 12_000_000_000
SHARE_DRAW_TIME = "21:00"
VN_TZ = timezone(timedelta(hours=7))

_DEFAULT_STATE: dict = {
    "pending": False,           # đang chờ kỳ chia giải?
    "share_date": None,         # "YYYY-MM-DD" của kỳ chia giải
    "reminded": False,          # đã gửi nhắc "tối nay chia giải" chưa?
    "peak_jackpot": 0,          # giá trị pot lớn nhất quan sát được chu kỳ này
    "trigger_draw_id": None,    # kỳ quay làm pot vượt 12 tỷ
    "trigger_draw_date": None,  # ngày của trigger_draw_id
    "scrape_fail_alerted": False,  # đã gửi cảnh báo scrape lỗi chưa?
}


# ── State I/O ────────────────────────────────────────────────────────────────

def _load() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return {**_DEFAULT_STATE, **json.load(f)}
        except Exception:
            pass
    return dict(_DEFAULT_STATE)


def _save(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── Compat helpers (dùng bởi run_pipeline.py) ───────────────────────────────

def get_threshold_crossed_date() -> str | None:
    """Ngày (YYYY-MM-DD) mà jackpot lần đầu vượt 12 tỷ chu kỳ này, hoặc None."""
    return _load().get("trigger_draw_date")


# ── Format ───────────────────────────────────────────────────────────────────

def _fmt(vnd: int | None) -> str:
    if vnd is None:
        return "?"
    s = f"{vnd:,}".replace(",", ".")
    return f"{s} đ (~{vnd / 1e9:.1f} tỷ)" if vnd >= 1e9 else f"{s} đ"


def _event(kind: str, title: str, message: str,
           priority: str = "high", tags: str = "moneybag") -> dict:
    return {"kind": kind, "title": title, "message": message,
            "priority": priority, "tags": tags}


def _reminder_event(share_date, peak_jackpot) -> dict:
    """Sự kiện nhắc 'TỐI NAY chia giải'. Chỉ cần ngày chia giải + pot đỉnh
    (đều đã lưu trong state) — KHÔNG cần jackpot scrape mới. Nhờ vậy reminder
    vẫn gửi được ngay cả khi tra cứu jackpot tạm thời lỗi."""
    return _event(
        "reminder",
        "🔔 TỐI NAY: kỳ CHIA GIẢI Độc Đắc Lotto 5/35!",
        f"Kỳ quay {SHARE_DRAW_TIME} hôm nay ({share_date:%d/%m/%Y}) "
        f"là kỳ CHIA GIẢI. Độc Đắc ~{_fmt(peak_jackpot)} "
        f"sẽ chia cho Giải Nhất (2/6) và Nhì/Ba/Tư/Năm (mỗi giải 1/6) "
        f"nếu không ai trúng trực tiếp. Nhớ mua vé trước giờ quay!",
        priority="max",
        tags="rotating_light,moneybag,alarm_clock",
    )


def _parse_date(s: str | None):
    """Parse 'YYYY-MM-DD' → date, hoặc None nếu không hợp lệ."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ── State machine chính ──────────────────────────────────────────────────────

def check_share_draw(jackpot_vnd: int | None,
                     last_draw_id: str | None = None,
                     last_draw_date: str | None = None) -> list[dict]:
    """Cập nhật trạng thái chia giải sau mỗi lần chạy pipeline.

    Args:
        jackpot_vnd    : giá trị Độc Đắc hiện tại (None nếu scrape thất bại)
        last_draw_id   : draw_id của kỳ vừa quay
        last_draw_date : draw_date của kỳ vừa quay (YYYY-MM-DD)

    Returns:
        Danh sách event dict {kind, title, message, priority, tags} cần ntfy.
    """
    events: list[dict] = []
    state = _load()
    today = datetime.now(VN_TZ).date()

    # ── Trường hợp scrape thất bại ─────────────────────────────────────────
    if jackpot_vnd is None:
        # Kỳ chia giải đã được xác định từ trước và HÔM NAY chính là ngày chia
        # giải → vẫn phải nhắc, dù không lấy được jackpot mới. Reminder chỉ dựa
        # vào share_date + peak_jackpot đã lưu trong state, nên scrape lỗi
        # KHÔNG được làm mất thông báo quan trọng này.
        share_date = _parse_date(state.get("share_date"))
        if (state.get("pending") and share_date is not None
                and today == share_date and not state.get("reminded")):
            state["reminded"] = True
            _save(state)
            events.append(_reminder_event(share_date, state.get("peak_jackpot")))
            return events

        if not state.get("scrape_fail_alerted"):
            state["scrape_fail_alerted"] = True
            _save(state)
            events.append(_event(
                "scrape_fail",
                "⚠️ Lotto 5/35 – Không lấy được số Jackpot",
                "Tất cả nguồn tra cứu giá trị Giải Độc Đắc đều lỗi. "
                "Hệ thống TẠM THỜI không thể tự xác định kỳ CHIA GIẢI. "
                "Kiểm tra thủ công trên vietlott.vn. "
                "Sẽ chỉ nhận cảnh báo này 1 lần cho đến khi tra cứu hoạt động trở lại.",
                priority="high",
                tags="warning",
            ))
        return events

    # scrape OK → reset cờ scrape_fail
    state["scrape_fail_alerted"] = False

    print(f"[jackpot_watch] Độc Đắc hiện tại: {_fmt(jackpot_vnd)}")

    # ── Đang chờ kỳ chia giải ──────────────────────────────────────────────
    if state["pending"]:
        share_date = _parse_date(state.get("share_date"))
        if share_date is None:
            # share_date hỏng → không thể theo dõi kỳ chia giải, reset an toàn.
            print("[jackpot_watch] share_date không hợp lệ, reset state.")
            _save({**_DEFAULT_STATE, "peak_jackpot": jackpot_vnd})
            return events
        peak = max(state.get("peak_jackpot") or 0, 0)

        if jackpot_vnd < JACKPOT_THRESHOLD and jackpot_vnd < peak * 0.8:
            # Pot đã reset → có người trúng Độc Đắc hoặc kỳ chia giải đã diễn ra
            if today <= share_date:
                events.append(_event(
                    "cancelled",
                    "🚫 Huỷ kỳ chia giải Lotto 5/35",
                    f"Đã có người trúng Độc Đắc (~{_fmt(peak)}) trước kỳ "
                    f"chia giải {share_date:%d/%m}. Pot quay về ~6 tỷ.",
                    priority="default",
                    tags="x,tada",
                ))
            else:
                events.append(_event(
                    "completed",
                    "✅ Kỳ chia giải Lotto 5/35 đã diễn ra",
                    f"Kỳ chia giải ngày {share_date:%d/%m/%Y} đã xong "
                    f"(pot trước chia ~{_fmt(peak)}). "
                    f"Pot hiện tại: {_fmt(jackpot_vnd)}.",
                    priority="default",
                    tags="white_check_mark",
                ))
            # Reset về chu kỳ mới
            state = {**_DEFAULT_STATE, "peak_jackpot": jackpot_vnd}

        else:
            state["peak_jackpot"] = max(peak, jackpot_vnd)
            if today == share_date and not state["reminded"]:
                events.append(_reminder_event(share_date, state["peak_jackpot"]))
                state["reminded"] = True
            elif (today - share_date).days > 2:
                # Dữ liệu trễ bất thường → reset cho sạch
                print("[jackpot_watch] State quá hạn >2 ngày, reset.")
                state = {**_DEFAULT_STATE, "peak_jackpot": jackpot_vnd}

    # ── Chưa có kỳ chia giải đang chờ ─────────────────────────────────────
    else:
        state["peak_jackpot"] = max(state.get("peak_jackpot") or 0, jackpot_vnd)

        if jackpot_vnd > JACKPOT_THRESHOLD:
            # Xác định ngày trigger: ưu tiên last_draw_date, fallback today
            try:
                trigger_date = (
                    datetime.strptime(last_draw_date, "%Y-%m-%d").date()
                    if last_draw_date else today
                )
            except ValueError:
                trigger_date = today

            share_date = trigger_date + timedelta(days=1)
            state.update({
                "pending": True,
                "share_date": share_date.isoformat(),
                "reminded": False,
                "trigger_draw_id": last_draw_id,
                "trigger_draw_date": trigger_date.isoformat(),
            })
            events.append(_event(
                "scheduled",
                "🔔 Lotto 5/35 – Jackpot vừa vượt 12 tỷ!",
                f"Giải Độc Đắc: {_fmt(jackpot_vnd)}.\n"
                f"Nếu không ai trúng trước đó, kỳ quay {SHARE_DRAW_TIME} ngày "
                f"{share_date:%d/%m/%Y} sẽ là kỳ CHIA GIẢI ĐỘC ĐẮC "
                f"(Giải Nhất +2/6, các giải Nhì-Năm mỗi giải +1/6 giá trị pot).",
                priority="high",
                tags="rotating_light,moneybag",
            ))

    _save(state)
    return events


# ── Compat: hàm cũ jackpot_watch dùng trong run_pipeline ────────────────────

def check_early_alert(jackpot_vnd: int | None,
                      draw_date: str | None = None) -> dict:
    """Backward-compat wrapper — không dùng trực tiếp nữa, thay bằng check_share_draw."""
    return {"should_alert": False, "jackpot_vnd": jackpot_vnd}


def check_scrape_alert(jackpot_vnd: int | None) -> dict:
    """Backward-compat wrapper — scrape alert giờ nằm trong check_share_draw."""
    return {"should_alert": False, "jackpot_vnd": jackpot_vnd}


def _self_test_reminder_survives_scrape_fail():
    """Regression: khi đã có kỳ chia giải đang chờ và HÔM NAY là ngày chia
    giải, reminder phải gửi ngay cả khi scrape jackpot thất bại (jackpot=None).
    Trước đây bug: hàm return sớm ở nhánh scrape_fail → mất reminder → hệ thống
    'không tìm được kỳ quay chia giải Độc Đắc' đúng ngày quan trọng nhất."""
    import tempfile
    global STATE_PATH
    orig_path = STATE_PATH
    fd = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8")
    today = datetime.now(VN_TZ).date().isoformat()
    json.dump({
        "pending": True, "share_date": today, "reminded": False,
        "peak_jackpot": 13_500_000_000, "trigger_draw_id": "00756",
        "trigger_draw_date": (datetime.now(VN_TZ).date()
                              - timedelta(days=1)).isoformat(),
        "scrape_fail_alerted": True,
    }, fd, ensure_ascii=False)
    fd.close()
    STATE_PATH = fd.name
    try:
        events = check_share_draw(None, last_draw_id="00757",
                                  last_draw_date=today)
        kinds = [e["kind"] for e in events]
        assert kinds == ["reminder"], f"expected reminder, got {kinds}"
        assert _load()["reminded"] is True, "reminded flag phải được set"
        # Chạy lại: đã reminded → không lặp lại reminder
        assert [e["kind"] for e in check_share_draw(None)] != ["reminder"]
    finally:
        os.unlink(fd.name)
        STATE_PATH = orig_path
    print("reminder-survives-scrape-fail self-test: OK")


if __name__ == "__main__":
    _self_test_reminder_survives_scrape_fail()
    # Test thủ công
    print("--- test: vượt 12 tỷ ---")
    for ev in check_share_draw(13_000_000_000, "00755", "2026-07-11"):
        print(f"[{ev['kind']}] {ev['title']}\n{ev['message']}\n")
    print("--- test: chạy lần 2 (đã scheduled) ---")
    for ev in check_share_draw(13_500_000_000, "00756", "2026-07-11"):
        print(f"[{ev['kind']}] {ev['title']}\n{ev['message']}\n")
