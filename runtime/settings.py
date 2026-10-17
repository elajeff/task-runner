"""Read and save the local provider settings used by the desktop interface."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, set_key

from runtime.config import DEFAULT_MODELS


PROVIDER_SETTINGS: dict[str, dict[str, Any]] = {
    "gemini": {
        "label": "Google Gemini",
        "model_key": "GEMINI_MODEL",
        "model_default": DEFAULT_MODELS["gemini"],
        "api_key_key": "GEMINI_API_KEY",
        "base_url_key": None,
        "base_url_default": "",
        "json_mode_key": None,
    },
    "openai": {
        "label": "OpenAI",
        "model_key": "OPENAI_MODEL",
        "model_default": DEFAULT_MODELS["openai"],
        "api_key_key": "OPENAI_API_KEY",
        "base_url_key": None,
        "base_url_default": "",
        "json_mode_key": None,
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "model_key": "ANTHROPIC_MODEL",
        "model_default": DEFAULT_MODELS["anthropic"],
        "api_key_key": "ANTHROPIC_API_KEY",
        "base_url_key": None,
        "base_url_default": "",
        "json_mode_key": None,
    },
    "ollama": {
        "label": "Ollama (local model)",
        "model_key": "OLLAMA_MODEL",
        "model_default": DEFAULT_MODELS["ollama"],
        "api_key_key": None,
        "base_url_key": "OLLAMA_BASE_URL",
        "base_url_default": "http://localhost:11434",
        "json_mode_key": None,
    },
    "openai_compatible": {
        "label": "OpenAI-compatible API",
        "model_key": "COMPAT_MODEL",
        "model_default": DEFAULT_MODELS["openai_compatible"],
        "api_key_key": "COMPAT_API_KEY",
        "base_url_key": "COMPAT_BASE_URL",
        "base_url_default": "http://localhost:1234/v1",
        "json_mode_key": "COMPAT_JSON_MODE",
    },
}


def load_provider_settings(env_path: Path, provider: str) -> dict[str, str | bool]:
    """Load one provider's settings from .env, using sensible local defaults."""
    if provider not in PROVIDER_SETTINGS:
        raise ValueError(f"Unsupported provider: {provider}")

    metadata = PROVIDER_SETTINGS[provider]
    values = dotenv_values(env_path) if env_path.exists() else {}

    def get(key: str | None, default: str = "") -> str:
        if not key:
            return default
        # Inherited environment variables follow standard dotenv precedence.
        current = os.environ.get(key)
        stored = values.get(key)
        return str(current if current is not None else (stored if stored is not None else default))

    json_key = metadata["json_mode_key"]
    return {
        "provider": provider,
        "model": get(metadata["model_key"], metadata["model_default"]),
        "api_key": get(metadata["api_key_key"]),
        "base_url": get(metadata["base_url_key"], metadata["base_url_default"]),
        "json_mode": get(json_key, "true").strip().lower() not in {"false", "0", "no", "off"},
    }


def save_provider_settings(
    env_path: Path, provider: str, settings: dict[str, str | bool]
) -> None:
    """Save provider settings locally and update this process for immediate use.

    Credentials are stored in the local .env file, outside a packaged app's
    executable directory. Source installs keep that file in the project folder.
    """
    if provider not in PROVIDER_SETTINGS:
        raise ValueError(f"Unsupported provider: {provider}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = PROVIDER_SETTINGS[provider]
    values_to_save: dict[str, str] = {"AGENT_PROVIDER": provider}
    values_to_save[metadata["model_key"]] = str(settings.get("model", "")).strip()

    for field, key in (
        ("api_key", metadata["api_key_key"]),
        ("base_url", metadata["base_url_key"]),
    ):
        if key:
            values_to_save[key] = str(settings.get(field, "")).strip()

    json_key = metadata["json_mode_key"]
    if json_key:
        values_to_save[json_key] = "true" if settings.get("json_mode", True) else "false"

    for key, value in values_to_save.items():
        set_key(str(env_path), key, value, quote_mode="always")
        os.environ[key] = value


def save_workspace_path(env_path: Path, workspace: Path, data_root: Path) -> None:
    """Save the agent's working folder relative to its default data directory."""
    env_path = Path(env_path)
    data_root = Path(data_root).expanduser().resolve()
    workspace = Path(workspace).expanduser().resolve()
    default_workspace = (data_root / "workspace").resolve()
    stored_path = "workspace" if workspace == default_workspace else str(workspace)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    set_key(str(env_path), "AGENT_WORKSPACE", stored_path, quote_mode="always")
    os.environ["AGENT_WORKSPACE"] = stored_path
