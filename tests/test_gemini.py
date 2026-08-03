"""Test provider Gemini + xoay vòng model (llm.gemini) — http_post giả."""

try:
    import pytest
except ImportError:
    pytest = None

from llm.client import Message, ToolCall, ToolResult
from llm.gemini import (
    RateTracker, GeminiModelClient, RotatingGeminiClient, GeminiRateLimit,
    to_gemini_tools, to_gemini_contents, parse_model_specs)


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _cand(parts):
    return {"candidates": [{"content": {"parts": parts, "role": "model"}}]}


# --------------------------- RateTracker --------------------------- #

def test_rate_tracker_rpm_limit():
    t = RateTracker(rpm=2, rpd=0)
    assert t.available(1000.0)
    t.record(1000.0); t.record(1000.5)
    assert not t.available(1001.0)                 # đã 2 lượt trong 60s
    assert t.available(1061.0)                      # qua 60s -> khả dụng lại


def test_rate_tracker_rpd_limit():
    t = RateTracker(rpm=0, rpd=2)
    t.record(1000.0); t.record(1100.0)
    assert not t.available(1200.0)                  # hết lượt/ngày
    # sang ngày mới (cách > 24h) -> reset
    assert t.available(1000.0 + 86400 * 2)


def test_rate_tracker_reactive_block_rpm():
    t = RateTracker(rpm=0, rpd=0)                   # không giới hạn chủ động
    assert t.available(1000.0)
    t.block_rpm(1000.0)
    assert not t.available(1030.0)                  # bị chặn 60s
    assert t.available(1061.0)


def test_rate_tracker_reactive_block_rpd():
    t = RateTracker(rpm=0, rpd=0)
    t.block_rpd(1000.0)
    assert not t.available(1500.0)                  # chặn hết ngày


# --------------------------- dịch định dạng --------------------------- #

def test_to_gemini_tools_uppercases_type_and_omits_empty():
    tools = [
        {"name": "set_volume", "description": "d",
         "input_schema": {"type": "object",
                          "properties": {"level": {"type": "integer", "description": "x"}}}},
        {"name": "take_screenshot", "description": "chụp",
         "input_schema": {"type": "object", "properties": {}}},
    ]
    out = to_gemini_tools(tools)
    decls = out[0]["function_declarations"]
    assert decls[0]["parameters"]["type"] == "OBJECT"
    assert decls[0]["parameters"]["properties"]["level"]["type"] == "INTEGER"
    assert "parameters" not in decls[1]             # không có properties -> no-arg


def test_to_gemini_tools_strips_unsupported_fields():
    # Schema MCP/pydantic có additionalProperties/title/default -> Gemini 400 nếu không lọc
    tools = [{"name": "gws_gmail_unread", "description": "d",
              "input_schema": {"type": "object", "additionalProperties": False, "title": "X",
                               "properties": {"user_email": {"type": "string", "default": "",
                                                             "title": "User Email"}}}}]
    params = to_gemini_tools(tools)[0]["function_declarations"][0]["parameters"]
    assert "additionalProperties" not in params and "title" not in params
    assert "default" not in params["properties"]["user_email"]      # trường lạ bị bỏ
    assert params["properties"]["user_email"]["type"] == "STRING"    # trường hợp lệ giữ nguyên


def test_to_gemini_contents_maps_roles_and_tools():
    msgs = [
        Message(role="user", text="chào"),
        Message(role="assistant", tool_calls=[ToolCall("c1", "open_app", {"app_name": "chrome"})]),
        Message(role="user", tool_results=[ToolResult("c1", "Đã mở", name="open_app")]),
    ]
    contents = to_gemini_contents(msgs)
    assert contents[0] == {"role": "user", "parts": [{"text": "chào"}]}
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][0]["functionCall"]["name"] == "open_app"
    assert contents[2]["role"] == "user"
    fr = contents[2]["parts"][0]["functionResponse"]
    assert fr["name"] == "open_app" and fr["response"] == {"result": "Đã mở"}


# --------------------------- GeminiModelClient --------------------------- #

