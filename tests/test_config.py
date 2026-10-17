from pathlib import Path

import runtime.config as config


def test_relative_paths_follow_the_actual_project_root(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "installed task-runner"
    project_root.mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", project_root)

    assert config._project_path("workspace") == (project_root / "workspace").resolve()


def test_absolute_working_folder_is_respected(tmp_path: Path):
    chosen = tmp_path / "another project"
    assert config._project_path(str(chosen)) == chosen.resolve()



def test_packaged_paths_use_local_app_data(tmp_path: Path, monkeypatch):
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)

    root = local_app_data / "task-runner"
    assert config.app_data_root() == root.resolve()
    assert config.env_file_path() == (root / ".env").resolve()
    assert config._project_path("workspace") == (root / "workspace").resolve()


def test_packaged_default_paths_do_not_use_the_executable_directory(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    for name in ("AGENT_PROVIDER", "AGENT_WORKSPACE", "AGENT_DATABASE", "AGENT_MAX_STEPS"):
        monkeypatch.delenv(name, raising=False)

    settings = config.Config.from_environment()
    data_root = tmp_path / "LocalAppData" / "task-runner"
    assert settings.workspace == (data_root / "workspace").resolve()
    assert settings.database == (data_root / "data" / "runtime.db").resolve()


def test_packaged_paths_migrate_legacy_user_data_folder(tmp_path: Path, monkeypatch):
    local_app_data = tmp_path / "LocalAppData"
    legacy_root = local_app_data / "TaskRunner"
    legacy_root.mkdir(parents=True)
    (legacy_root / ".env").write_text("AGENT_PROVIDER=ollama\n", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)

    new_root = local_app_data / "task-runner"
    assert config.app_data_root() == new_root.resolve()
    assert (new_root / ".env").is_file()
    assert not legacy_root.exists()
