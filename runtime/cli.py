import argparse
import json
import sys
from pathlib import Path

from runtime.config import Config
from runtime.engine import AgentRuntime
from runtime.providers import create_provider
from runtime.storage import TaskStore
from runtime.tools import ToolRegistry


def approve_overwrite(path: str) -> bool:
    """Ask the local user before replacing different existing file contents."""
    if not sys.stdin.isatty():
        print(
            f"Refusing to overwrite {path!r}: no interactive terminal is available.",
            file=sys.stderr,
        )
        return False
    try:
        answer = input(
            f"The agent wants to replace existing file {path!r}. "
            "This cannot be automatically undone. Approve? [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def main() -> int:
    parser = argparse.ArgumentParser(description="A small durable runtime for tool-using AI tasks.")
    commands = parser.add_subparsers(dest="command", required=True)

    run_parser = commands.add_parser("run", help="start a new task")
    run_parser.add_argument("description", help="what the agent should do")

    resume_parser = commands.add_parser("resume", help="resume a stored task")
    resume_parser.add_argument("task_id")
    resume_parser.add_argument(
        "--retry-uncertain", action="store_true",
        help="explicitly retry a tool action whose previous outcome is uncertain",
    )

    status_parser = commands.add_parser("status", help="show a task and its steps")
    status_parser.add_argument("task_id")

    commands.add_parser("list", help="list recent tasks")

    args = parser.parse_args()
    try:
        config = Config.from_environment()
        store = TaskStore(config.database)
        try:
            if args.command == "list":
                print(json.dumps(store.list_tasks(), indent=2, ensure_ascii=False))
                return 0
            if args.command == "status":
                task = store.get_task(args.task_id)
                if not task:
                    print(f"Task not found: {args.task_id}", file=sys.stderr)
                    return 1
                total_steps = store.step_count(args.task_id)
                steps = store.get_steps(args.task_id, limit=100) if total_steps else []
                details = {"task": task, "steps": steps}
                omitted_steps = total_steps - len(steps)
                if omitted_steps:
                    details["omitted_steps"] = omitted_steps
                print(json.dumps(details, indent=2, ensure_ascii=False))
                return 0

            workspace = config.workspace
            if args.command == "resume":
                task = store.get_task(args.task_id)
                if not task:
                    print(f"Task not found: {args.task_id}", file=sys.stderr)
                    return 1
                if task.get("workspace_path"):
                    workspace = Path(task["workspace_path"])
                    if not workspace.is_dir():
                        raise RuntimeError(f"Saved workspace does not exist: {workspace}")

            model = create_provider(config)
            runtime = AgentRuntime(
                store,
                ToolRegistry(workspace, approval_callback=approve_overwrite),
                model,
                config.max_steps,
            )
            if args.command == "run":
                task_id = runtime.create_task(args.description)
                print(f"Task ID: {task_id}")
            else:
                task_id = args.task_id
            retry_uncertain = args.command == "resume" and args.retry_uncertain
            if retry_uncertain:
                if not sys.stdin.isatty():
                    raise RuntimeError("Uncertain-action retry requires an interactive terminal. Inspect the task first.")
                answer = input(
                    "The action may already have completed before interruption. Inspect its target first. "
                    "Retry anyway? [y/N] "
                )
                if answer.strip().lower() not in {"y", "yes"}:
                    print("Resume cancelled.")
                    return 1
            result = runtime.run(task_id, retry_uncertain=retry_uncertain)
            print(f"Status: {result['status']}")
            if result.get("final_response"):
                print(result["final_response"])
            if result.get("error_text"):
                print(f"Error: {result['error_text']}", file=sys.stderr)
                return 1
            return 0
        finally:
            store.close()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
