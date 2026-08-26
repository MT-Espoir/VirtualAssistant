"""
LLM provider Gemini + XOAY VÒNG MODEL cho free tier.
"""

import json
import re
import time
from collections import deque

from llm.client import AssistantTurn, Message, ToolCall
from utils.logger import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
# JSON Schema -> kiểu Schema của Gemini (enum viết HOA).
_TYPE_MAP = {"string": "STRING", "integer": "INTEGER", "number": "NUMBER",
             "boolean": "BOOLEAN", "object": "OBJECT", "array": "ARRAY", "null": "NULL"}


class GeminiRateLimit(Exception):
    """Model bị 429. scope='rpm' (tạm) | 'rpd' (hết ngày)."""
    def __init__(self, scope):
        super().__init__(f"Gemini rate limit ({scope})")
        self.scope = scope


class RateTracker:
    """Đếm lượt gọi để biết model còn khả dụng không. rpm/rpd <= 0 = không giới hạn."""

    def __init__(self, rpm, rpd):
        self.rpm = rpm
        self.rpd = rpd
        self._calls = deque()          # mốc thời gian các lượt gần đây (cho RPM)
        self._date = None              # ngày (chuỗi) của bộ đếm RPD hiện tại
        self._day = 0                  # số lượt trong ngày
        self._rpm_until = 0.0          # bị chặn RPM tới thời điểm này (phản ứng 429)
        self._rpd_blocked_date = None  # bị chặn RPD cho ngày này (phản ứng 429)

    @staticmethod
    def _today(now):
        return time.strftime("%Y-%m-%d", time.localtime(now))

    def _sync_day(self, now):
        today = self._today(now)
        if self._date != today:        # sang ngày mới -> reset bộ đếm ngày
            self._date, self._day = today, 0
        return today

    def available(self, now):
        while self._calls and now - self._calls[0] >= 60:   # bỏ lượt cũ hơn 60s
            self._calls.popleft()
        today = self._sync_day(now)
        if self._rpd_blocked_date == today:
            return False
        if now < self._rpm_until:
            return False
        rpm_ok = self.rpm <= 0 or len(self._calls) < self.rpm
        rpd_ok = self.rpd <= 0 or self._day < self.rpd
        return rpm_ok and rpd_ok

    def record(self, now):
        self._sync_day(now)
        self._calls.append(now)
        self._day += 1

    def block_rpm(self, now):
        self._rpm_until = now + 60

    def block_rpd(self, now):
        self._rpd_blocked_date = self._today(now)


# Trường Gemini function-declaration hiểu. CHỈ giữ các trường này -> tự bỏ
# additionalProperties/title/default/$defs/$schema... (schema MCP/pydantic có nhưng Gemini
# trả 400 "Unknown name 'additionalProperties'").
_GEMINI_SCHEMA_KEYS = {"type", "description", "properties", "items", "required",
                       "enum", "format", "nullable"}


