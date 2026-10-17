"""Provider configuration and adapters are tested without network/API usage."""

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import runtime.config as config_module
import runtime.providers as provider_module
from runtime.config import Config
from runtime.providers import (
    AnthropicProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    OllamaProvider,
    create_provider,
)


PROVIDER_ENV_NAMES = [
    "AGENT_PROVIDER",
    "GEMINI_API_KEY", "GEMINI_MODEL",
    "OPENAI_API_KEY", "OPENAI_MODEL",
    "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "OLLAMA_BASE_URL", "OLLAMA_MODEL",
    "COMPAT_BASE_URL", "COMPAT_API_KEY", "COMPAT_MODEL", "COMPAT_JSON_MODE",
    "AGENT_WORKSPACE", "AGENT_DATABASE", "AGENT_MAX_STEPS",
]


def isolate_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)
    for name in PROVIDER_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_gemini_is_default_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    isolate_config(monkeypatch, tmp_path)
    config = Config.from_environment()
    assert config.provider == "gemini"
    assert config.model == "gemini-3.8-flash"
    assert config.api_key is None


def test_config_supports_native_openai(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = Config.from_environment()
    assert config.provider == "openai"
    assert config.model == "gpt-5.6-sol"
    assert config.api_key == "test-key"


def test_config_supports_native_anthropic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    config = Config.from_environment()
    assert config.provider == "anthropic"
    assert config.model == "claude-sonnet-5"


def test_config_supports_ollama(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_PROVIDER", "ollama")
    config = Config.from_environment()
    assert config.base_url == "http://localhost:11434"
    assert config.model == "qwen3:4b"
    assert config.api_key is None


def test_config_supports_openai_compatible_and_json_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("COMPAT_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("COMPAT_MODEL", "local-model")
    monkeypatch.setenv("COMPAT_JSON_MODE", "false")
    config = Config.from_environment()
    assert config.json_mode is False
    assert config.model == "local-model"


def test_config_rejects_invalid_boolean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("COMPAT_JSON_MODE", "sometimes")
    with pytest.raises(ValueError, match="COMPAT_JSON_MODE must be true or false"):
        Config.from_environment()


def test_openai_adapter_uses_json_mode(monkeypatch: pytest.MonkeyPatch):
    captured = {}
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"finish"}'))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: captured.update(kwargs) or fake_response)
        )
    )
    fake_module = ModuleType("openai")
    fake_module.OpenAI = lambda **kwargs: fake_client
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    provider = OpenAIProvider("secret-test-key", "test-model")
    assert provider.generate_json("Return an action") == '{"action":"finish"}'
    assert captured["model"] == "test-model"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["max_completion_tokens"] == 2048


def test_anthropic_adapter_joins_text_blocks(monkeypatch: pytest.MonkeyPatch):
    captured = {}
    response = SimpleNamespace(content=[
        SimpleNamespace(type="text", text='{"action":'),
        SimpleNamespace(type="tool_use", text=None),
        SimpleNamespace(type="text", text='"finish"}')
    ])
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kwargs: captured.update(kwargs) or response)
    )
    fake_module = ModuleType("anthropic")
    fake_module.Anthropic = lambda **kwargs: fake_client
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    provider = AnthropicProvider("secret-test-key", "test-model")
    assert provider.generate_json("Return an action") == '{"action":\n"finish"}'
    assert captured["model"] == "test-model"
    assert captured["max_tokens"] == 2048
    assert captured["system"]


def test_openai_compatible_supports_local_server_without_key(monkeypatch: pytest.MonkeyPatch):
    captured = {}
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"finish"}'))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: captured.update(kwargs) or response)
        )
    )
    fake_module = ModuleType("openai")
    fake_module.OpenAI = lambda **kwargs: fake_client
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    provider = OpenAICompatibleProvider(None, "http://localhost:1234/v1", "local-model", json_mode=False)
    assert provider.generate_json("Return an action") == '{"action":"finish"}'
    assert "response_format" not in captured
    assert captured["max_tokens"] == 2048


def test_openai_compatible_requires_key_for_remote_server():
    with pytest.raises(ValueError, match="COMPAT_API_KEY is required for a remote provider"):
        OpenAICompatibleProvider(None, "https://api.example.test/v1", "model")


def test_ollama_adapter_sends_json_request(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"message":{"content":"{\\\"action\\\":\\\"finish\\\"}"}}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(provider_module, "urlopen", fake_urlopen)
    provider = OllamaProvider("http://localhost:11434/", "test-model")
    result = provider.generate_json("Return an action")
    assert result == '{"action":"finish"}'
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["payload"]["format"] == "json"


def test_unsupported_provider_has_actionable_message():
    config = SimpleNamespace(provider="unknown")
    with pytest.raises(ValueError, match="openai_compatible"):
        create_provider(config)


def test_factory_selects_dedicated_openai_and_anthropic_adapters(monkeypatch: pytest.MonkeyPatch):
    made = []

    class MarkerProvider:
        def generate_json(self, prompt: str) -> str:
            return '{"action":"finish"}'

    def factory(name):
        def create(api_key, model):
            made.append((name, api_key, model))
            return MarkerProvider()
        return create

    monkeypatch.setattr(provider_module, "OpenAIProvider", factory("openai"))
    monkeypatch.setattr(provider_module, "AnthropicProvider", factory("anthropic"))

    for name in ("openai", "anthropic"):
        config = SimpleNamespace(provider=name, api_key="test-key", model="test-model")
        assert isinstance(create_provider(config), MarkerProvider)

    assert made == [
        ("openai", "test-key", "test-model"),
        ("anthropic", "test-key", "test-model"),
    ]


def test_gemini_adapter_sets_timeout_and_output_limit(monkeypatch: pytest.MonkeyPatch):
    captured = {"client": {}, "request": {}}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"].update(kwargs)
            self.models = self

        def generate_content(self, **kwargs):
            captured["request"].update(kwargs)
            return SimpleNamespace(text='{"action":"finish","response":"ok"}')

    class FakeTypes:
        @staticmethod
        def HttpOptions(**kwargs):
            return kwargs

        @staticmethod
        def GenerateContentConfig(**kwargs):
            return kwargs

    genai_module = ModuleType("google.genai")
    genai_module.Client = FakeClient
    types_module = ModuleType("google.genai.types")
    types_module.HttpOptions = FakeTypes.HttpOptions
    types_module.GenerateContentConfig = FakeTypes.GenerateContentConfig
    google_module = ModuleType("google")
    google_module.genai = genai_module
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)

    provider = provider_module.GeminiProvider("secret-test-key", "test-model")
    result = provider.generate_json("Return one JSON object")
    assert json.loads(result)["response"] == "ok"
    assert captured["client"]["http_options"]["timeout"] == 60_000
    assert captured["request"]["config"]["max_output_tokens"] == 2048


def test_provider_error_text_redacts_api_key():
    assert provider_module._safe_error_text(
        RuntimeError("failed with secret-test-key"), "secret-test-key"
    ) == "failed with [redacted]"


def test_base_url_rejects_query_tokens_and_url_credentials():
    for url in (
        "https://api.example.test/v1?token=secret",
        "https://user:password@api.example.test/v1",
        "https://api.example.test/v1#token",
    ):
        with pytest.raises(ValueError, match="credentials|query string or fragment"):
            OpenAICompatibleProvider("api-key", url, "model")


@pytest.mark.parametrize("value", ["0", "-1", "51", "many", ""])
def test_config_rejects_invalid_step_limits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str):
    isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_MAX_STEPS", value)
    with pytest.raises(ValueError, match="AGENT_MAX_STEPS"):
        Config.from_environment()
