from pathlib import Path

from runtime.storage import TaskStore


def test_task_and_step_survive_reopening_database(tmp_path: Path):
    database = tmp_path / "runtime.db"
    store = TaskStore(database)
    task_id = store.create_task("Read notes")
    step_id = store.add_running_step(task_id, 1, "read_text_file", {"path": "notes.txt"})
    store.finish_step(step_id, "hello")
    store.close()

    reopened = TaskStore(database)
    try:
        task = reopened.get_task(task_id)
        assert task is not None
        assert task["description"] == "Read notes"
        assert reopened.history(task_id) == [
            {
                "tool": "read_text_file",
                "arguments": {"path": "notes.txt"},
                "status": "completed",
                "result": "hello",
                "planned_action": "Execute read_text_file",
            }
        ]
    finally:
        reopened.close()


def test_failed_step_is_in_history_for_recovery(tmp_path: Path):
    database = tmp_path / "runtime.db"
    store = TaskStore(database)
    try:
        task_id = store.create_task("Read a missing file")
        step_id = store.add_running_step(task_id, 1, "read_text_file", {"path": "missing.txt"})
        store.fail_step(step_id, "File not found: missing.txt")
        assert store.history(task_id) == [
            {
                "tool": "read_text_file",
                "arguments": {"path": "missing.txt"},
                "status": "failed",
                "error": "File not found: missing.txt",
                "planned_action": "Execute read_text_file",
            }
        ]
    finally:
        store.close()


def test_task_list_limit_is_bounded(tmp_path: Path):
    import pytest

    store = TaskStore(tmp_path / "runtime.db")
    try:
        assert store.list_tasks(limit=1) == []
        for bad_limit in (0, -1, 101, True, "10"):
            with pytest.raises(ValueError, match="between 1 and 100"):
                store.list_tasks(limit=bad_limit)
    finally:
        store.close()


def test_bounded_step_history_returns_latest_entries_in_chronological_order(tmp_path: Path):
    store = TaskStore(tmp_path / "runtime.db")
    try:
        task_id = store.create_task("Keep a long history")
        for sequence in range(1, 5):
            step_id = store.add_running_step(
                task_id,
                sequence,
                "read_text_file",
                {"path": f"notes-{sequence}.txt"},
            )
            store.finish_step(step_id, f"result-{sequence}")

        latest = store.get_steps(task_id, limit=2)
        assert [step["sequence"] for step in latest] == [3, 4]
        assert [entry["result"] for entry in store.history(task_id, limit=2)] == [
            "result-3",
            "result-4",
        ]
        assert store.step_count(task_id) == 4
        assert len(store.get_steps(task_id)) == 4
    finally:
        store.close()


def test_step_history_limit_rejects_invalid_values(tmp_path: Path):
    import pytest

    store = TaskStore(tmp_path / "runtime.db")
    try:
        task_id = store.create_task("Validate history limits")
        for bad_limit in (0, -1, 501, True, "10", 1.5):
            with pytest.raises(ValueError, match="between 1 and 500"):
                store.get_steps(task_id, limit=bad_limit)
            with pytest.raises(ValueError, match="between 1 and 500"):
                store.history(task_id, limit=bad_limit)
    finally:
        store.close()


def test_sqlite_backup_is_created_and_retention_is_three(tmp_path: Path):
    database = tmp_path / "runtime.db"
    for index in range(5):
        store = TaskStore(database)
        store.create_task(f"Task {index}")
        store.close()
    backups = list((tmp_path / "backups").glob("runtime-*.db"))
    assert len(backups) == 3
    import sqlite3
    connection = sqlite3.connect(backups[0])
    try:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] >= 1
    finally:
        connection.close()


def test_old_step_schema_migrates_without_losing_history(tmp_path: Path):
    import sqlite3
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('running','completed','failed','paused')),
            final_response TEXT, error_text TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE steps (id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL, tool_name TEXT NOT NULL, arguments_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('running','completed','failed')),
            result_json TEXT, error_text TEXT, created_at TEXT NOT NULL, finished_at TEXT,
            UNIQUE(task_id, sequence));
        INSERT INTO tasks VALUES ('abcdef123456','legacy task','completed','done',NULL,'now','now');
        INSERT INTO steps (task_id,sequence,tool_name,arguments_json,status,result_json,created_at)
            VALUES ('abcdef123456',1,'read_text_file','{"path":"a.txt"}','completed','"ok"','now');
    """)
    connection.commit()
    connection.close()
    store = TaskStore(database)
    try:
        assert store.history("abcdef123456")[0]["result"] == "ok"
        columns = {row[1] for row in store._connection.execute("PRAGMA table_info(tasks)")}
        assert "workspace_path" in columns
        assert store.get_task("abcdef123456")["workspace_path"] is None
        step_id = store.add_running_step("abcdef123456", 2, "read_text_file", {"path": "b.txt"})
        store.mark_step_uncertain(step_id)
        assert store.get_uncertain_step("abcdef123456") is not None
    finally:
        store.close()


def test_recovery_scan_marks_unlocked_running_task_and_step_uncertain(tmp_path: Path):
    store = TaskStore(tmp_path / "runtime.db")
    try:
        task_id = store.create_task("Interrupted task")
        step_id = store.add_running_step(task_id, 1, "write_text_file", {"path": "x.txt", "content": "x"})
        assert store.recover_interrupted_tasks() == [task_id]
        assert store.get_task(task_id)["status"] == "failed"
        assert store.get_steps(task_id)[0]["status"] == "uncertain"
        assert store.get_uncertain_step(task_id)["id"] == step_id
    finally:
        store.close()


def test_saved_task_keeps_the_working_folder_path(tmp_path: Path):
    workspace = tmp_path / "project files"
    store = TaskStore(tmp_path / "runtime.db")
    try:
        task_id = store.create_task("Compare notes", workspace_path=workspace)
        assert store.get_task(task_id)["workspace_path"] == str(workspace.resolve())
    finally:
        store.close()
