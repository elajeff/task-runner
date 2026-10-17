"""Small adapters for supported LLM APIs.

Every adapter implements ``generate_json(prompt) -> str``. The runtime does
not depend on any provider-specific SDK types or response objects.
"""

from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


JSON_SYSTEM_PROMPT = (
    "Follow the instructions in the user message. Return exactly one valid JSON "
    "object, with no Markdown fences or text before or after it."
)


class ModelProvider(Protocol):
    """Interface required by the agent runtime's provider adapters."""

    def generate_json(self, prompt: str) -> str:
        """Return the model's JSON response as text."""


class GeminiProvider:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is missing. Add a key to .env from "
                "https://aistudio.google.com/apikey."
            )
        from google import genai
        from google.genai import types

        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=60_000),
        )
        self._model = _require_setting(model, "GEMINI_MODEL")
        self._types = types
        self._api_key = api_key

    def generate_json(self, prompt: str) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=f"{JSON_SYSTEM_PROMPT}\n\n{prompt}",
                config=self._types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                    max_output_tokens=2048,
                ),
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini request failed: {_safe_error_text(exc, self._api_key)}") from exc
        return _require_text(getattr(response, "text", None), "Gemini")


class OllamaProvider:
    """Call an Ollama server over its local HTTP API."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = _validate_base_url(base_url, "OLLAMA_BASE_URL")
        self._model = _require_setting(model, "OLLAMA_MODEL")

    def generate_json(self, prompt: str) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": JSON_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {"num_predict": 2048},
        }
        request = Request(
            f"{self._base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Ollama returned HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                "Could not reach Ollama. Check that it is running, the URL is correct, "
                "and the selected model is installed."
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama returned invalid JSON from its HTTP API.") from exc

        message = data.get("message", {})
        return _require_text(message.get("content"), "Ollama")


class OpenAIProvider:
    """Provider using OpenAI's official API and Python SDK."""

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is missing. Add your API key to .env.")
        self._model = _require_setting(model, "OPENAI_MODEL")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, timeout=60.0)
        self._api_key = api_key

    def generate_json(self, prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": JSON_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=2048,
            )
        except Exception as exc:
            raise RuntimeError(f"OpenAI request failed: {_safe_error_text(exc, self._api_key)}") from exc
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenAI returned an unexpected response shape.") from exc
        return _require_text(content, "OpenAI")


class AnthropicProvider:
    """Provider using Anthropic's native Messages API."""

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is missing. Add your API key to .env."
            )
        self._model = _require_setting(model, "ANTHROPIC_MODEL")
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key, timeout=60.0)
        self._api_key = api_key

    def generate_json(self, prompt: str) -> str:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                system=JSON_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise RuntimeError(f"Anthropic request failed: {_safe_error_text(exc, self._api_key)}") from exc

        text_blocks = [
            block.text
            for block in getattr(response, "content", [])
            if getattr(block, "type", None) == "text"
            and isinstance(getattr(block, "text", None), str)
        ]
        return _require_text("\n".join(text_blocks), "Anthropic")


class OpenAICompatibleProvider:
    """Use any service that implements the OpenAI-compatible chat endpoint.

    This covers services such as OpenRouter, LM Studio and many hosted/local
    inference servers. Set COMPAT_JSON_MODE=false if the chosen service does
    not implement the JSON response_format parameter.
    """

    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        model: str,
        json_mode: bool = True,
    ) -> None:
        self._base_url = _validate_base_url(base_url, "COMPAT_BASE_URL")
        self._model = _require_setting(model, "COMPAT_MODEL")
        if not api_key and not _is_loopback_url(self._base_url):
            raise ValueError(
                "COMPAT_API_KEY is required for a remote provider. For a local "
                "server without authentication, use a loopback URL such as localhost."
            )
        from openai import OpenAI

        # The OpenAI SDK requires a non-empty key even for local servers that do
        # not authenticate. This placeholder is sent only to the configured local URL.
        self._client = OpenAI(
            api_key=api_key or "local-provider-no-auth",
            base_url=self._base_url,
            timeout=60.0,
        )
        self._api_key = api_key or ""
        self._json_mode = json_mode

    def generate_json(self, prompt: str) -> str:
        arguments: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 2048,
            "messages": [
                {"role": "system", "content": JSON_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        if self._json_mode:
            arguments["response_format"] = {"type": "json_object"}
        try:
            response = self._client.chat.completions.create(**arguments)
        except Exception as exc:
            raise RuntimeError(
                "OpenAI-compatible provider request failed: "
                f"{_safe_error_text(exc, self._api_key)}"
            ) from exc
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "The OpenAI-compatible provider returned an unexpected response shape."
            ) from exc
        return _require_text(content, "OpenAI-compatible provider")


def create_provider(config: Any) -> ModelProvider:
    """Create the selected supported provider."""
    if config.provider == "gemini":
        return GeminiProvider(config.api_key or "", config.model)
    if config.provider == "ollama":
        return OllamaProvider(config.base_url or "http://localhost:11434", config.model)
    if config.provider == "openai":
        return OpenAIProvider(config.api_key or "", config.model)
    if config.provider == "anthropic":
        return AnthropicProvider(config.api_key or "", config.model)
    if config.provider == "openai_compatible":
        return OpenAICompatibleProvider(
            config.api_key,
            config.base_url or "",
            config.model,
            json_mode=config.json_mode,
        )
    raise ValueError(
        "Unsupported AGENT_PROVIDER. Choose gemini, ollama, openai, anthropic, or openai_compatible."
    )


def _safe_error_text(exc: Exception, api_key: str) -> str:
    """Avoid echoing the configured API key if an SDK exception includes it."""
    message = str(exc) or type(exc).__name__
    if api_key and len(api_key) >= 6:
        message = message.replace(api_key, "[redacted]")
    return message[:1000]


def _require_text(value: object, provider_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{provider_name} returned an empty response.")
    return value.strip()


def _require_setting(value: str | None, setting_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{setting_name} is missing. Configure it in .env.")
    return value.strip()


def _validate_base_url(value: str, setting_name: str) -> str:
    value = _require_setting(value, setting_name).rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{setting_name} must be a valid http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise ValueError(
            f"Do not place credentials in {setting_name}; use the corresponding API key setting."
        )
    if parsed.query or parsed.fragment:
        raise ValueError(
            f"{setting_name} must not contain a query string or fragment; use the API key setting for credentials."
        )
    return value


def _is_loopback_url(value: str) -> bool:
    host = (urlparse(value).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost")
