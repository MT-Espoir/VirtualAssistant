"""Direct path for an unambiguous A/C off timer voice command."""

import json
import re
from datetime import datetime

from utils.text_norm import norm


_MINUTES = r"(\d{1,4})\s*(?:phut|p)"
_AC = r"(?:may lanh|dieu hoa)"
_DURATION = r"(\d{1,4}|mot|hai|ba|bon|nam|sau|bay|tam|chin|muoi|nua)\s*(phut|tieng|gio)"
_ON_DURATION = re.compile(rf"(?:mo|bat)\s+{_AC}\s+(?:trong\s+(?:vong\s+)?|trong\s+)?{_DURATION}")
_NUMBERS = dict(zip(("mot", "hai", "ba", "bon", "nam", "sau", "bay", "tam", "chin", "muoi", "nua"),
                    (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 0.5)))
_PATTERNS = (
    re.compile(rf"{_MINUTES}\s+sau\s+tat\s+{_AC}"),
    re.compile(rf"(?:hay\s+)?tat\s+{_AC}\s+sau\s+{_MINUTES}"),
    re.compile(rf"hen\s+(?:gio\s+)?tat\s+{_AC}\s+(?:sau\s+)?{_MINUTES}"),
    re.compile(rf"sau\s+{_MINUTES}\s+(?:hay\s+)?tat\s+{_AC}"),
)


def match_ac_off_timer(text):
    """Only match a single explicit, relative A/C off command."""
    words = norm(text)
    words = re.sub(r"\s+", " ", words)
    words = re.sub(r"^alice\s+", "", words)
    words = re.sub(r"^(?:giup toi|lam on|vui long|nho|ban|em)\s+", "", words)
    words = re.sub(r"\s+(?:giup toi|nhe|voi|di|a)$", "", words)
    on = _ON_DURATION.fullmatch(words)
    if on:
        number, unit = on.groups()
        minutes = (_NUMBERS[number] if number in _NUMBERS else int(number)) * (1 if unit == "phut" else 60)
        if minutes == int(minutes) and 1 <= minutes <= 1440:
            return "control_room_ac", {"action": "on", "timer_minutes": int(minutes)}
    for pattern in _PATTERNS:
        match = pattern.fullmatch(words)
        if match:
            minutes = int(match.group(1))
            if 1 <= minutes <= 1440:
                return "control_room_ac", {"action": "schedule_off", "timer_minutes": minutes}
    return None


def describe_ac_off_timer_result(raw):
    """Speak success only when the gateway explicitly saved the timer."""
    try:
        result = json.loads(raw)
    except (TypeError, ValueError):
        return "Tôi chưa xác nhận được lịch tắt máy lạnh. Bạn kiểm tra lại giúp tôi."
    if not isinstance(result, dict):
        return "Tôi chưa xác nhận được lịch tắt máy lạnh."
    if result.get("status") == "scheduled" and result.get("run_until_local"):
        try:
            deadline = datetime.fromisoformat(result["run_until_local"])
        except (TypeError, ValueError):
            return "Tôi chưa xác nhận được giờ tắt máy lạnh. Bạn kiểm tra lại giúp tôi."
        return (f"Đã đặt lịch tắt máy lạnh lúc {deadline.hour} giờ "
                f"{deadline.minute:02d}, ngày {deadline.day}/{deadline.month}.")
    if result.get("status") == "room_required":
        return "Bạn muốn hẹn tắt máy lạnh ở phòng nào?"
    detail = result.get("message")
    return ("Tôi chưa đặt được lịch tắt máy lạnh" +
            (": " + str(detail) if detail else "."))


def describe_ac_result(raw, arguments):
    """Translate gateway diagnostics to speech, including uncertain delivery."""
    if arguments.get("action") == "schedule_off":
        return describe_ac_off_timer_result(raw)
    try:
        result = json.loads(raw)
    except (TypeError, ValueError):
        result = {}
    if not isinstance(result, dict):
        result = {}
    status = result.get("status")
    if status == "room_required":
        return "Bạn muốn điều khiển máy lạnh ở phòng nào?"
    action = "bật" if arguments.get("action") == "on" else "tắt"
    if status == "ir_sent":
        text = f"Thiết bị đã báo gửi lệnh {action} máy lạnh; chưa xác minh trạng thái máy lạnh thực tế."
    elif status == "node_result_ok_uncorrelated":
        text = f"Thiết bị đã phản hồi thành công cho lệnh {action} máy lạnh; chưa xác minh trạng thái máy lạnh thực tế."
    elif status in ("queued_for_mqtt", "published_to_broker", "received", "pending", "ack_timeout_unknown"):
        text = f"Đã gửi yêu cầu {action} máy lạnh, nhưng chưa xác nhận thiết bị đã thực hiện."
    else:
        return "Tôi chưa thực hiện được lệnh máy lạnh. Bạn kiểm tra kết nối thiết bị rồi thử lại."
    if result.get("run_until_local"):
        timer = describe_ac_off_timer_result(json.dumps({
            "status": "scheduled", "run_until_local": result["run_until_local"]}))
        text += " " + timer
    elif arguments.get("timer_minutes"):
        text += " Tôi chưa xác nhận được lịch tự tắt."
    return text


def match_ac_automation(text):
    words = re.sub(r"^alice\s+", "", norm(text))
    match = re.fullmatch(
        r"(?:khi\s+)?nhiet do\s+(?:phong\s+)?(?:tang len\s+|len\s+)?"
        r"(?:tren|vuot(?: qua)?)\s+(\d{1,2}(?:[.,]\d+)?)\s*(?:do\s*c|do)?"
        r"\s+(?:thi\s+)?(?:em\s+)?(?:hay\s+)?(?:tu dong\s+)?(?:bat|mo)\s+(?:may lanh|dieu hoa)", words)
    if match:
        threshold = float(match.group(1).replace(",", "."))
        if 16 <= threshold <= 50:
            return "configure_climate_automation", {"enabled": True, "threshold_c": threshold}
    return None


def describe_automation_result(raw):
    try:
        data = json.loads(raw)
        policy = data["policy"]
        if data["status"] != "saved":
            raise ValueError("not saved")
        if not policy["automation_enabled"]:
            return "Đã tắt chế độ tự bật máy lạnh."
        return (f"Đã lưu quy tắc: nhiệt độ trên {policy['threshold_c']:g} độ C "
                "trong 20 phút và có người trong phòng thì bật máy lạnh. "
                "Thời gian chờ giữa các lần bật vẫn được áp dụng.")
    except (ValueError, TypeError, KeyError):
        return "Tôi chưa lưu được quy tắc tự bật máy lạnh. Bạn kiểm tra gateway giúp tôi."


FAST_PATHS = (match_ac_off_timer, match_ac_automation)
