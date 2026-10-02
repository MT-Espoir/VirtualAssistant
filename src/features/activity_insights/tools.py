"""Agent adapters cho Activity Insights và preference do chính người dùng chọn."""

import json

from agent.tools import Tool


def _query(service, bus, period="today", view="overview"):
    snapshot = service.snapshot(period=period, view=view)
    if bus is not None:
        bus.emit_activity(snapshot)
    return service.llm_result(snapshot)


def _settings(service, bus, action, app_id=None, category=None):
    result = service.apply_setting(action, app_id=app_id, category=category)
    snapshot = service.refresh_snapshot()
    if bus is not None:
        bus.emit_activity(snapshot)
    return json.dumps({"status": "ok", **result}, ensure_ascii=False,
                      separators=(",", ":"))


def _run(service, bus, action="query", period="today", view="overview",
         app_id=None, category=None):
    if action == "query":
        return _query(service, bus, period, view)
    return _settings(service, bus, action, app_id, category)


def register(reg, ctx):
    service, bus = ctx.activity_insights, ctx.bus
    reg.register(Tool(
        name="activity_insights",
        description=(
            "Xem activity local; hoặc theo yêu cầu rõ ràng, phân loại/loại trừ app và "
            "xóa lịch sử. Không suy luận stress, deadline hay năng suất."),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["query", "classify", "exclude", "include", "reset",
                             "clear_history"],
                },
                "period": {
                    "type": "string", "enum": ["today", "7_days", "30_days"],
                },
                "view": {
                    "type": "string", "enum": ["overview", "apps", "focus", "trend"],
                },
                "app_id": {"type": "string"},
                "category": {
                    "type": "string",
                    "enum": ["work", "communication", "media", "personal", "unknown"],
                },
            },
        },
        handler=lambda action="query", period="today", view="overview",
                       app_id=None, category=None: _run(
            service, bus, action, period, view, app_id, category),
        destructive=lambda action=None, **_: action == "clear_history",
        confirm_message=lambda action=None, **_: (
            "xóa toàn bộ lịch sử hoạt động SALM" if action == "clear_history"
            else "cập nhật phân loại ứng dụng"),
        persistent=lambda action="query", **_: action != "query",
    ))
