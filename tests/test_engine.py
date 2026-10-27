import json
import threading
from pathlib import Path

import pytest

from runtime.engine import (
    MAX_PROMPT_CHARS,
    AgentRuntime,
)
from runtime.storage import TaskStore
from runtime.tools import ToolRegistry, ToolError


class ScriptedProvider:
    """Test double for deterministic runtime tests; not a user-facing provider."""

    def __init__(self, responses: list[dict]):
        self.responses = iter(responses)
        self.prompts = []
        self.calls = 0

    def generate_json(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        return json.dumps(next(self.responses))


class BlockingProvider:
    def __init__(self, started: threading.Event, release: threading.Event):
        self.started = started
        self.release = release
        self.calls = 0

    def generate_json(self, prompt: str) -> str:
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("Test provider was not released.")
        return json.dumps({"action": "finish", "response": "Task completed."})


def test_runtime_executes_tool_calls_and_persists_results(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("apples and oranges", encoding="utf-8")
    model = ScriptedProvider([
        {"action": "tool", "tool": "read_text_file", "arguments": {"path": "notes.txt"}},
        {"action": "tool", "tool": "write_text_file", "arguments": {"path": "summary.txt", "content": "Notes mention apples and oranges."}},
        {"action": "finish", "response": "Saved summary.txt."},
    ])
    store = TaskStore(tmp_path / "runtime.db")
    try:
        runtime = AgentRuntime(store, ToolRegistry(workspace), model)
        task_id = runtime.create_task("Summarize notes and save the summary")
        result = runtime.run(task_id)
        assert result["status"] == "completed"
        assert (workspace / "summary.txt").read_text(encoding="utf-8") == "Notes mention apples and oranges."
        history = store.history(task_id)
        assert len(history) == 2
        assert history[0]["status"] == "completed"
        assert store.get_steps(task_id)[0]["planned_action"] == "Read workspace file notes.txt"
        assert store.get_steps(task_id)[1]["planned_action"].startswith("Write 33 characters to workspace file summary.txt")
        assert "apples and oranges" in model.prompts[1]
    finally:
        store.close()


def test_resume_rejects_a_different_workspace_before_replaying_a_write(tmp_path: Path):
    original = tmp_path / "original"
    other = tmp_path / "other"
    original.mkdir()
    other.mkdir()
    model = ScriptedProvider([])
    with TaskStore(tmp_path / "runtime.db") as store:
        task_id = AgentRuntime(store, ToolRegistry(original), model).create_task("Save result")
        store.add_running_step(task_id, 1, "write_text_file",
                               {"path": "result.txt", "content": "saved action"})
        runtime = AgentRuntime(store, ToolRegistry(other), model)
        with pytest.raises(ValueError, match="saved folder"):
            runtime.run(task_id, retry_uncertain=True)
        assert not (original / "result.txt").exists()
        assert not (other / "result.txt").exists()
        assert store.get_running_step(task_id) is not None
        assert model.calls == 0


def test_running_step_requires_explicit_retry_after_restart(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("recover me", encoding="utf-8")
    database = tmp_path / "runtime.db"
    store = TaskStore(database)
    try:
        task_id = store.create_task("Read notes")
        store.add_running_step(task_id, 1, "read_text_file", {"path": "notes.txt"})
        model = ScriptedProvider([{"action": "finish", "response": "Read notes successfully."}])
        runtime = AgentRuntime(store, ToolRegistry(workspace), model)
        result = runtime.run(task_id)
        assert result["status"] == "failed"
        assert store.get_uncertain_step(task_id) is not None
        result = runtime.run(task_id, retry_uncertain=True)
        assert result["status"] == "completed"
        assert store.history(task_id)[0]["result"] == "recover me"
    finally:
        store.close()


def test_interrupted_write_replay_is_idempotent_and_does_not_overwrite_again(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "report.txt").write_text("finished before crash", encoding="utf-8")
    store = TaskStore(tmp_path / "runtime.db")
    try:
        task_id = store.create_task("Write the report")
        store.add_running_step(
            task_id,
            1,
            "write_text_file",
            {"path": "report.txt", "content": "finished before crash"},
        )
        model = ScriptedProvider([{"action": "finish", "response": "Report saved."}])
        runtime = AgentRuntime(store, ToolRegistry(workspace), model)
        result = runtime.run(task_id)
        assert result["status"] == "failed"
        result = runtime.run(task_id, retry_uncertain=True)
        assert result["status"] == "completed"
        assert store.history(task_id)[0]["result"]["unchanged"] is True
        assert (workspace / "report.txt").read_text(encoding="utf-8") == "finished before crash"
    finally:
        store.close()


def test_unknown_tool_is_rejected_and_recorded_as_failed(tmp_path: Path):
    store = TaskStore(tmp_path / "runtime.db")
    try:
        model = ScriptedProvider([
            {"action": "tool", "tool": "run_shell", "arguments": {"command": "whoami"}}
        ])
        runtime = AgentRuntime(store, ToolRegistry(tmp_path / "workspace"), model)
        task_id = runtime.create_task("Do something")
        with pytest.raises(ToolError, match="not allowed"):
            runtime.run(task_id)
        assert store.get_task(task_id)["status"] == "failed"
        assert store.get_steps(task_id)[0]["status"] == "failed"
    finally:
        store.close()


def test_failed_step_is_visible_when_task_is_resumed(tmp_path: Path):
    store = TaskStore(tmp_path / "runtime.db")
    try:
        first_model = ScriptedProvider([
            {"action": "tool", "tool": "run_shell", "arguments": {"command": "whoami"}}
        ])
        runtime = AgentRuntime(store, ToolRegistry(tmp_path / "workspace"), first_model)
        task_id = runtime.create_task("Do something")
        with pytest.raises(ToolError):
            runtime.run(task_id)

        retry_model = ScriptedProvider([{"action": "finish", "response": "Stopped the unsupported operation."}])
        resumed = AgentRuntime(store, ToolRegistry(tmp_path / "workspace"), retry_model).run(task_id)
        assert resumed["status"] == "completed"
        assert "Tool is not allowed: run_shell" in retry_model.prompts[0]
        assert '"status": "failed"' in retry_model.prompts[0]
    finally:
        store.close()


def test_paused_task_can_continue_on_a_later_run(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("one", encoding="utf-8")
    model = ScriptedProvider([
        {"action": "tool", "tool": "read_text_file", "arguments": {"path": "notes.txt"}},
        {"action": "finish", "response": "Done after resuming."},
    ])
    store = TaskStore(tmp_path / "runtime.db")
    try:
        runtime = AgentRuntime(store, ToolRegistry(workspace), model, max_steps=1)
        task_id = runtime.create_task("Read notes")
        first_result = runtime.run(task_id)
        assert first_result["status"] == "paused"
        second_result = runtime.run(task_id)
        assert second_result["status"] == "completed"
        assert second_result["final_response"] == "Done after resuming."
    finally:
        store.close()


@pytest.mark.parametrize("value", [0, -1, 51, True, "3"])
def test_max_steps_must_be_a_bounded_integer(tmp_path: Path, value):
    store = TaskStore(tmp_path / "runtime.db")
    try:
        with pytest.raises(ValueError, match="max_steps"):
            AgentRuntime(store, ToolRegistry(tmp_path / "workspace"), ScriptedProvider([]), value)
    finally:
        store.close()


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not JSON",
        "[]",
        '{"action":"finish","response":"done","response":"also done"}',
        '{"action":"finish","response":NaN}',
        '{"action":"tool","tool":"read_text_file","arguments":{},"extra":true}',
        '{"action":"finish","response":""}',
    ],
)
def test_model_response_validation_rejects_malformed_actions(raw: str):
    with pytest.raises(ValueError):
        AgentRuntime._parse_action(raw)


def test_model_response_and_final_text_are_size_limited():
    with pytest.raises(ValueError, match="too large"):
        AgentRuntime._parse_action(" " * 100_001)
    with pytest.raises(ValueError, match="too long"):
        AgentRuntime._parse_action(json.dumps({"action": "finish", "response": "x" * 8001}))


def test_prompt_history_is_bounded_and_notes_omitted_records(tmp_path: Path):
    store = TaskStore(tmp_path / "runtime.db")
    try:
        runtime = AgentRuntime(store, ToolRegistry(tmp_path / "workspace"), ScriptedProvider([]))
        huge_history = [
            {"tool": "read_text_file", "arguments": {"path": f"file-{index}.txt"}, "status": "completed", "result": "x" * 8000}
            for index in range(30)
        ]
        prompt = runtime._build_prompt("Summarize my files", huge_history)
        assert len(prompt) <= MAX_PROMPT_CHARS
        assert "older tool-history entries were omitted" in prompt or "Result truncated in model context" in prompt
    finally:
        store.close()


def test_invalid_task_id_is_rejected_before_lock_path_is_built(tmp_path: Path):
    store = TaskStore(tmp_path / "runtime.db")
    try:
        runtime = AgentRuntime(store, ToolRegistry(tmp_path / "workspace"), ScriptedProvider([]))
        with pytest.raises(ValueError, match="12-character identifier"):
            runtime.run("../../outside")
        assert not (tmp_path / "outside.lock").exists()
    finally:
        store.close()


def test_same_task_cannot_run_in_two_process_contexts_at_once(tmp_path: Path):
    database = tmp_path / "runtime.db"
    workspace = tmp_path / "workspace"
    main_store = TaskStore(database)
    task_id = main_store.create_task("Wait and finish")
    main_store.close()

    provider_started = threading.Event()
    release_provider = threading.Event()
    worker_errors: list[Exception] = []
    worker_results: list[dict] = []

    def worker() -> None:
        store = TaskStore(database)
        try:
            runtime = AgentRuntime(
                store,
                ToolRegistry(workspace),
                BlockingProvider(provider_started, release_provider),
            )
            worker_results.append(runtime.run(task_id))
        except Exception as exc:  # captured for assertion on main thread
            worker_errors.append(exc)
        finally:
            store.close()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert provider_started.wait(timeout=3), "First run did not reach its provider call."
    second_store = TaskStore(database)
    try:
        second_runtime = AgentRuntime(
            second_store,
            ToolRegistry(workspace),
            ScriptedProvider([{"action": "finish", "response": "duplicate"}]),
        )
        with pytest.raises(RuntimeError, match="already running"):
            second_runtime.run(task_id)
    finally:
        second_store.close()
        release_provider.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert not worker_errors
    assert worker_results[0]["status"] == "completed"


def test_task_description_must_be_non_empty_and_bounded(tmp_path: Path):
    store = TaskStore(tmp_path / "runtime.db")
    try:
        runtime = AgentRuntime(store, ToolRegistry(tmp_path / "workspace"), ScriptedProvider([]))
        for description in ("", "  ", None, "x" * 4001):
            with pytest.raises(ValueError):
                runtime.create_task(description)
        task_id = runtime.create_task("x" * 4000)
        assert store.get_task(task_id)["description"] == "x" * 4000
    finally:
        store.close()


def test_agent_instructions_discover_files_when_user_does_not_name_them():
    from runtime.engine import SYSTEM_INSTRUCTIONS

    assert "list the available files first" in SYSTEM_INSTRUCTIONS
    assert "Never invent filenames" in SYSTEM_INSTRUCTIONS


def test_new_task_records_its_workspace_for_safe_resume(tmp_path: Path):
    database = tmp_path / "runtime.db"
    workspace = tmp_path / "chosen project"
    store = TaskStore(database)
    try:
        runtime = AgentRuntime(store, ToolRegistry(workspace), ScriptedProvider([]))
        task_id = runtime.create_task("Compare project notes")
        assert store.get_task(task_id)["workspace_path"] == str(workspace.resolve())
    finally:
        store.close()
