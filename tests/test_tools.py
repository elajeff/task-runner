from pathlib import Path

import pytest

from runtime.tools import MAX_TEXT_FILE_BYTES, ToolError, ToolRegistry


def test_write_and_read_text_file(tmp_path: Path):
    tools = ToolRegistry(tmp_path)
    tools.execute("write_text_file", {"path": "report.txt", "content": "summary"})
    assert tools.execute("read_text_file", {"path": "report.txt"}) == "summary"


def test_paths_cannot_escape_workspace(tmp_path: Path):
    tools = ToolRegistry(tmp_path / "workspace")
    with pytest.raises(ToolError):
        tools.execute("read_text_file", {"path": "../outside.txt"})
    with pytest.raises(ToolError):
        tools.execute("write_text_file", {"path": str(tmp_path / "outside.txt"), "content": "no"})
    with pytest.raises(ToolError):
        tools.execute("read_text_file", {"path": "C:\\outside.txt"})
    with pytest.raises(ToolError):
        tools.execute("read_text_file", {"path": "folder/../outside.txt"})
    with pytest.raises(ToolError, match="Hidden or credential-like"):
        tools.execute("read_text_file", {"path": "report.txt:private-stream"})
    with pytest.raises(ToolError, match="Hidden or credential-like"):
        tools.execute("read_text_file", {"path": "NUL.txt"})
    with pytest.raises(ToolError, match="too long"):
        tools.execute("read_text_file", {"path": "a" * 1001})


def test_unknown_tool_is_rejected(tmp_path: Path):
    with pytest.raises(ToolError, match="not allowed"):
        ToolRegistry(tmp_path).execute("run_shell", {"command": "whoami"})


def test_tool_arguments_are_validated(tmp_path: Path):
    tools = ToolRegistry(tmp_path)
    with pytest.raises(ToolError, match="Unexpected argument"):
        tools.execute("list_files", {"unexpected": True})
    with pytest.raises(ToolError, match="Missing argument"):
        tools.execute("write_text_file", {"path": "missing-content.txt"})
    with pytest.raises(ToolError, match="path must be a non-empty"):
        tools.execute("read_text_file", {"path": "  "})


