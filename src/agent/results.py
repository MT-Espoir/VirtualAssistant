"""Kết quả có cấu trúc của một lần gọi tool (hợp đồng R0.6/R1.2).

Từ vựng, danh mục mã lý do và quy tắc ở đây theo `docs/alice_result_contract_spec.md`
§3–§5, §7. Danh mục là tập đóng: thêm mã mới phải sửa cả spec.

`ActionResult` kế thừa `str` để mọi nơi đang dùng output như một câu (fast path, panel,
`describe_ac_result`, test) vẫn chạy nguyên trong lúc migration; trạng thái đi kèm theo
thuộc tính, không nằm trong câu.
"""

STATUSES = frozenset({"verified", "dispatched", "unknown", "failed", "refused",
                      "declined", "not_attempted"})

# Trạng thái mà Agent phải báo LLM là lỗi và không được chốt lượt là "xong".
ERROR_STATUSES = frozenset({"failed", "refused", "unknown", "not_attempted", "declined"})

REASONS = frozenset({
    "ok", "accepted_unverified", "no_client", "selected_profile_disconnected",
    "connection_changed", "connection_lost", "transport_error", "deadline_exceeded",
    "data_scope_not_authorized", "target_changed", "target_not_found", "target_ambiguous",
    "dependency_unavailable", "publish_failed", "ack_timeout_unknown", "remote_error",
    "process_exit_nonzero", "storage_error", "policy_refused", "user_declined",
    "superseded_by_new_request", "suppressed_by_dnd", "invalid_arguments",
    "handler_exception", "unexpected_response", "legacy_unclassified",
})

LAYERS = frozenset({"local", "bridge", "extension", "page", "gateway", "mqtt", "node",
                    "device", "mcp", "provider"})

EVIDENCE_POLICIES = frozenset({"read", "local_commit", "read_after_write", "dispatch_only"})


class ActionResult(str):
    """Câu trả lời của tool kèm trạng thái, mã lý do và tầng xa nhất đã biết chắc."""

    def __new__(cls, render, *, name, status, reason, layer,
                side_effect_possible=False, request_id=None, legacy=False):
        if status not in STATUSES or reason not in REASONS or layer not in LAYERS:
            raise ValueError(f"ActionResult sai hợp đồng: {status}/{reason}/{layer}")
        result = super().__new__(cls, render)
        result.name = name
        result.status = status
        result.reason = reason
        result.layer = layer
        result.side_effect_possible = side_effect_possible
        result.request_id = request_id
        result.legacy = legacy
        return result

    @property
    def render(self):
        return str.__str__(self)

    @property
    def is_error(self):
        # Tool cũ chưa migration giữ đúng hành vi trước đây (D5): không bị đánh lỗi.
        return self.status in ERROR_STATUSES and not self.legacy

    def for_llm(self, content=None):
        """Nội dung gửi LLM: câu (đã bọc nếu là nội dung ngoài) + một dòng trạng thái.

        Dòng trạng thái nằm trong ToolResult chứ không trong system prompt, để prefix
        prompt không đổi và cache Gemini còn trúng. Tool cũ không có dòng này (D5).
        """
        content = self.render if content is None else content
        if self.legacy:
            return content
        return f"{content}\n[kết quả: {self.status}/{self.reason}]"


class RemoteError(Exception):
    """Lỗi từ hệ ngoài mà nơi ném biết rõ đã tới tầng nào và hậu quả ra sao.

    Ví dụ timeout sau khi gửi là `unknown` chứ không phải `failed`: thư có thể đã đi,
    báo thất bại dễ khiến người dùng gửi lại lần nữa.
    """

    def __init__(self, message, *, status="failed", reason="remote_error", layer="provider"):
        super().__init__(message)
        if status not in STATUSES or reason not in REASONS or layer not in LAYERS:
            raise ValueError(f"RemoteError sai hợp đồng: {status}/{reason}/{layer}")
        self.status, self.reason, self.layer = status, reason, layer
