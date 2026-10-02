"""Text-only camera return greetings, with admission before each provider call."""

import hashlib
import threading
import time
import uuid
from collections import deque

from features.camera.call_budget import CameraCallBudget
from features.salm.welcome import WelcomeDialogue


def build_camera_welcome_client(settings):
    """A dedicated single-model client: no model rotation or automatic retries."""
    provider = (settings.LLM_PROVIDER or "ollama").strip().lower()
    model = (settings.CAMERA_WELCOME_LLM_MODEL or "").strip()
    tokens = max(128, min(512, settings.CAMERA_WELCOME_LLM_MAX_TOKENS))
    timeout = max(0.5, min(10.0, settings.CAMERA_WELCOME_LLM_TIMEOUT_SECONDS))
    if provider == "gemini":
        from llm.gemini import GeminiModelClient, parse_model_specs
        if not settings.GEMINI_API_KEY:
            raise ValueError("missing_api_key")
        if not model:
            specs = parse_model_specs(settings.GEMINI_MODELS)
            if not specs:
                raise ValueError("missing_model")
            model = specs[0][0]

        def post(url, payload):
            import requests
            return requests.post(
                url, json=payload, timeout=timeout, allow_redirects=False,
                headers={"x-goog-api-key": settings.GEMINI_API_KEY,
                         "Content-Type": "application/json"})

        return GeminiModelClient(model, settings.GEMINI_API_KEY, http_post=post,
                                 timeout=timeout, max_tokens=tokens, log_usage=False)
    if provider == "claude":
        from llm.client import ClaudeClient
        return ClaudeClient(model=model or settings.LLM_MODEL, max_tokens=tokens,
                            timeout=timeout, max_retries=0)
    if provider == "ollama":
        from llm.client import OllamaLLMClient

        def post(url, payload):
            import requests
            payload = dict(payload, options={"num_predict": tokens})
            response = requests.post(url, json=payload, timeout=timeout,
                                     allow_redirects=False)
            response.raise_for_status()
            return response

        return OllamaLLMClient(model=model or settings.OLLAMA_MODEL,
                               base_url=settings.OLLAMA_URL, http_post=post,
                               timeout=timeout)
    raise ValueError("unsupported_provider")


class CameraReturnWelcome:
    def __init__(self, llm, budget_path, timeout_seconds=5,
                 min_interval_seconds=900, max_per_hour=3, max_per_day=12,
                 address_form_provider=None, persona_context_provider=None,
                 proactive_text_provider=None, debug=None):
        self.debug = debug
        self._session_id = uuid.uuid4().hex
        self._lock = threading.Lock()
        self._seen = deque(maxlen=256)
        self.budget = CameraCallBudget(
            budget_path, min_interval_seconds, max_per_hour, max_per_day)
        self.dialogue = WelcomeDialogue(
            llm, timeout_seconds=max(0.5, min(10.0, timeout_seconds)),
            address_form_provider=address_form_provider,
            persona_context_provider=persona_context_provider,
            proactive_text_provider=proactive_text_provider,
            status_sink=self._log)

    def _log(self, message, data=None, level="INFO"):
        if self.debug is not None:
            try:
                self.debug("camera", message, data or {}, level=level)
            except Exception:
                pass  # Diagnostics must not turn a denied call into an action.

    def generate(self, request, is_allowed):
        if request.source != "camera" or not is_allowed():
            return None
        episode = request.absence_episode_id
        with self._lock:
            if episode in self._seen:
                self._log("Camera welcome duplicate dropped")
                return None
            self._seen.append(episode)
        attempt_key = hashlib.sha256(
            f"{self._session_id}:{episode}".encode("utf-8")).hexdigest()
        if self.dialogue.llm is None:
            self._log("Camera welcome using local fallback", {"reason": "llm_unavailable"})

        def before_call(*, system, messages, tools):
            if (not isinstance(system, str) or len(system) > 6000 or tools or
                    len(messages) != 1 or messages[0].role != "user" or
                    not isinstance(messages[0].text, str) or len(messages[0].text) > 500 or
                    messages[0].tool_calls or messages[0].tool_results):
                self._log("Camera welcome LLM blocked", {"reason": "payload_limit"})
                return False
            if not is_allowed():
                self._log("Camera welcome LLM blocked", {"reason": "stale_or_cancelled"})
                return False
            if not 0 <= time.monotonic() - request.observed_monotonic <= max(
                    0.0, 10.0 - self.dialogue.timeout_seconds):
                self._log("Camera welcome LLM blocked", {"reason": "insufficient_deadline"})
                return False
            accepted, usage = self.budget.reserve(attempt_key)
            self._log("Camera welcome LLM attempt reserved" if accepted else
                      "Camera welcome LLM blocked", usage)
            # A cancellation racing with the commit consumes the slot conservatively.
            return accepted and is_allowed()

        return self.dialogue.generate("return", before_call=before_call)
