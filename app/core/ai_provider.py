import json
import re
import time
import httpx
from app.core.config import settings

class ProviderError(RuntimeError):
    def __init__(self, code="ai_unavailable", *, output=None, details=None):
        self.code = code
        self.output = output
        self.details = details or []
        super().__init__(code)


def parse_output(content):
    """Accept JSON and a single Markdown JSON fence, without guessing missing data."""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content
                          if isinstance(part, dict) and part.get("type") == "text")
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("ai_invalid_output", details=[{"field": "$", "type": "empty_content"}])
    cleaned = content.strip().lstrip("\ufeff")
    fence = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        result = json.loads(cleaned)
    except ValueError as exc:
        raise ProviderError("ai_invalid_output", output=content[:50000],
                            details=[{"field": "$", "type": "invalid_json"}]) from exc
    if not isinstance(result, dict):
        raise ProviderError("ai_invalid_output", output=content[:50000],
                            details=[{"field": "$", "type": "object_required"}])
    return result


class ChatProvider:
    def _request(self, messages, model=None):
        model = model or settings.ai_text_model or settings.ai_vision_model
        if not settings.ai_api_key or not model:
            raise ProviderError("ai_not_configured")
        payload = {"model": model, "messages": messages,
                   "response_format": {"type": "json_object"}, "temperature": 0.2, "stream": False}
        for attempt in range(3):
            try:
                with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
                    response = client.post(settings.ai_base_url.rstrip("/") + "/chat/completions",
                                           headers={"Authorization": "Bearer " + settings.ai_api_key},
                                           json=payload)
                if response.status_code in {408, 429} or response.status_code >= 500:
                    if attempt < 2:
                        time.sleep(attempt + 1)
                        continue
                    raise ProviderError("ai_unavailable")
                if response.is_error:
                    raise ProviderError("ai_request_rejected")
                choice = response.json()["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise ProviderError("ai_output_truncated", details=[{"field": "$", "type": "output_truncated"}])
                return parse_output(choice["message"]["content"])
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise ProviderError("ai_unavailable") from exc
                time.sleep(attempt + 1)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ProviderError("ai_invalid_output", details=[{"field": "$response", "type": type(exc).__name__}]) from exc

