"""
Test OllamaLLMClient — dịch qua lại giữa kiểu trung lập và định dạng Ollama.

Dùng http_post giả (trả về object có .json()) nên không cần requests, mạng, hay
Ollama đang chạy. Kiểm tra: parse phản hồi (text / tool_calls, arguments dạng dict
lẫn chuỗi JSON) và dựng payload gửi đi (system, tools, tool result role 'tool').
"""

try:
    import pytest
except ImportError:
    pytest = None

from llm.client import Message, ToolCall, ToolResult, OllamaLLMClient


class FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def make_client(response_data):
    captured = {}

    def fake_post(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return FakeResp(response_data)

    client = OllamaLLMClient(model="llama3.1", base_url="http://localhost:11434",
                             http_post=fake_post)
    return client, captured


def test_parse_text_response():
    client, _ = make_client({"message": {"role": "assistant", "content": "Xin chào!"}})
    turn = client.generate(system="s", messages=[Message(role="user", text="chào")], tools=[])
    assert turn.text == "Xin chào!"
    assert turn.tool_calls == []


def test_parse_tool_call_dict_args():
    client, _ = make_client({"message": {"content": "", "tool_calls": [
        {"function": {"name": "open_app", "arguments": {"app_name": "chrome"}}},
    ]}})
    turn = client.generate(system="s", messages=[Message(role="user", text="mở chrome")], tools=[])
    assert turn.wants_tools
    tc = turn.tool_calls[0]
    assert tc.name == "open_app" and tc.arguments == {"app_name": "chrome"}
    assert tc.id  # có id tổng hợp


def test_parse_tool_call_json_string_args():
    client, _ = make_client({"message": {"content": "", "tool_calls": [
        {"function": {"name": "set_volume", "arguments": '{"change": 20}'}},
    ]}})
    turn = client.generate(system="s", messages=[Message(role="user", text="tăng")], tools=[])
    assert turn.tool_calls[0].arguments == {"change": 20}


def test_payload_has_system_and_tools():
    client, captured = make_client({"message": {"content": "ok"}})
    tools = [{"name": "open_app", "description": "mở app",
              "input_schema": {"type": "object", "properties": {"app_name": {"type": "string"}}}}]
    client.generate(system="Bạn là trợ lý", messages=[Message(role="user", text="hi")], tools=tools)
    payload = captured["payload"]
    assert payload["messages"][0] == {"role": "system", "content": "Bạn là trợ lý"}
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["function"]["name"] == "open_app"
    assert payload["stream"] is False


def test_tool_result_becomes_tool_role():
    client, captured = make_client({"message": {"content": "done"}})
    messages = [
        Message(role="user", text="mở chrome"),
        Message(role="assistant", tool_calls=[ToolCall("call_0", "open_app", {"app_name": "chrome"})]),
        Message(role="user", tool_results=[ToolResult("call_0", "Đã mở Chrome", name="open_app")]),
    ]
    client.generate(system="", messages=messages, tools=[])
    sent = captured["payload"]["messages"]
    tool_msg = [m for m in sent if m["role"] == "tool"][0]
    assert tool_msg["tool_name"] == "open_app" and tool_msg["content"] == "Đã mở Chrome"
    # lượt assistant kèm tool_calls được dịch đúng
    asst = [m for m in sent if m["role"] == "assistant"][0]
    assert asst["tool_calls"][0]["function"]["name"] == "open_app"


if __name__ == "__main__":
    if pytest is not None:
        raise SystemExit(pytest.main([__file__, "-v"]))
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print("PASS", _name)
            except Exception as _e:  # noqa: BLE001
                failures += 1
                print("FAIL", _name, "->", repr(_e))
    print(f"\n{'ALL PASS' if not failures else str(failures) + ' FAILED'}")
    raise SystemExit(1 if failures else 0)
