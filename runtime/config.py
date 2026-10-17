"""Read provider and runtime settings from environment variables and .env."""

from dataclasses import dataclass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-5.6-sol",
    "anthropic": "claude-sonnet-5",
    "ollama": "qwen3:4b",
    "openai_compatible": "",
}


def app_data_root() -> Path:
    """Return writable app data, migrating files from the previous app name once."""
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        current = base / "task-runner"
        legacy_paths = (base / "Task-Runner", base / "TaskRunner")
        if not current.exists():
            for legacy in legacy_paths:
                if legacy.is_dir():
                    try:
                        legacy.rename(current)
                    except OSError:
                        # Keep using existing data if Windows has a lock or permission issue.
                        return legacy.resolve()
                    break
        return current.resolve()
    return PROJECT_ROOT


def env_file_path() -> Path:
    return app_data_root() / ".env"


@dataclass(frozen=True)
class Config:
    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    workspace: Path
    database: Path
    max_steps: int
    json_mode: bool = True

    @classmethod
    def from_environment(cls) -> "Config":
        data_root = app_data_root()
        load_dotenv(data_root / ".env")

        provider = os.getenv("AGENT_PROVIDER", "gemini").strip().lower()
        json_mode = (
            _read_bool("COMPAT_JSON_MODE", default=True)
            if provider == "openai_compatible"
            else True
        )

        if provider == "gemini":
            model = os.getenv("GEMINI_MODEL", DEFAULT_MODELS["gemini"]).strip()
            api_key = os.getenv("GEMINI_API_KEY")
            base_url = None
        elif provider == "ollama":
            model = os.getenv("OLLAMA_MODEL", DEFAULT_MODELS["ollama"]).strip()
            api_key = None
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
        elif provider == "openai":
            model = os.getenv("OPENAI_MODEL", DEFAULT_MODELS["openai"]).strip()
            api_key = os.getenv("OPENAI_API_KEY")
            base_url = None
        elif provider == "anthropic":
            model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODELS["anthropic"]).strip()
            api_key = os.getenv("ANTHROPIC_API_KEY")
            base_url = None
        elif provider == "openai_compatible":
            model = os.getenv("COMPAT_MODEL", DEFAULT_MODELS["openai_compatible"]).strip()
            api_key = os.getenv("COMPAT_API_KEY") or None
            base_url = os.getenv("COMPAT_BASE_URL", "http://localhost:1234/v1").strip()
        else:
            raise ValueError(
                "AGENT_PROVIDER must be gemini, ollama, openai, anthropic, or openai_compatible."
            )

        workspace = _project_path(os.getenv("AGENT_WORKSPACE", "workspace"), data_root)
        database = _project_path(os.getenv("AGENT_DATABASE", "data/runtime.db"), data_root)
        try:
            max_steps = int(os.getenv("AGENT_MAX_STEPS", "8"))
        except ValueError as exc:
            raise ValueError("AGENT_MAX_STEPS must be a whole number between 1 and 50.") from exc
        if max_steps < 1 or max_steps > 50:
            raise ValueError("AGENT_MAX_STEPS must be between 1 and 50.")

        return cls(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            workspace=workspace,
            database=database,
            max_steps=max_steps,
            json_mode=json_mode,
        )


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false.")


def _project_path(value: str, root: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (root or app_data_root()) / path
    return path.resolve()
