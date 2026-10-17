import sys

from runtime.cli import approve_overwrite


class NonInteractiveStdin:
    def isatty(self) -> bool:
        return False


def test_cli_denies_overwrite_without_interactive_terminal(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", NonInteractiveStdin())
    assert approve_overwrite("report.txt") is False
    assert "no interactive terminal" in capsys.readouterr().err


def test_cli_accepts_only_explicit_yes(monkeypatch):
    class InteractiveStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", InteractiveStdin())
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    assert approve_overwrite("report.txt") is True
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    assert approve_overwrite("report.txt") is False


def test_status_command_limits_step_output(monkeypatch, capsys, tmp_path):
    import json
    from types import SimpleNamespace

    from runtime.storage import TaskStore
    import runtime.cli as cli_module

    database = tmp_path / "runtime.db"
    store = TaskStore(database)
    task_id = store.create_task("Create many steps")
    for sequence in range(1, 106):
        step_id = store.add_running_step(
            task_id, sequence, "read_text_file", {"path": f"file-{sequence}.txt"}
        )
        store.finish_step(step_id, f"result-{sequence}")
    store.close()

    monkeypatch.setattr(
        cli_module.Config,
        "from_environment",
        classmethod(lambda _cls: SimpleNamespace(database=database, workspace=tmp_path)),
    )
    monkeypatch.setattr(sys, "argv", ["durable-agent", "status", task_id])

    assert cli_module.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert len(output["steps"]) == 100
    assert output["steps"][0]["sequence"] == 6
    assert output["steps"][-1]["sequence"] == 105
    assert output["omitted_steps"] == 5
