from pathlib import Path

import pytest

from runtime import gui


def _window(workspace: Path):
    window = gui.RuntimeWindow.__new__(gui.RuntimeWindow)
    window.root = object()
    window.document_workspace = workspace
    window.last_document_dir = None
    return window


def test_open_latest_results_explains_how_to_create_first_result(tmp_path: Path, monkeypatch):
    window = _window(tmp_path)
    notices = []
    opened = []
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda title, message, **_kwargs: notices.append((title, message)))
    monkeypatch.setattr(gui, "_open_directory", lambda path: opened.append(path))

    window.open_latest_results()

    assert not opened
    assert notices and "use Extract text or Generate AI outputs first" in notices[0][1]


def test_open_latest_results_opens_exact_run_folder(tmp_path: Path, monkeypatch):
    window = _window(tmp_path)
    run_folder = tmp_path / "document_outputs" / "report_run"
    run_folder.mkdir(parents=True)
    (run_folder / "START_HERE.txt").write_text("results", encoding="utf-8")
    window.last_document_dir = run_folder
    opened = []
    monkeypatch.setattr(gui, "_open_directory", lambda path: opened.append(path))

    window.open_latest_results()

    assert opened == [run_folder]


def test_browse_all_results_opens_parent_folder(tmp_path: Path, monkeypatch):
    window = _window(tmp_path)
    output_root = tmp_path / "document_outputs"
    run_folder = output_root / "report_run"
    run_folder.mkdir(parents=True)
    (run_folder / "START_HERE.txt").write_text("results", encoding="utf-8")
    opened = []
    monkeypatch.setattr(gui, "_open_directory", lambda path: opened.append(path))

    window.browse_all_results()

    assert opened == [output_root]


def test_browse_all_results_explains_how_to_create_first_result(tmp_path: Path, monkeypatch):
    window = _window(tmp_path)
    notices = []
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda title, message, **_kwargs: notices.append((title, message)))
    monkeypatch.setattr(gui, "_open_directory", lambda _path: (_ for _ in ()).throw(AssertionError("nothing to open")))

    window.browse_all_results()

    assert notices and "use Extract text or Generate AI outputs first" in notices[0][1]


def test_view_latest_results_prompts_when_job_has_no_outputs_yet(tmp_path: Path, monkeypatch):
    from runtime.documents import create_document_job

    source = tmp_path / "report.txt"
    source.write_text("Not processed yet", encoding="utf-8")
    run_folder = create_document_job(source, ["verbatim"], False, tmp_path / "document_outputs")
    window = _window(tmp_path)
    window.last_document_dir = run_folder
    notices = []
    opened = []
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda title, message, **_kwargs: notices.append((title, message)))
    monkeypatch.setattr(gui, "_open_file", lambda path: opened.append(path))

    window.view_latest_results()

    assert notices and "has not saved any results yet" in notices[0][1]
    assert not opened


def test_view_latest_results_builds_and_opens_formatted_preview(tmp_path: Path, monkeypatch):
    from runtime.documents import create_document_job, process_document_job

    source = tmp_path / "report.txt"
    source.write_text("# Report\n\n| Product | Revenue |\n|---|---|\n| Alpha | 1200 |", encoding="utf-8")
    run_folder = create_document_job(source, ["verbatim"], False, tmp_path / "document_outputs")
    process_document_job(run_folder, None)
    window = _window(tmp_path)
    window.last_document_dir = run_folder
    opened = []
    monkeypatch.setattr(gui, "_open_file", lambda path: opened.append(path))

    window.view_latest_results()

    assert opened == [run_folder / "results.html"]
    assert (run_folder / "results.html").is_file()


def test_startup_cleanup_removes_old_index_only_from_known_document_jobs(tmp_path: Path):
    recognized = tmp_path / "document_outputs" / "recognized_job"
    recognized.mkdir(parents=True)
    (recognized / ".task-runner-document.json").write_text("{}", encoding="utf-8")
    old_index = recognized / "START_HERE.txt"
    old_index.write_text("Old generated guide", encoding="utf-8")

    unrelated = tmp_path / "document_outputs" / "unrelated_folder"
    unrelated.mkdir(parents=True)
    unrelated_index = unrelated / "START_HERE.txt"
    unrelated_index.write_text("A user's file", encoding="utf-8")

    gui.RuntimeWindow._remove_legacy_result_indexes(tmp_path)

    assert not old_index.exists()
    assert unrelated_index.read_text(encoding="utf-8") == "A user's file"


@pytest.mark.parametrize(
    ("choice", "expected_open"),
    [("browser", "browser"), ("folder", "folder"), (None, None)],
)
def test_results_ready_prompt_opens_selected_destination(
    tmp_path: Path, monkeypatch, choice: str | None, expected_open: str | None
):
    from runtime.documents import create_document_job, process_document_job

    source = tmp_path / "report.txt"
    source.write_text("Report text", encoding="utf-8")
    run_folder = create_document_job(source, ["verbatim"], False, tmp_path / "document_outputs")
    process_document_job(run_folder, None)
    window = _window(tmp_path)
    window.last_document_dir = run_folder
    monkeypatch.setattr(gui, "_ask_results_destination", lambda _parent: choice)
    opened = []
    monkeypatch.setattr(gui, "_open_file", lambda path: opened.append(("browser", path)))
    monkeypatch.setattr(gui, "_open_directory", lambda path: opened.append(("folder", path)))

    window._choose_results_destination(run_folder / "results.html")

    if expected_open is None:
        assert opened == []
    elif expected_open == "browser":
        assert opened == [("browser", run_folder / "results.html")]
    else:
        assert opened == [("folder", run_folder)]


def test_apply_app_icon_uses_bundled_icon_when_available(tmp_path: Path, monkeypatch):
    icon_folder = tmp_path / "assets"
    icon_folder.mkdir()
    icon_file = icon_folder / "task-runner.ico"
    icon_file.write_bytes(b"test icon placeholder")

    monkeypatch.setattr(gui.sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui.sys, "_MEIPASS", str(tmp_path), raising=False)

    class FakeRoot:
        def __init__(self):
            self.icon = None

        def iconbitmap(self, **kwargs):
            self.icon = kwargs.get("default")

    root = FakeRoot()
    gui._apply_app_icon(root)

    assert root.icon == str(icon_file)


def test_apply_app_icon_silently_skips_missing_icon(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gui.sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui.sys, "_MEIPASS", str(tmp_path), raising=False)

    class FakeRoot:
        def iconbitmap(self, **_kwargs):
            raise AssertionError("no icon exists, so this should not be called")

    gui._apply_app_icon(FakeRoot())
