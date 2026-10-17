from pathlib import Path
import os

from dotenv import dotenv_values

from runtime.settings import load_provider_settings, save_provider_settings


def test_saving_provider_settings_preserves_other_provider_keys(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=keep-this\nAGENT_PROVIDER=gemini\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)

    save_provider_settings(
        env_file,
        "gemini",
        {"model": "gemini-test-model", "api_key": "test-gemini-key", "base_url": "", "json_mode": True},
    )

    values = dotenv_values(env_file)
    assert values["AGENT_PROVIDER"] == "gemini"
    assert values["GEMINI_MODEL"] == "gemini-test-model"
    assert values["GEMINI_API_KEY"] == "test-gemini-key"
    assert values["OPENAI_API_KEY"] == "keep-this"
    assert os.environ["GEMINI_API_KEY"] == "test-gemini-key"


def test_loads_openai_compatible_settings(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'AGENT_PROVIDER="openai_compatible"\n'
        'COMPAT_MODEL="local-model"\n'
        'COMPAT_BASE_URL="http://localhost:1234/v1"\n'
        'COMPAT_JSON_MODE="false"\n',
        encoding="utf-8",
    )
    settings = load_provider_settings(env_file, "openai_compatible")
    assert settings["model"] == "local-model"
    assert settings["base_url"] == "http://localhost:1234/v1"
    assert settings["json_mode"] is False


def test_workspace_setting_keeps_default_relative_and_custom_folder_absolute(tmp_path: Path, monkeypatch):
    from runtime.settings import save_workspace_path

    env_file = tmp_path / ".env"
    project_root = tmp_path / "task-runner"
    default_workspace = project_root / "workspace"
    custom_workspace = tmp_path / "another project"
    custom_workspace.mkdir(parents=True)
    monkeypatch.delenv("AGENT_WORKSPACE", raising=False)

    save_workspace_path(env_file, default_workspace, project_root)
    assert dotenv_values(env_file)["AGENT_WORKSPACE"] == "workspace"
    assert os.environ["AGENT_WORKSPACE"] == "workspace"

    save_workspace_path(env_file, custom_workspace, project_root)
    assert dotenv_values(env_file)["AGENT_WORKSPACE"] == str(custom_workspace.resolve())
    assert os.environ["AGENT_WORKSPACE"] == str(custom_workspace.resolve())