def test_thought_signature_captured_and_echoed():
    # Gemini 3.x: functionCall kèm thoughtSignature -> phải giữ và echo lại lượt sau
    def fake_post(url, payload):
        return _Resp(_cand([{"functionCall": {"name": "open_app", "args": {"app_name": "x"}},
                             "thoughtSignature": "SIG123"}]))
    c = GeminiModelClient("m", "key", http_post=fake_post)
    turn = c.generate(system="", messages=[Message(role="user", text="x")], tools=[])
    assert turn.tool_calls[0].thought_signature == "SIG123"
    # echo lại: part functionCall phải kèm thoughtSignature
    contents = to_gemini_contents([Message(role="assistant", tool_calls=turn.tool_calls)])
    assert contents[0]["parts"][0]["thoughtSignature"] == "SIG123"


def test_model_client_parses_text_and_tool_call():
    def fake_post(url, payload):
        return _Resp(_cand([{"text": "ok"},
                            {"functionCall": {"name": "set_volume", "args": {"level": 50}}}]))
    c = GeminiModelClient("m", "key", http_post=fake_post)
    turn = c.generate(system="s", messages=[Message(role="user", text="x")], tools=[])
    assert turn.text == "ok"
    assert turn.tool_calls[0].name == "set_volume" and turn.tool_calls[0].arguments == {"level": 50}


def test_model_client_raises_rpm_on_429():
    def fake_post(url, payload):
        return _Resp({"error": {"message": "Quota exceeded per minute"}}, status=429)
    c = GeminiModelClient("m", "key", http_post=fake_post)
    with pytest.raises(GeminiRateLimit) as ei:
        c.generate(system="", messages=[Message(role="user", text="x")], tools=[])
    assert ei.value.scope == "rpm"


def test_model_client_raises_rpd_on_daily_429():
    def fake_post(url, payload):
        return _Resp({"error": {"message": "Quota exceeded PerDay limit"}}, status=429)
    c = GeminiModelClient("m", "key", http_post=fake_post)
    with pytest.raises(GeminiRateLimit) as ei:
        c.generate(system="", messages=[Message(role="user", text="x")], tools=[])
    assert ei.value.scope == "rpd"


# --------------------------- RotatingGeminiClient --------------------------- #

def _rot(fakes, specs, now=1000.0):
    """Dựng client xoay vòng với http_post tuỳ theo model (map tên -> hàm)."""
    def dispatch(url, payload):
        model = url.split("/models/")[1].split(":")[0]
        return fakes[model](url, payload)
    return RotatingGeminiClient("key", specs, http_post=dispatch, now=lambda: now)


def test_rotate_when_first_model_rate_limited():
    calls = {"a": 0, "b": 0}
    def a(url, p):
        calls["a"] += 1
        return _Resp({"error": {"message": "per minute"}}, status=429)
    def b(url, p):
        calls["b"] += 1
        return _Resp(_cand([{"text": "từ B"}]))
    rot = _rot({"a": a, "b": b}, [("a", 5, 20), ("b", 10, 20)])
    turn = rot.generate(system="", messages=[Message(role="user", text="x")], tools=[])
    assert turn.text == "từ B" and calls["a"] == 1 and calls["b"] == 1


def test_rpd_block_persists_skips_model_next_call():
    calls = {"a": 0, "b": 0}
    def a(url, p):
        calls["a"] += 1
        return _Resp({"error": {"message": "PerDay"}}, status=429)
    def b(url, p):
        calls["b"] += 1
        return _Resp(_cand([{"text": "B"}]))
    rot = _rot({"a": a, "b": b}, [("a", 5, 20), ("b", 10, 20)])
    rot.generate(system="", messages=[Message(role="user", text="1")], tools=[])
    rot.generate(system="", messages=[Message(role="user", text="2")], tools=[])
    assert calls["a"] == 1 and calls["b"] == 2       # A bị chặn hết ngày -> lượt 2 bỏ qua A


def test_all_exhausted_raises():
    def boom(url, p):
        return _Resp({"error": {"message": "per minute"}}, status=429)
    rot = _rot({"a": boom}, [("a", 5, 20)])
    with pytest.raises(RuntimeError):
        rot.generate(system="", messages=[Message(role="user", text="x")], tools=[])


# --------------------------- parse_model_specs --------------------------- #

def test_parse_model_specs():
    out = parse_model_specs("a:5:20, b:10:500 ,c")
    assert out == [("a", 5, 20), ("b", 10, 500), ("c", 0, 0)]


if __name__ == "__main__":
    if pytest is not None:
        raise SystemExit(pytest.main([__file__, "-v"]))
