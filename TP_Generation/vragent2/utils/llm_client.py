"""
LLM Client — Unified interface for calling OpenAI-compatible LLM APIs.

Extracted and refactored from GenerateTestPlanModified._call_llm_api().
Supports:
    - Single-turn and multi-turn conversations
    - Configurable model, temperature, retries
    - Response parsing (JSON extraction, think-tag stripping)

Implementation uses Python stdlib ``urllib`` to call the OpenAI-compatible
REST endpoint directly, avoiding the ``openai``, ``httpx``, and ``requests``
packages.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

# Regex to strip <think>...</think> blocks (some reasoning models emit these)
_THINK_RE = re.compile(r"<\s*think\s*>.*?<\s*/\s*think\s*>", re.IGNORECASE | re.DOTALL)

# Local proxy for API access
_PROXY_URL = "http://127.0.0.1:15236"


class LLMClient:
    """Thin wrapper around the OpenAI-compatible chat-completions REST API."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str = "gpt-4o",
        default_temperature: float = 0.0,
        max_retries: int = 5,
        retry_delay: float = 30.0,
        proxy_url: str = _PROXY_URL,
    ):
        self.default_model = default_model
        self.default_temperature = default_temperature
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Normalise base_url: strip trailing slash, auto-append /v1 if bare domain
        from urllib.parse import urlparse as _urlparse
        _raw = (base_url or "").rstrip("/")
        _parsed = _urlparse(_raw)
        if _parsed.path in ("", "/"):
            # Bare domain like https://api.vectorengine.cn — auto-add /v1
            self._base_url = _raw + "/v1"
            print(f"[LLM] Auto-added /v1 to base URL: {_raw} -> {self._base_url}")
        else:
            self._base_url = _raw
        self._endpoint = self._base_url + "/chat/completions"
        print(f"[LLM] Endpoint: {self._endpoint}")

        # Token usage accumulator: {caller: {prompt_tokens, completion_tokens, total_tokens, calls}}
        self._token_usage: Dict[str, Dict[str, int]] = {}

        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if proxy_url:
            proxy_handler = urllib_request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            self._opener = urllib_request.build_opener(proxy_handler)
        else:
            self._opener = urllib_request.build_opener()

    # ------------------------------------------------------------------
    # Core API call
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_retries: Optional[int] = None,
        caller: Optional[str] = None,
    ) -> Optional[str]:
        """
        Send *messages* to the LLM and return the assistant reply as a string.

        *caller* is an optional tag (e.g. ``"planner"``, ``"verifier"``) used
        to attribute token usage.  Returns ``None`` on total failure after retries.
        """
        model = model or self.default_model
        temperature = temperature if temperature is not None else self.default_temperature
        retries = max_retries if max_retries is not None else self.max_retries

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        for attempt in range(1, retries + 1):
            response_status = None
            response_text = ""
            response_headers: Dict[str, str] = {}
            error: Optional[Exception] = None
            try:
                request = urllib_request.Request(
                    self._endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=self._headers,
                    method="POST",
                )
                with self._opener.open(request, timeout=120) as response:
                    response_status = response.getcode()
                    response_headers = dict(response.headers.items())
                    response_text = response.read().decode("utf-8", errors="replace")

                data = json.loads(response_text)

                # Accumulate token usage
                self._accumulate_usage(data, caller or model)

                choices = data.get("choices") or []
                if choices:
                    return choices[0].get("message", {}).get("content")
                print("[LLM] Empty response from API")
                return None
            except urllib_error.HTTPError as exc:
                response_status = exc.code
                response_headers = dict(exc.headers.items()) if exc.headers else {}
                response_text = exc.read().decode("utf-8", errors="replace")
                error = exc
            except Exception as exc:
                error = exc

            if error is not None:
                # Show HTTP status + response body snippet to aid debugging
                if response_status is not None:
                    _snippet = response_text[:300].replace("\n", " ")
                    print(f"[LLM] Attempt {attempt}/{retries} failed (HTTP {response_status}): {error} | body: {_snippet}")
                    # If server returned HTML, this is a config error (wrong endpoint),
                    # not a rate limit — no point waiting the full retry_delay
                    content_type = response_headers.get("Content-Type", "")
                    is_html = "text/html" in content_type or response_text.lstrip().startswith("<!DOCTYPE")
                    if is_html:
                        print("[LLM] Response is HTML — likely wrong endpoint. Check API Base URL.")
                        # Short delay only; no benefit to 30s wait
                        wait = min(self.retry_delay, 3.0)
                    else:
                        wait = self.retry_delay
                else:
                    print(f"[LLM] Attempt {attempt}/{retries} failed: {error}")
                    wait = self.retry_delay
                if attempt < retries:
                    time.sleep(wait)
        print("[LLM] All retries exhausted")
        return None

    # ------------------------------------------------------------------
    # Token usage tracking
    # ------------------------------------------------------------------

    def _accumulate_usage(self, data: Any, caller: str) -> None:
        """Extract token counts from the API response dict and accumulate."""
        usage = data.get("usage") if isinstance(data, dict) else None
        if not usage:
            return
        bucket = self._token_usage.setdefault(caller, {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0,
        })
        bucket["prompt_tokens"] += usage.get("prompt_tokens", 0) or 0
        bucket["completion_tokens"] += usage.get("completion_tokens", 0) or 0
        bucket["total_tokens"] += usage.get("total_tokens", 0) or 0
        bucket["calls"] += 1

    def get_token_usage(self) -> Dict[str, Dict[str, int]]:
        """Return accumulated token usage by caller, plus an ``_total`` key."""
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
        for v in self._token_usage.values():
            for k in totals:
                totals[k] += v[k]
        result = dict(self._token_usage)
        result["_total"] = totals
        return result

    def reset_token_usage(self) -> None:
        """Clear accumulated stats (e.g. between iterations)."""
        self._token_usage.clear()

    # ------------------------------------------------------------------
    # Convenience: single-turn
    # ------------------------------------------------------------------

    def ask(self, prompt: str, **kwargs) -> Optional[str]:
        """Single-turn user→assistant call."""
        return self.chat([{"role": "user", "content": prompt}], **kwargs)


    # ------------------------------------------------------------------
    # Convenience: multi-turn with context management
    # ------------------------------------------------------------------

    def ask_with_context(
        self,
        prompt: str,
        context: List[Dict[str, str]],
        **kwargs,
    ) -> Optional[str]:
        """Append *prompt* to *context*, call LLM, and return the reply.

        *context* is **mutated** in-place (user + assistant messages appended).
        """
        context.append({"role": "user", "content": prompt})
        reply = self.chat(context, **kwargs)
        if reply:
            context.append({"role": "assistant", "content": reply})
        return reply

    # ------------------------------------------------------------------
    # Response parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def strip_think_tags(text: str) -> str:
        """Remove ``<think>…</think>`` blocks."""
        return _THINK_RE.sub("", text).strip()

    @staticmethod
    def extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Try to pull a JSON object out of a fenced code block or raw text."""
        text = LLMClient.strip_think_tags(text)

        # Try ```json ... ``` first
        m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # Fallback: find first { … }
        start = text.find("{")
        if start != -1:
            brace = 0
            for i, ch in enumerate(text[start:], start):
                if ch == "{":
                    brace += 1
                elif ch == "}":
                    brace -= 1
                    if brace == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break
        return None

    @staticmethod
    def extract_test_plan(text: str) -> Optional[Dict[str, Any]]:
        """Extract a test-plan JSON (must contain ``taskUnits``) from LLM output."""
        parsed = LLMClient.extract_json(text)
        if parsed and "taskUnits" in parsed:
            return parsed
        # Last resort: check raw text
        if text and "taskUnits" in text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        return None
