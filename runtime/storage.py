"""SQLite persistence for tasks and their tool execution history."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self, database: Path) -> None:
        self.database = Path(database).expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database, timeout=10)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._create_schema()
        self._changes_at_backup = self._connection.total_changes

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'paused')),
                final_response TEXT,
                error_text TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                workspace_path TEXT
            );
            CREATE TABLE IF NOT EXISTS steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'uncertain')),
                result_json TEXT,
                error_text TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                UNIQUE(task_id, sequence)
            );
            """
        )
        # Migrate older databases without discarding their saved task history.
        task_columns = {row[1] for row in self._connection.execute("PRAGMA table_info(tasks)")}
        if "workspace_path" not in task_columns:
            self._connection.execute("ALTER TABLE tasks ADD COLUMN workspace_path TEXT")
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(steps)")}
        table_sql_row = self._connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='steps'").fetchone()
        table_sql = table_sql_row[0] if table_sql_row else ""
        if "uncertain" not in table_sql:
            # SQLite cannot alter a CHECK constraint in place. Rebuild this small
            # table while preserving saved history and step IDs.
            self._connection.execute("ALTER TABLE steps RENAME TO steps_legacy")
            self._connection.execute("""CREATE TABLE steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'uncertain')),
                result_json TEXT, error_text TEXT, created_at TEXT NOT NULL, finished_at TEXT,
                planned_action TEXT, UNIQUE(task_id, sequence)
            )""")
            planned = "planned_action" if "planned_action" in columns else "NULL"
            self._connection.execute(f"""INSERT INTO steps
                (id, task_id, sequence, tool_name, arguments_json, status, result_json, error_text, created_at, finished_at, planned_action)
                SELECT id, task_id, sequence, tool_name, arguments_json, status, result_json, error_text, created_at, finished_at, {planned}
                FROM steps_legacy""")
            self._connection.execute("DROP TABLE steps_legacy")
        elif "planned_action" not in columns:
            self._connection.execute("ALTER TABLE steps ADD COLUMN planned_action TEXT")
        self._connection.commit()

    def close(self) -> None:
        if self._connection is None:
            return
        try:
            if self._connection.total_changes > self._changes_at_backup:
                self._create_backup()
        finally:
            self._connection.close()
            self._connection = None

    def _create_backup(self) -> None:
        """Create a consistent SQLite backup, retaining the newest three copies."""
        backup_dir = self.database.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = backup_dir / f"{self.database.stem}-{stamp}.db"
        temporary = destination.with_suffix(".tmp")
        target = sqlite3.connect(temporary)
        try:
            self._connection.backup(target)
            target.close()
            os.replace(temporary, destination)
        except Exception:
            target.close()
            temporary.unlink(missing_ok=True)
            raise
        backups = sorted(backup_dir.glob(f"{self.database.stem}-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[3:]:
            old.unlink(missing_ok=True)

    def recover_interrupted_tasks(self) -> list[str]:
        """Mark tasks as interrupted when their execution lock is no longer held."""
        from filelock import FileLock, Timeout
        lock_dir = self.database.parent / ".runtime-locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        rows = self._connection.execute(
            "SELECT id FROM tasks WHERE status = 'running'"
        ).fetchall()
        recovered: list[str] = []
        for row in rows:
            task_id = row["id"]
            lock = FileLock(str(lock_dir / f"{task_id}.lock"), timeout=0)
            try:
                with lock:
                    with self._connection:
                        self._connection.execute(
                            "UPDATE steps SET status = 'uncertain', error_text = ?, finished_at = ? "
                            "WHERE task_id = ? AND status = 'running'",
                            ("Application stopped before the action outcome was saved; inspect before retrying.", _now(), task_id),
                        )
                        self._connection.execute(
                            "UPDATE tasks SET status = 'failed', error_text = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                            ("Task was interrupted. Review saved steps, then explicitly resume if appropriate.", _now(), task_id),
                        )
                    recovered.append(task_id)
            except Timeout:
                # Another CLI/GUI process still owns this task's lock.
                continue
        return recovered

    def create_task(self, description: str, workspace_path: Path | str | None = None) -> str:
        task_id = uuid4().hex[:12]
        now = _now()
        saved_workspace = str(Path(workspace_path).expanduser().resolve()) if workspace_path else None
        with self._connection:
            self._connection.execute(
                "INSERT INTO tasks (id, description, status, created_at, updated_at, workspace_path) "
                "VALUES (?, ?, 'running', ?, ?, ?)",
                (task_id, description, now, now, saved_workspace),
            )
        return task_id

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("Task list limit must be an integer between 1 and 100.")
        rows = self._connection.execute(
            "SELECT id, description, status, created_at, updated_at FROM tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_steps(self, task_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        if limit is None:
            rows = self._connection.execute(
                "SELECT * FROM steps WHERE task_id = ? ORDER BY sequence", (task_id,)
            ).fetchall()
            return [dict(row) for row in rows]
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Step history limit must be an integer between 1 and 500.")
        # Load the newest rows first for a bounded query, then reverse them so callers
        # still see chronological order. The full database history is not changed.
        rows = self._connection.execute(
            "SELECT * FROM steps WHERE task_id = ? ORDER BY sequence DESC LIMIT ?",
            (task_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def step_count(self, task_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM steps WHERE task_id = ?", (task_id,)
        ).fetchone()
        return int(row["count"])

    def add_running_step(self, task_id: str, sequence: int, tool_name: str, arguments: dict[str, Any], planned_action: str | None = None) -> int:
        now = _now()
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO steps (task_id, sequence, tool_name, arguments_json, status, created_at, planned_action) VALUES (?, ?, ?, ?, 'running', ?, ?)",
                (task_id, sequence, tool_name, json.dumps(arguments, ensure_ascii=False), now, planned_action or f"Execute {tool_name}"),
            )
        return int(cursor.lastrowid)

    def mark_step_uncertain(self, step_id: int, reason: str = "Process stopped before the outcome was saved.") -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE steps SET status = 'uncertain', error_text = ?, finished_at = ? WHERE id = ? AND status = 'running'",
                (reason[:2000], _now(), step_id),
            )

    def get_uncertain_step(self, task_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM steps WHERE task_id = ? AND status = 'uncertain' ORDER BY sequence LIMIT 1", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def retry_uncertain_step(self, step_id: int) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE steps SET status = 'running', error_text = NULL, finished_at = NULL WHERE id = ? AND status = 'uncertain'",
                (step_id,),
            )

    def get_running_step(self, task_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM steps WHERE task_id = ? AND status = 'running' ORDER BY sequence LIMIT 1",
            (task_id,),
        ).fetchone()
        return dict(row) if row else None

    def finish_step(self, step_id: int, result: Any) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE steps SET status = 'completed', result_json = ?, finished_at = ?, error_text = NULL WHERE id = ?",
                (json.dumps(result, ensure_ascii=False), _now(), step_id),
            )

    def fail_step(self, step_id: int, error: str) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE steps SET status = 'failed', error_text = ?, finished_at = ? WHERE id = ?",
                (error[:2000], _now(), step_id),
            )

    def set_task_status(self, task_id: str, status: str, *, response: str | None = None, error: str | None = None) -> None:
        if status not in {"running", "completed", "failed", "paused"}:
            raise ValueError(f"Unsupported task status: {status}")
        with self._connection:
            self._connection.execute(
                "UPDATE tasks SET status = ?, final_response = ?, error_text = ?, updated_at = ? WHERE id = ?",
                (status, response, error[:2000] if error else None, _now(), task_id),
            )

    def history(self, task_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        """Return prior tool calls, including failures needed for safe recovery."""
        history: list[dict[str, Any]] = []
        for step in self.get_steps(task_id, limit=limit):
            entry: dict[str, Any] = {
                "tool": step["tool_name"],
                "arguments": json.loads(step["arguments_json"]),
                "status": step["status"],
            }
            if step["status"] == "completed":
                entry["result"] = json.loads(step["result_json"])
            elif step["status"] == "failed":
                entry["error"] = step["error_text"] or "The tool call failed without an error message."
            else:
                entry["error"] = step.get("error_text") or "The tool call outcome is uncertain; inspect before retrying."
            if step.get("planned_action"):
                entry["planned_action"] = step["planned_action"]
            history.append(entry)
        return history

    def __enter__(self) -> "TaskStore":
        return self

    def __exit__(self, *_args) -> None:
        self.close()