def _convert_schema(node):
    """Chuyển JSON Schema -> Schema Gemini (đệ quy, viết HOA 'type'). Lọc bỏ trường lạ."""
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k not in _GEMINI_SCHEMA_KEYS:
            continue                                   # bỏ trường Gemini không chấp nhận
        if k == "type" and isinstance(v, str):
            out["type"] = _TYPE_MAP.get(v.lower(), v.upper())
        elif k == "properties" and isinstance(v, dict):
            out["properties"] = {pk: _convert_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out["items"] = _convert_schema(v)
        else:
            out[k] = v
    return out


def to_gemini_tools(tools):
    """specs tool ({name,description,input_schema}) -> function_declarations của Gemini.

    Tool không có 'properties' (vd chụp màn hình) -> khai báo KHÔNG parameters (no-arg).
    """
    if not tools:
        return None
    decls = []
    for t in tools:
        decl = {"name": t["name"], "description": t.get("description", "")}
        props = (t.get("input_schema") or {}).get("properties") or {}
        if props:
            decl["parameters"] = _convert_schema(t["input_schema"])
        decls.append(decl)
    return [{"function_declarations": decls}]


def to_gemini_contents(messages):
    """Message trung lập -> 'contents' Gemini (role: user|model; tool = functionCall/Response)."""
    contents = []
    for m in messages:
        if m.role == "assistant":
            parts = []
            if m.text:
                parts.append({"text": m.text})
            for tc in m.tool_calls:
                part = {"functionCall": {"name": tc.name, "args": tc.arguments or {}}}
                if getattr(tc, "thought_signature", None):
                    part["thoughtSignature"] = tc.thought_signature   # Gemini 3.x bắt buộc
                parts.append(part)
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
        elif m.tool_results:
            parts = [{"functionResponse": {"name": r.name, "response": {"result": r.content}}}
                     for r in m.tool_results]
            contents.append({"role": "user", "parts": parts})
        else:
            contents.append({"role": "user", "parts": [{"text": m.text}]})
    return contents


class GeminiModelClient:
    """Gọi generateContent cho MỘT model Gemini. Ném GeminiRateLimit khi 429."""

    def __init__(self, model, api_key, http_post=None, timeout=60, max_tokens=1024):
        self.model = model
        self.api_key = api_key
        self.url = f"{_BASE_URL}/{model}:generateContent"
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._http_post = http_post

    def _post(self, payload):
        if self._http_post is not None:
            return self._http_post(self.url, payload)
        import requests
        return requests.post(self.url, json=payload, timeout=self.timeout,
                             headers={"x-goog-api-key": self.api_key,
                                      "Content-Type": "application/json"})

    def generate(self, *, system, messages, tools):
        payload = {
            "contents": to_gemini_contents(messages),
            "generationConfig": {"maxOutputTokens": self.max_tokens},
        }
        if system:
            payload["system_instruction"] = {"parts": [{"text": system}]}
        gtools = to_gemini_tools(tools)
        if gtools:
            payload["tools"] = gtools

        resp = self._post(payload)
        status = getattr(resp, "status_code", 200)
        try:
            data = resp.json()
        except Exception:
            data = {}

        if status == 429:
            body = json.dumps(data)
            scope = "rpd" if re.search(r"per\s*day|daily|PerDay", body, re.I) else "rpm"
            raise GeminiRateLimit(scope)
        if status >= 400:
            raise RuntimeError(f"Gemini lỗi {status}: {json.dumps(data)[:200]}")

        _log_cache_usage(self.model, data.get("usageMetadata") or {})

        candidates = data.get("candidates") or []
        if not candidates:
            return AssistantTurn(text="", tool_calls=[])
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text_parts, tool_calls = [], []
        for i, p in enumerate(parts):
            if "text" in p:
                text_parts.append(p["text"])
            elif "functionCall" in p:
                fc = p["functionCall"]
                tool_calls.append(ToolCall(id=f"call_{i}", name=fc.get("name", ""),
                                           arguments=dict(fc.get("args") or {}),
                                           thought_signature=p.get("thoughtSignature")))
        return AssistantTurn(text="".join(text_parts), tool_calls=tool_calls)


def _log_cache_usage(model, usage):
    """Ghi lại tỉ lệ token ĐƯỢC CACHE mỗi lượt gọi.

    Gemini bật cache NGẦM ĐỊNH sẵn cho model 2.5 trở lên — không phải khai gì, và token
    trúng cache được giảm 90%. Điều kiện: request phải có TIỀN TỐ CHUNG với request trước,
    và phải dài hơn ngưỡng tối thiểu (Gemini 3.x: 4.096 token).

    Đo 2026-08-26: 99,97% payload mỗi lượt của hệ này giống hệt nhau từng byte, và mỗi
    call ~9.618 token — tức đủ điều kiện. Nhưng TRƯỚC ĐÂY KHÔNG AI ĐO, nên không biết
    thực tế có trúng hay không. Dòng log này biến câu hỏi đó thành quan sát được.

    Đáng chú ý cho mọi thay đổi tương lai: thu hẹp payload (vd bật router) có thể đẩy
    request xuống DƯỚI ngưỡng và mất sạch cache — nhỏ hơn chưa chắc rẻ hơn.
    Xem `docs/router_local_classifier_spec.md` §6b.
    """
    tong = usage.get("promptTokenCount")
    if not tong:
        return
    cache = usage.get("cachedContentTokenCount", 0)
    logger.info("💾 %s: %d token vào, %d trúng cache (%.0f%%)",
                model, tong, cache, 100 * cache / tong)


class RotatingGeminiClient:
    """Hiện thực LLMClient: chọn model khả dụng đầu tiên; xoay khi hết lượt/lỗi."""

    def __init__(self, api_key, model_specs, http_post=None, timeout=60,
                 max_tokens=1024, now=time.time):
        self._now = now
        self._entries = [
            (GeminiModelClient(name, api_key, http_post, timeout, max_tokens),
             RateTracker(rpm, rpd))
            for name, rpm, rpd in model_specs
        ]

    def generate(self, *, system, messages, tools):
        now = self._now()
        last_err = None
        for client, tracker in self._entries:
            if not tracker.available(now):
                continue
            try:
                turn = client.generate(system=system, messages=messages, tools=tools)
                tracker.record(now)
                logger.info("🔮 Gemini: dùng model %s", client.model)
                return turn
            except GeminiRateLimit as e:
                tracker.block_rpd(now) if e.scope == "rpd" else tracker.block_rpm(now)
                logger.warning("Gemini %s hết lượt (%s) — xoay sang model khác.",
                               client.model, e.scope)
                last_err = e
            except Exception as e:   # lỗi khác: thử model kế, giữ lỗi cuối
                logger.error("Gemini %s lỗi: %s — thử model khác.", client.model, e)
                last_err = e
        raise RuntimeError(f"Tất cả model Gemini đều hết lượt hoặc lỗi (gần nhất: {last_err}).")


def parse_model_specs(spec):
    """'name:rpm:rpd,name:rpm:rpd,...' -> [(name, rpm, rpd)]. rpm/rpd thiếu = 0 (không giới hạn)."""
    out = []
    for part in (spec or "").split(","):
        bits = [b.strip() for b in part.split(":")]
        name = bits[0] if bits else ""
        if not name:
            continue
        rpm = int(bits[1]) if len(bits) > 1 and bits[1] else 0
        rpd = int(bits[2]) if len(bits) > 2 and bits[2] else 0
        out.append((name, rpm, rpd))
    return out


def build_rotating_gemini(config):
    """Dựng RotatingGeminiClient từ config. Ném RuntimeError nếu thiếu key/model."""
    if not config.GEMINI_API_KEY:
        raise RuntimeError("Chưa đặt GEMINI_API_KEY trong src/.env.")
    specs = parse_model_specs(config.GEMINI_MODELS)
    if not specs:
        raise RuntimeError("GEMINI_MODELS trống hoặc không hợp lệ.")
    return RotatingGeminiClient(config.GEMINI_API_KEY, specs,
                                timeout=config.LLM_TIMEOUT, max_tokens=config.LLM_MAX_TOKENS)