def test_hidden_and_credential_like_paths_are_blocked(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("API_KEY=do-not-read", encoding="utf-8")
    (workspace / "credentials.json").write_text("{}", encoding="utf-8")
    tools = ToolRegistry(workspace)
    for path in (".env", "credentials.json", ".ssh/id_rsa", "config.pem"):
        with pytest.raises(ToolError, match="Hidden or credential-like"):
            tools.execute("read_text_file", {"path": path})
        with pytest.raises(ToolError, match="Hidden or credential-like"):
            tools.execute("write_text_file", {"path": path, "content": "bad"})


def test_symlinks_cannot_read_or_write_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    try:
        (workspace / "outside-link.txt").symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlink creation is not available on this system: {exc}")

    tools = ToolRegistry(workspace)
    with pytest.raises(ToolError, match="Symbolic links"):
        tools.execute("read_text_file", {"path": "outside-link.txt"})
    with pytest.raises(ToolError, match="Symbolic links"):
        tools.execute("write_text_file", {"path": "outside-link.txt", "content": "modified"})
    assert outside.read_text(encoding="utf-8") == "private"


def test_read_and_write_size_limits(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    huge_file = workspace / "large.txt"
    huge_file.write_bytes(b"x" * (MAX_TEXT_FILE_BYTES + 1))
    tools = ToolRegistry(workspace)
    with pytest.raises(ToolError, match="too large to read"):
        tools.execute("read_text_file", {"path": "large.txt"})
    with pytest.raises(ToolError, match="too large to write"):
        tools.execute("write_text_file", {"path": "new.txt", "content": "x" * (MAX_TEXT_FILE_BYTES + 1)})
    assert not (workspace / "new.txt").exists()


def test_invalid_utf8_is_rejected(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "binary.txt").write_bytes(b"\xff\xfe\xff")
    with pytest.raises(ToolError, match="not valid UTF-8"):
        ToolRegistry(workspace).execute("read_text_file", {"path": "binary.txt"})


def test_file_listing_skips_hidden_dirs_and_symlinks(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "visible.txt").write_text("visible", encoding="utf-8")
    (workspace / ".private.txt").write_text("private", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("private", encoding="utf-8")
    try:
        (workspace / "linked.txt").symlink_to(workspace / "visible.txt")
    except (OSError, NotImplementedError):
        pass
    listed = ToolRegistry(workspace).execute("list_files", {})
    assert listed == ["visible.txt"]


def test_existing_file_overwrite_requires_approval(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "report.txt"
    target.write_text("original", encoding="utf-8")

    with pytest.raises(ToolError, match="without user approval"):
        ToolRegistry(workspace).execute("write_text_file", {"path": "report.txt", "content": "new"})
    assert target.read_text(encoding="utf-8") == "original"


def test_overwrite_denial_preserves_existing_content(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "report.txt"
    target.write_text("original", encoding="utf-8")
    requested = []

    def deny(path: str) -> bool:
        requested.append(path)
        return False

    with pytest.raises(ToolError, match="User declined"):
        ToolRegistry(workspace, approval_callback=deny).execute(
            "write_text_file", {"path": "report.txt", "content": "replacement"}
        )
    assert requested == ["report.txt"]
    assert target.read_text(encoding="utf-8") == "original"


def test_approved_overwrite_replaces_content_atomically(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "report.txt"
    target.write_text("original", encoding="utf-8")
    calls = []

    def approve(path: str) -> bool:
        calls.append(path)
        return True

    result = ToolRegistry(workspace, approval_callback=approve).execute(
        "write_text_file", {"path": "report.txt", "content": "replacement"}
    )
    assert calls == ["report.txt"]
    assert target.read_text(encoding="utf-8") == "replacement"
    assert result["unchanged"] is False


def test_replaying_identical_write_needs_no_second_approval(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tools = ToolRegistry(workspace)
    first = tools.execute("write_text_file", {"path": "report.txt", "content": "same"})
    second = tools.execute("write_text_file", {"path": "report.txt", "content": "same"})
    assert first["unchanged"] is False
    assert second["unchanged"] is True
    assert (workspace / "report.txt").read_text(encoding="utf-8") == "same"


def test_concurrent_writes_to_same_target_do_not_race(tmp_path: Path):
    import threading

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "report.txt"
    target.write_text("original", encoding="utf-8")
    approval_started = threading.Event()
    allow_approval_to_finish = threading.Event()
    thread_errors: list[Exception] = []

    def approve(_path: str) -> bool:
        approval_started.set()
        return allow_approval_to_finish.wait(timeout=3)

    first_tools = ToolRegistry(workspace, approval_callback=approve)
    second_tools = ToolRegistry(workspace, approval_callback=lambda _path: True)

    def first_write() -> None:
        try:
            first_tools.execute(
                "write_text_file", {"path": "report.txt", "content": "first replacement"}
            )
        except Exception as exc:
            thread_errors.append(exc)

    thread = threading.Thread(target=first_write, daemon=True)
    thread.start()
    assert approval_started.wait(timeout=2)
    with pytest.raises(ToolError, match="already writing"):
        second_tools.execute(
            "write_text_file", {"path": "report.txt", "content": "second replacement"}
        )
    allow_approval_to_finish.set()
    thread.join(timeout=4)
    assert not thread.is_alive()
    assert not thread_errors
    assert target.read_text(encoding="utf-8") == "first replacement"


def test_file_listing_is_capped_at_one_hundred_files(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for index in range(125):
        (workspace / f"file-{index:03}.txt").write_text("x", encoding="utf-8")
    listed = ToolRegistry(workspace).execute("list_files", {})
    assert len(listed) == 100
    assert listed == sorted(listed)


def test_workspace_scan_stops_at_configured_entry_limit(tmp_path: Path, monkeypatch):
    import runtime.tools as tools_module

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in ("one.txt", "two.txt", "three.txt"):
        (workspace / name).write_text(name, encoding="utf-8")
    monkeypatch.setattr(tools_module, "MAX_WORKSPACE_ENTRIES_SCANNED", 2)

    with pytest.raises(ToolError, match="too many entries"):
        ToolRegistry(workspace).execute("list_files", {})


def test_failed_atomic_replace_preserves_existing_file_and_cleans_temp(
    tmp_path: Path, monkeypatch
):
    import runtime.tools as tools_module

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "report.txt"
    target.write_text("original", encoding="utf-8")

    def fail_replace(_source, _destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(tools_module.os, "replace", fail_replace)
    tools = ToolRegistry(workspace, approval_callback=lambda _path: True)
    with pytest.raises(ToolError, match="Could not write the requested file"):
        tools.execute("write_text_file", {"path": "report.txt", "content": "replacement"})

    assert target.read_text(encoding="utf-8") == "original"
    assert list(workspace.glob(".report.txt.*.tmp")) == []


def test_read_accepts_file_exactly_at_size_limit(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    expected = "a" * MAX_TEXT_FILE_BYTES
    (workspace / "limit.txt").write_text(expected, encoding="utf-8")

    assert ToolRegistry(workspace).execute("read_text_file", {"path": "limit.txt"}) == expected
