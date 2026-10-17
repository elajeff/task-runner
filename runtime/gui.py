"""Desktop interface for task runner."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk, filedialog
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from runtime.config import Config, app_data_root, env_file_path
from runtime.engine import AgentRuntime
from runtime.documents import (
    DOCUMENT_OUTPUT_LABELS, SUPPORTED_DOCUMENT_EXTENSIONS, SUPPORTED_DOCUMENT_LABEL,
    IMAGE_EXTENSIONS, create_document_job, list_resumable_document_jobs,
    load_document_job, process_document_job,
)
from runtime.providers import create_provider
from runtime.results_view import build_results_page
from runtime.settings import (
    PROVIDER_SETTINGS, load_provider_settings, save_provider_settings, save_workspace_path,
)
from runtime.storage import TaskStore
from runtime.tools import ToolRegistry


ENV_PATH = env_file_path()


def _apply_app_icon(root: tk.Tk) -> None:
    """Use the bundled icon for the title bar and Windows taskbar when available."""
    if getattr(sys, "frozen", False):
        resource_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        resource_root = Path(__file__).resolve().parent.parent
    icon_path = resource_root / "assets" / "task-runner.ico"
    if not icon_path.is_file():
        return
    try:
        root.iconbitmap(default=str(icon_path))
    except tk.TclError:
        # Keep the GUI usable if Windows or Tk cannot load the optional icon.
        return


class RuntimeWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("task runner")
        _apply_app_icon(self.root)
        self.root.geometry("1040x790")
        self.root.minsize(850, 650)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.busy = False
        self.current_task_id: str | None = None
        self.last_document_dir: Path | None = None
        self.settings_cache: dict[str, dict[str, str | bool]] = {}
        self.default_workspace = (app_data_root() / "workspace").resolve()
        self.document_workspace = self.default_workspace
        self.current_workspace = self.default_workspace

        self._load_settings_cache()
        self.workspace_path_var = tk.StringVar(value=str(self.default_workspace))
        self._build_ui()
        _center_window(self.root)
        workspace_dir = self.default_workspace
        try:
            config = Config.from_environment()
            workspace_dir = config.workspace
            workspace_dir.mkdir(parents=True, exist_ok=True)
            self.current_workspace = workspace_dir
            self.workspace_path_var.set(str(workspace_dir))
            with TaskStore(config.database) as store:
                store.recover_interrupted_tasks()
        except Exception as exc:
            self.status_var.set(f"Recovery scan warning: {_friendly_error(exc)}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._populate_provider_form(self.active_provider)
        self._show_provider_fields()
        # Document results always stay under task runner's own workspace, even when
        # the user selects another project folder for Agent tasks. Check the active
        # folder as well for older runs created before this separation.
        self._remove_legacy_result_indexes(self.document_workspace, workspace_dir)
        self.last_document_dir = self._find_latest_document_dir(self.document_workspace)
        if workspace_dir != self.document_workspace:
            older_results = self._find_latest_document_dir(workspace_dir)
            if older_results and (
                self.last_document_dir is None
                or older_results.stat().st_mtime > self.last_document_dir.stat().st_mtime
            ):
                self.last_document_dir = older_results
        self.refresh_tasks()
        self._poll_events()
        self.root.after(2000, self._periodic_refresh)

    def _load_settings_cache(self) -> None:
        values = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
        selected = str(os.environ.get("AGENT_PROVIDER", values.get("AGENT_PROVIDER") or "gemini"))
        if selected not in PROVIDER_SETTINGS:
            # Migrate unsupported provider choices from older local .env files.
            selected = "gemini"
            os.environ["AGENT_PROVIDER"] = selected
        for provider in PROVIDER_SETTINGS:
            self.settings_cache[provider] = load_provider_settings(ENV_PATH, provider)
        self.selected_provider = selected
        self.active_provider = selected

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="task runner", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text="Extract text locally, create summaries and other AI outputs, or ask the agent to work across files.",
        ).pack(anchor="w", pady=(3, 0))

        pages = ttk.Notebook(outer)
        pages.pack(fill="both", expand=True, pady=(0, 8))
        document_tab = ttk.Frame(pages, padding=10)
        task_tab = ttk.Frame(pages, padding=10)
        settings_tab = ttk.Frame(pages, padding=10)
        pages.add(document_tab, text="Document tools")
        pages.add(task_tab, text="Agent tasks")
        pages.add(settings_tab, text="Provider settings")

        settings = ttk.LabelFrame(settings_tab, text="AI provider", padding=10)
        settings.pack(fill="x", pady=(0, 10))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        ttk.Label(settings, text="Provider").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        gui_providers = dict(PROVIDER_SETTINGS)
        self.provider_label_to_key = {
            ("Compatible API (advanced)" if key == "openai_compatible" else entry["label"]): key
            for key, entry in gui_providers.items()
        }
        self.provider_key_to_label = {key: label for label, key in self.provider_label_to_key.items()}
        self.provider_var = tk.StringVar(value=self.provider_key_to_label[self.selected_provider])
        self.provider_combo = ttk.Combobox(
            settings,
            textvariable=self.provider_var,
            values=list(self.provider_label_to_key.keys()),
            state="readonly",
            width=23,
        )
        self.provider_combo.grid(row=0, column=1, sticky="ew", padx=(0, 18), pady=4)
        self.provider_combo.bind("<<ComboboxSelected>>", self._on_provider_changed)

        ttk.Label(settings, text="Model").grid(row=0, column=2, sticky="w", padx=(0, 8), pady=4)
        self.model_var = tk.StringVar()
        self.model_entry = ttk.Entry(settings, textvariable=self.model_var)
        self.model_entry.grid(row=0, column=3, sticky="ew", pady=4)

        self.api_key_label = ttk.Label(settings, text="API key")
        self.api_key_label.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.api_key_var = tk.StringVar()
        self.api_key_entry = ttk.Entry(settings, textvariable=self.api_key_var, show="•")
        self.api_key_entry.grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=4)

        self.base_url_label = ttk.Label(settings, text="Server address")
        self.base_url_label.grid(row=1, column=2, sticky="w", padx=(0, 8), pady=4)
        self.base_url_var = tk.StringVar()
        self.base_url_entry = ttk.Entry(settings, textvariable=self.base_url_var)
        self.base_url_entry.grid(row=1, column=3, sticky="ew", pady=4)

        # This setting is only relevant for some OpenAI-compatible endpoints.
        self.json_mode_var = tk.BooleanVar(value=True)
        self.json_mode_check = ttk.Checkbutton(
            settings, text="Require JSON responses (advanced)", variable=self.json_mode_var
        )
        self.json_mode_check.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 2))

        self.provider_hint = ttk.Label(settings, text="", wraplength=780)
        self.provider_hint.grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 6))

        setting_buttons = ttk.Frame(settings)
        setting_buttons.grid(row=4, column=0, columnspan=4, sticky="ew")
        self.save_button = ttk.Button(setting_buttons, text="Save settings", command=self.save_settings)
        self.save_button.pack(side="left")
        ttk.Label(
            setting_buttons,
            text="Settings are saved in the local .env file. Do not commit it to Git.",
        ).pack(side="left", padx=(12, 0))

        task_frame = ttk.LabelFrame(task_tab, text="Custom file tasks", padding=10)
        task_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(
            task_frame,
            text="Use the agent for custom work across files. For one document, use Document tools.",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        ttk.Label(task_frame, text="Current working folder:").pack(anchor="w")
        ttk.Label(task_frame, textvariable=self.workspace_path_var, wraplength=780).pack(anchor="w", pady=(2, 6))
        workspace_buttons = ttk.Frame(task_frame)
        workspace_buttons.pack(fill="x", pady=(0, 8))
        self.open_workspace_button = ttk.Button(
            workspace_buttons, text="Open working folder", command=self.open_workspace
        )
        self.open_workspace_button.pack(side="left")
        self.choose_workspace_button = ttk.Button(
            workspace_buttons, text="Choose a different folder…", command=self.choose_workspace
        )
        self.choose_workspace_button.pack(side="left", padx=(8, 0))
        self.default_workspace_button = ttk.Button(
            workspace_buttons, text="Use task runner's default", command=self.use_default_workspace
        )
        self.default_workspace_button.pack(side="left", padx=(8, 0))
        ttk.Label(
            task_frame,
            text="Choose the folder the agent can use. It reads and writes text files but cannot run programs. File text may be sent to your AI provider.",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            task_frame,
            text="Describe the result you need. You can omit filenames; the agent can list files first.",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))
        self.task_text = tk.Text(task_frame, height=4, wrap="word")
        self.task_text.pack(fill="x", pady=(5, 4))
        ttk.Label(
            task_frame,
            text='Example: "Compare the files in meeting-notes/ and save action items to action-items.md. Do not overwrite existing files."',
            wraplength=780,
        ).pack(anchor="w", pady=(0, 8))
        task_buttons = ttk.Frame(task_frame)
        task_buttons.pack(fill="x")
        self.run_button = ttk.Button(task_buttons, text="Run new task", command=self.run_task)
        self.run_button.pack(side="left")
        self.resume_button = ttk.Button(task_buttons, text="Resume selected task", command=self.resume_selected_task)
        self.resume_button.pack(side="left", padx=(8, 0))
        self.refresh_button = ttk.Button(task_buttons, text="Refresh tasks", command=self.refresh_tasks)
        self.refresh_button.pack(side="left", padx=(8, 0))

        document_frame = ttk.LabelFrame(document_tab, text="Document tools", padding=8)
        document_frame.pack(fill="x", pady=(0, 10))

        document_row = ttk.Frame(document_frame)
        document_row.pack(fill="x")
        self.document_path_var = tk.StringVar()
        self.document_path_var.trace_add("write", self._on_document_path_changed)
        ttk.Entry(document_row, textvariable=self.document_path_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(document_row, text="Choose file…", command=self.choose_document).pack(
            side="left", padx=(6, 0)
        )

        tool_sections = ttk.Frame(document_frame)
        tool_sections.pack(fill="x", pady=(8, 0))
        tool_sections.columnconfigure(0, weight=1, uniform="document-tools")
        tool_sections.columnconfigure(1, weight=1, uniform="document-tools")

        local_frame = ttk.LabelFrame(tool_sections, text="Local tools (no AI needed)", padding=8)
        local_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        local_frame.columnconfigure(0, weight=1)
        ttk.Label(
            local_frame,
            text="Extract a PDF, Word document, spreadsheet, CSV/TSV, text file, or image without AI.",
            wraplength=355,
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.ocr_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            local_frame,
            text="Use OCR for scanned PDFs and images",
            variable=self.ocr_var,
        ).grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(
            local_frame,
            text=(
                "OCR supports Latin, Cyrillic, Greek, Devanagari, Bengali, and simplified/traditional Chinese. "
                "Clear printed text works best. PDFs with selectable text support many more scripts."
            ),
            wraplength=355,
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(2, 0))
        self.local_button = ttk.Button(
            local_frame,
            text="Extract text",
            command=lambda: self.process_document("local"),
        )
        self.local_button.grid(row=3, column=0, sticky="w", pady=(8, 0))

        ai_frame = ttk.LabelFrame(tool_sections, text="AI tools", padding=8)
        ai_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ai_frame.columnconfigure(0, weight=1)
        ai_frame.columnconfigure(1, weight=1)
        ttk.Label(
            ai_frame,
            text=(
                "Uses your selected AI provider and its available quota. Hosted services may charge for requests."
            ),
            wraplength=355,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        self.ai_output_vars = {
            "summary": tk.BooleanVar(value=False),
            "notes": tk.BooleanVar(value=False),
            "definitions": tk.BooleanVar(value=False),
            "questions": tk.BooleanVar(value=False),
        }
        ai_options = (
            ("summary", "Summary"),
            ("notes", "Detailed notes"),
            ("definitions", "Key definitions"),
            ("questions", "Questions & answers"),
        )
        for index, (key, label) in enumerate(ai_options):
            ttk.Checkbutton(ai_frame, text=label, variable=self.ai_output_vars[key]).grid(
                row=1 + index // 2,
                column=index % 2,
                sticky="w",
                padx=(0, 10),
                pady=2,
            )
        self.ai_button = ttk.Button(
            ai_frame,
            text="Generate AI outputs",
            command=lambda: self.process_document("ai"),
        )
        self.ai_button.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        document_actions = ttk.Frame(document_frame)
        document_actions.pack(fill="x", pady=(7, 0))
        ttk.Label(
            document_actions,
            text="Local extraction and OCR do not use AI quota.",
        ).pack(side="left")
        self.resume_document_button = ttk.Button(
            document_actions,
            text="Resume unfinished job…",
            command=self.resume_saved_document_job,
        )
        self.resume_document_button.pack(side="right")
        self.open_results_button = ttk.Button(
            document_actions,
            text="Open latest results",
            command=self.open_latest_results,
        )
        self.open_results_button.pack(side="right", padx=(0, 8))
        self.view_results_button = ttk.Button(
            document_actions,
            text="View latest results",
            command=self.view_latest_results,
        )
        self.view_results_button.pack(side="left", padx=(12, 0))
        self.browse_results_button = ttk.Button(
            document_actions,
            text="Browse all results",
            command=self.browse_all_results,
        )
        self.browse_results_button.pack(side="right", padx=(0, 8))

        task_area = ttk.Frame(task_tab)
        task_area.pack(fill="both", expand=True)
        task_area.columnconfigure(0, weight=1)
        task_area.columnconfigure(1, weight=1)
        task_area.rowconfigure(0, weight=1)

        list_frame = ttk.LabelFrame(task_area, text="Recent tasks", padding=6)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        columns = ("status", "description")
        self.task_tree = ttk.Treeview(list_frame, columns=columns, show="tree headings", height=12)
        self.task_tree.heading("#0", text="Task ID")
        self.task_tree.heading("status", text="Status")
        self.task_tree.heading("description", text="Description")
        self.task_tree.column("#0", width=105, stretch=False)
        self.task_tree.column("status", width=90, stretch=False)
        self.task_tree.column("description", width=260, stretch=True)
        tree_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=tree_scroll.set)
        self.task_tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.task_tree.bind("<<TreeviewSelect>>", self._on_task_selected)

        detail_frame = ttk.LabelFrame(task_area, text="Task details and step history", padding=6)
        detail_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        self.details = scrolledtext.ScrolledText(detail_frame, wrap="word", state="disabled", height=12)
        self.details.grid(row=0, column=0, sticky="nsew")

        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(outer, textvariable=self.status_var, anchor="w", relief="sunken", padding=(7, 4))
        status_bar.pack(fill="x", pady=(10, 0))

    def _on_document_path_changed(self, *_args: str) -> None:
        path = self.document_path_var.get().strip()
        if path and Path(path).suffix.lower() in IMAGE_EXTENSIONS:
            # An image has no selectable text layer, so OCR is required.
            self.ocr_var.set(True)

    def choose_document(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose a document",
            filetypes=[
                ("Supported documents", " ".join(f"*{extension}" for extension in SUPPORTED_DOCUMENT_EXTENSIONS)),
                ("All files", "*.*"),
            ],
        )
        if selected:
            self.document_path_var.set(selected)

    def open_workspace(self) -> None:
        """Open the active agent working folder in the system file manager."""
        folder = Path(self.workspace_path_var.get()).expanduser()
        if not folder.is_dir():
            messagebox.showerror("Working folder not found", f"The folder does not exist:\n\n{folder}", parent=self.root)
            return
        try:
            _open_directory(folder)
        except OSError as exc:
            messagebox.showerror("Could not open working folder", str(exc), parent=self.root)

    def choose_workspace(self) -> None:
        """Let the user point the agent at an existing project folder directly."""
        initial = self.current_workspace if self.current_workspace.is_dir() else self.default_workspace
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Choose the folder the agent can work in",
            initialdir=str(initial),
            mustexist=True,
        )
        if not selected:
            return
        workspace = Path(selected).expanduser().resolve()
        try:
            save_workspace_path(ENV_PATH, workspace, app_data_root())
        except Exception as exc:
            messagebox.showerror("Could not save working folder", _friendly_error(exc), parent=self.root)
            return
        self.current_workspace = workspace
        self.workspace_path_var.set(str(workspace))
        self.status_var.set("Agent working folder updated.")

    def use_default_workspace(self) -> None:
        """Restore the portable workspace located beside task runner's source."""
        try:
            save_workspace_path(ENV_PATH, self.default_workspace, app_data_root())
            self.default_workspace.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("Could not restore default folder", _friendly_error(exc), parent=self.root)
            return
        self.current_workspace = self.default_workspace
        self.workspace_path_var.set(str(self.default_workspace))
        self.status_var.set("Using task runner's default working folder.")

    def process_document(self, mode: str) -> None:
        if self.busy:
            return
        if mode not in {"local", "ai"}:
            raise ValueError(f"Unknown document processing mode: {mode}")

        source_text = self.document_path_var.get().strip()
        if mode == "local":
            selected = ["verbatim"]
        else:
            selected = [key for key, variable in self.ai_output_vars.items() if variable.get()]
        if not source_text:
            messagebox.showwarning(
                "File required",
                f"Choose a supported file first: {SUPPORTED_DOCUMENT_LABEL}.",
                parent=self.root,
            )
            return
        if not selected:
            messagebox.showwarning("Output required", "Select at least one AI output.", parent=self.root)
            return
        if mode == "ai" and not self.save_settings(quiet=True):
            return

        try:
            job_dir = create_document_job(
                Path(source_text),
                selected,
                self.ocr_var.get(),
                self.document_workspace / "document_outputs",
            )
        except Exception as exc:
            messagebox.showerror("Could not start document processing", _friendly_error(exc), parent=self.root)
            return
        self._start_document_worker(job_dir)

    @staticmethod
    def _remove_legacy_result_indexes(*workspaces: Path) -> None:
        """Remove obsolete START_HERE files only from recognizable saved document jobs."""
        state_markers = (
            ".task-runner-document.json",
            ".task-runner-study.json",
            ".taskrunner-study.json",
        )
        roots_seen: set[Path] = set()
        for workspace in workspaces:
            if not workspace:
                continue
            for folder_name in ("document_outputs", "study_outputs"):
                output_root = Path(workspace) / folder_name
                if output_root in roots_seen:
                    continue
                roots_seen.add(output_root)
                try:
                    folders = list(output_root.iterdir())
                except OSError:
                    continue
                for folder in folders:
                    legacy_index = folder / "START_HERE.txt"
                    if not folder.is_dir() or not legacy_index.is_file():
                        continue
                    if not any((folder / marker).is_file() for marker in state_markers):
                        continue
                    try:
                        legacy_index.unlink()
                    except OSError:
                        # A locked file should not prevent the application from starting.
                        continue

    @staticmethod
    def _find_latest_document_dir(workspace: Path | None) -> Path | None:
        if workspace is None:
            return None
        candidates: list[Path] = []
        for folder_name in ("document_outputs", "study_outputs"):
            output_root = workspace / folder_name
            try:
                for child in output_root.iterdir():
                    if child.is_dir() and (
                        (child / "START_HERE.txt").is_file()
                        or any(
                            (child / marker).is_file()
                            for marker in (
                                ".task-runner-document.json",
                                ".task-runner-study.json",
                                ".taskrunner-study.json",
                            )
                        )
                    ):
                        candidates.append(child)
            except OSError:
                continue
        if not candidates:
            return None
        try:
            return max(candidates, key=lambda folder: folder.stat().st_mtime)
        except OSError:
            return None

    def open_latest_results(self) -> None:
        """Open the exact folder containing results from the latest document run."""
        folder = self.last_document_dir
        if folder is None or not folder.is_dir():
            folder = self._find_latest_document_dir(self.document_workspace)
            self.last_document_dir = folder
        if folder is None or not folder.is_dir():
            messagebox.showinfo(
                "No document results yet",
                f"No results yet. Choose a file ({SUPPORTED_DOCUMENT_LABEL}) and use Extract text or "
                "Generate AI outputs first. Then click Open latest results to open its folder.",
                parent=self.root,
            )
            return
        try:
            _open_directory(folder)
        except OSError as exc:
            messagebox.showerror("Could not open results folder", str(exc), parent=self.root)

    def view_latest_results(self) -> None:
        """Open the formatted preview without making users find a Markdown file."""
        folder = self.last_document_dir
        if folder is None or not folder.is_dir():
            folder = self._find_latest_document_dir(self.document_workspace)
            self.last_document_dir = folder
        if folder is None or not folder.is_dir():
            messagebox.showinfo(
                "No results yet",
                "Choose a document, then use Extract text or Generate AI outputs. "
                "Your results will be ready to view here after processing.",
                parent=self.root,
            )
            return
        try:
            preview = build_results_page(folder)
            if preview is None:
                messagebox.showinfo(
                    "No saved outputs yet",
                    "This job has not saved any results yet. If it was interrupted, use "
                    "Resume unfinished job… and try viewing the results again afterward.",
                    parent=self.root,
                )
                return
            _open_file(preview)
        except Exception as exc:
            messagebox.showerror(
                "Could not open results preview",
                f"The outputs may still be saved in this folder:\n\n{folder}\n\n{_friendly_error(exc)}",
                parent=self.root,
            )

    def _choose_results_destination(self, preview: Path) -> None:
        """Ask whether to view formatted output or open the containing folder."""
        choice = _ask_results_destination(self.root)
        try:
            if choice == "browser":
                _open_file(preview)
            elif choice == "folder" and self.last_document_dir is not None:
                _open_directory(self.last_document_dir)
        except OSError as exc:
            location = preview if choice == "browser" else self.last_document_dir
            messagebox.showerror(
                "Could not open results",
                f"Your results are saved at:\n\n{location}\n\n{_friendly_error(exc)}",
                parent=self.root,
            )

    def browse_all_results(self) -> None:
        """Open the directory containing document-run folders, when results exist."""
        roots = [
            self.document_workspace / "document_outputs",
            self.document_workspace / "study_outputs",  # compatibility with earlier versions
        ]
        try:
            existing_roots = [
                root for root in roots
                if root.is_dir() and any(child.is_dir() for child in root.iterdir())
            ]
        except OSError as exc:
            messagebox.showerror("Could not inspect results folder", str(exc), parent=self.root)
            return
        if not existing_roots:
            messagebox.showinfo(
                "No document results yet",
                f"No results yet. Choose a file ({SUPPORTED_DOCUMENT_LABEL}) and use Extract text or "
                "Generate AI outputs first. Your results will appear here after processing.",
                parent=self.root,
            )
            return
        # Prefer the current folder layout. Fall back to the legacy folder if that's
        # where a user's older results are stored.
        folder = existing_roots[0]
        try:
            _open_directory(folder)
        except OSError as exc:
            messagebox.showerror("Could not open results directory", str(exc), parent=self.root)

    def resume_saved_document_job(self) -> None:
        if self.busy:
            return
        try:
            config = Config.from_environment()
            jobs = []
            # New document outputs live in task runner's own workspace; also inspect the
            # active folder to preserve compatibility with jobs from older versions.
            workspaces = list(dict.fromkeys([self.document_workspace, config.workspace]))
            for workspace in workspaces:
                for folder_name in ("document_outputs", "study_outputs"):
                    jobs.extend(list_resumable_document_jobs(workspace / folder_name))
            jobs.sort(key=lambda job: job.get("updated_at", ""), reverse=True)
        except Exception as exc:
            messagebox.showerror("Could not inspect saved jobs", _friendly_error(exc), parent=self.root)
            return
        if not jobs:
            messagebox.showinfo(
                "No incomplete jobs",
                "There are no interrupted or incomplete document-processing jobs.",
                parent=self.root,
            )
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Resume a document job")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("690x330")
        ttk.Label(
            dialog,
            text=(
                "Choose an incomplete job. task runner saves extracted text and completed "
                "AI sections so they can be reused on resume."
            ),
            wraplength=650,
        ).pack(anchor="w", padx=12, pady=(12, 8))
        listbox = tk.Listbox(dialog, height=10, exportselection=False)
        listbox.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        for job in jobs:
            labels = ", ".join(DOCUMENT_OUTPUT_LABELS.get(key, key) for key in job.get("selected", []))
            last = job.get("last_completed_step") or "No completed step saved"
            stage = job.get("stage", "unknown stage")
            current = job.get("current_section")
            position = f"current section {current}" if current else f"stage: {stage}"
            description = (
                f"{Path(job['source']).name} | {job.get('status', 'unknown')} | {position} | "
                f"Last completed: {last} | Outputs: {labels}"
            )
            listbox.insert("end", description)
        listbox.selection_set(0)
        listbox.activate(0)

        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=12, pady=(0, 12))

        def resume_choice() -> None:
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("Select a job", "Select a job to resume first.", parent=dialog)
                return
            job = jobs[selection[0]]
            has_ai_outputs = any(key != "verbatim" for key in job.get("selected", []))
            if has_ai_outputs and not self.save_settings(quiet=True):
                return
            self.document_path_var.set(job["source"])
            self.ocr_var.set(bool(job.get("use_ocr")))
            for key, variable in self.ai_output_vars.items():
                variable.set(key in job.get("selected", []))
            dialog.destroy()
            self._start_document_worker(Path(job["job_dir"]))

        ttk.Button(buttons, text="Resume selected job", command=resume_choice).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")

    def _start_document_worker(self, job_dir: Path) -> None:
        try:
            saved = load_document_job(job_dir)
        except Exception as exc:
            messagebox.showerror(
                "Could not read saved document job",
                _friendly_error(exc),
                parent=self.root,
            )
            return
        is_resume = saved.get("status") != "pending"
        self.last_document_dir = job_dir
        self._set_busy(True, "Resuming document job…" if is_resume else "Processing document…")

        def work() -> None:
            try:
                current = load_document_job(job_dir)
                ai_selected = any(key != "verbatim" for key in current.get("selected", []))
                provider = create_provider(Config.from_environment()) if ai_selected else None
                result_dir = process_document_job(
                    job_dir,
                    (lambda prompt: provider.generate_json(prompt)) if provider is not None else None,
                    progress=lambda message: self.events.put(("document_progress", message)),
                )
                self.events.put(("document_finished", str(result_dir)))
            except Exception as exc:
                self.events.put(("document_failed", {"error": _friendly_error(exc), "job_dir": str(job_dir)}))

        threading.Thread(target=work, daemon=True, name="document-processing").start()

    def _selected_provider(self) -> str:
        label = self.provider_var.get()
        try:
            return self.provider_label_to_key[label]
        except KeyError as exc:
            raise ValueError(f"Unknown provider selection: {label}") from exc

    def _populate_provider_form(self, provider: str) -> None:
        settings = self.settings_cache.get(provider) or load_provider_settings(ENV_PATH, provider)
        self.model_var.set(str(settings.get("model", "")))
        self.api_key_var.set(str(settings.get("api_key", "")))
        self.base_url_var.set(str(settings.get("base_url", "")))
        self.json_mode_var.set(bool(settings.get("json_mode", True)))

    def _on_provider_changed(self, _event: object = None) -> None:
        # Tk updates the combobox variable before emitting this event, so cache the
        # previous form under active_provider rather than the newly selected provider.
        self._cache_current_form(self.active_provider)
        provider = self._selected_provider()
        self._populate_provider_form(provider)
        self.active_provider = provider
        self._show_provider_fields()

    def _cache_current_form(self, provider: str | None = None) -> None:
        provider = provider or self.active_provider
        self.settings_cache[provider] = {
            "provider": provider,
            "model": self.model_var.get().strip(),
            "api_key": self.api_key_var.get(),
            "base_url": self.base_url_var.get().strip(),
            "json_mode": self.json_mode_var.get(),
        }

    def _show_provider_fields(self) -> None:
        provider = self._selected_provider()
        metadata = PROVIDER_SETTINGS[provider]
        api_enabled = metadata["api_key_key"] is not None
        base_enabled = metadata["base_url_key"] is not None

        if api_enabled:
            self.api_key_label.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
            self.api_key_entry.grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=4)
        else:
            self.api_key_label.grid_remove()
            self.api_key_entry.grid_remove()

        if base_enabled:
            base_column = 2 if api_enabled else 0
            entry_column = base_column + 1
            self.base_url_label.grid(row=1, column=base_column, sticky="w", padx=(0, 8), pady=4)
            self.base_url_entry.grid(row=1, column=entry_column, sticky="ew", pady=4)
        else:
            self.base_url_label.grid_remove()
            self.base_url_entry.grid_remove()

        if metadata["json_mode_key"]:
            self.json_mode_check.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 2))
        else:
            self.json_mode_check.grid_remove()

        hints = {
            "gemini": "",
            "openai": "",
            "anthropic": "",
            "ollama": "Ollama runs on this computer. Start Ollama and install the selected model first.",
            "openai_compatible": (
                "For a compatible server such as LM Studio. Hosted services may charge for requests."
            ),
        }
        self.provider_hint.configure(text=hints.get(provider, ""))

    def save_settings(self, quiet: bool = False) -> bool:
        provider = self._selected_provider()
        self._cache_current_form(provider)
        values = self.settings_cache[provider]
        if not str(values.get("model", "")).strip():
            messagebox.showerror("Model required", "Enter the model ID for the selected provider.", parent=self.root)
            return False
        try:
            save_provider_settings(ENV_PATH, provider, values)
        except Exception as exc:
            messagebox.showerror("Could not save settings", str(exc), parent=self.root)
            return False
        self.status_var.set(f"Saved {PROVIDER_SETTINGS[provider]['label']} settings locally.")
        if not quiet:
            messagebox.showinfo(
                "Settings saved",
                "Settings were saved locally in .env. Keep this file private and out of Git.",
                parent=self.root,
            )
        return True

    def run_task(self) -> None:
        if self.busy:
            return
        description = self.task_text.get("1.0", "end").strip()
        if not description:
            messagebox.showwarning("Task required", "Enter a task description first.", parent=self.root)
            return
        if not self.save_settings(quiet=True):
            return
        self._start_task_worker(description=description)

    def resume_selected_task(self) -> None:
        if self.busy:
            return
        selection = self.task_tree.selection()
        if not selection:
            messagebox.showinfo("Select a task", "Select a task in the list first.", parent=self.root)
            return
        if not self.save_settings(quiet=True):
            return
        try:
            config = Config.from_environment()
            with TaskStore(config.database) as store:
                task = store.get_task(selection[0])
                uncertain = store.get_uncertain_step(selection[0])
                running = store.get_running_step(selection[0])
            if task is None:
                messagebox.showerror("Task not found", "The selected task no longer exists.", parent=self.root)
                return
            saved_workspace = task.get("workspace_path")
            if not saved_workspace and not messagebox.askyesno(
                "Working folder not recorded",
                "This task was created by an older version and does not save its working folder. "
                "It will use the current folder shown in Agent tasks:\n\n"
                f"{config.workspace}\n\nResume using this folder?",
                parent=self.root,
            ):
                return
            if saved_workspace and not Path(saved_workspace).is_dir():
                messagebox.showerror(
                    "Working folder not found",
                    "This task was created for a folder that is no longer available:\n\n"
                    f"{saved_workspace}\n\nChoose or restore that folder before resuming the task.",
                    parent=self.root,
                )
                return
        except Exception as exc:
            messagebox.showerror("Could not inspect task", _friendly_error(exc), parent=self.root)
            return
        retry_uncertain = bool(uncertain or running)
        if retry_uncertain and not messagebox.askyesno(
            "Previous action may have completed",
            "A saved action has no recorded outcome. It may already have changed a file before the interruption. "
            "Inspect the target first. Retry this action anyway?",
            parent=self.root,
        ):
            return
        self._start_task_worker(
            task_id=selection[0],
            retry_uncertain=retry_uncertain,
            workspace_path=saved_workspace,
        )

    def _request_overwrite_approval(self, relative_path: str) -> bool:
        """Request confirmation on the Tk main thread while the worker waits."""
        decision = {"approved": False}
        response_event = threading.Event()
        self.events.put(("overwrite_approval_requested", (relative_path, response_event, decision)))
        if not response_event.wait(timeout=300):
            return False
        return bool(decision["approved"])

    def _start_task_worker(
        self,
        description: str | None = None,
        task_id: str | None = None,
        retry_uncertain: bool = False,
        workspace_path: str | None = None,
    ) -> None:
        self._set_busy(True, "Running task…")

        def work() -> None:
            try:
                config = Config.from_environment()
                task_workspace = Path(workspace_path).expanduser().resolve() if workspace_path else config.workspace
                if task_id and workspace_path and not task_workspace.is_dir():
                    raise FileNotFoundError(
                        f"The saved task's working folder is unavailable: {task_workspace}"
                    )
                with TaskStore(config.database) as store:
                    runtime = AgentRuntime(
                        store,
                        ToolRegistry(
                            task_workspace,
                            approval_callback=self._request_overwrite_approval,
                        ),
                        create_provider(config),
                        config.max_steps,
                    )
                    current_id = task_id
                    if description is not None:
                        current_id = runtime.create_task(description)
                    if not current_id:
                        raise ValueError("No task was selected.")
                    self.events.put(("task_started", current_id))
                    result = runtime.run(current_id, retry_uncertain=retry_uncertain)
                    self.events.put(("task_finished", result))
            except Exception as exc:
                self.events.put(("task_failed", {"task_id": task_id, "error": _friendly_error(exc)}))

        threading.Thread(target=work, daemon=True, name="agent-task").start()

    def refresh_tasks(self) -> None:
        try:
            config = Config.from_environment()
            with TaskStore(config.database) as store:
                tasks = store.list_tasks(limit=50)
        except Exception as exc:
            self.status_var.set(f"Could not load tasks: {_friendly_error(exc)}")
            return

        selected = self.task_tree.selection()
        selected_id = selected[0] if selected else self.current_task_id
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        for task in tasks:
            description = task["description"].replace("\n", " ")
            self.task_tree.insert(
                "", "end", iid=task["id"], text=task["id"],
                values=(task["status"], description),
            )
        if selected_id and self.task_tree.exists(selected_id):
            self.task_tree.selection_set(selected_id)
            self.task_tree.focus(selected_id)
            self._display_task_details(selected_id)

    def _on_task_selected(self, _event: object = None) -> None:
        selection = self.task_tree.selection()
        if selection:
            self.current_task_id = selection[0]
            self._display_task_details(self.current_task_id)

    def _display_task_details(self, task_id: str) -> None:
        try:
            config = Config.from_environment()
            with TaskStore(config.database) as store:
                task = store.get_task(task_id)
                total_steps = store.step_count(task_id)
                steps = store.get_steps(task_id, limit=100) if total_steps else []
        except Exception as exc:
            self._set_details(f"Could not read task details: {_friendly_error(exc)}")
            return
        if not task:
            self._set_details("Task not found.")
            return
        lines = [
            f"Task ID: {task['id']}",
            f"Status: {task['status']}",
            f"Created: {task['created_at']}",
            f"Working folder: {task.get('workspace_path') or 'Not recorded (older task)'}",
            "",
            "Description:",
            task["description"],
            "",
        ]
        if task.get("final_response"):
            lines.extend(["Final response:", task["final_response"], ""])
        if task.get("error_text"):
            lines.extend(["Error:", task["error_text"], ""])
        if total_steps > len(steps):
            lines.append(f"Showing the latest {len(steps)} of {total_steps} saved steps.")
        lines.append(f"Steps ({len(steps)}):")
        for step in steps:
            lines.extend([
                f"  {step['sequence']}. {step['tool_name']} — {step['status']}",
                f"     Planned action: {step.get('planned_action') or step['tool_name']}",
                f"     Arguments: {step['arguments_json']}",
            ])
            if step.get("result_json"):
                lines.append(f"     Result: {step['result_json']}")
            if step.get("error_text"):
                lines.append(f"     Error / recovery note: {step['error_text']}")
            if step["status"] == "uncertain":
                lines.append("     Recovery: inspect the target before explicitly retrying this action.")
        self._set_details("\n".join(lines))

    def _set_details(self, text: str) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _set_busy(self, busy: bool, message: str) -> None:
        self.busy = busy
        self.status_var.set(message)
        state = "disabled" if busy else "normal"
        self.run_button.configure(state=state)
        self.resume_button.configure(state=state)
        self.save_button.configure(state=state)
        if hasattr(self, "open_workspace_button"):
            self.open_workspace_button.configure(state=state)
            self.choose_workspace_button.configure(state=state)
            self.default_workspace_button.configure(state=state)
        self.local_button.configure(state=state)
        self.ai_button.configure(state=state)
        self.resume_document_button.configure(state=state)
        if hasattr(self, "open_results_button"):
            self.open_results_button.configure(state=state)
            self.view_results_button.configure(state=state)
            self.browse_results_button.configure(state=state)

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "document_progress":
                    self.status_var.set(payload)
                elif event == "document_finished":
                    self.last_document_dir = Path(payload)
                    self._set_busy(False, "Document outputs saved.")
                    try:
                        preview = build_results_page(self.last_document_dir)
                    except Exception as exc:
                        messagebox.showwarning(
                            "Results saved",
                            f"Your files were saved, but the formatted preview could not be created.\n\n"
                            f"Folder: {self.last_document_dir}\n\n{_friendly_error(exc)}",
                            parent=self.root,
                        )
                    else:
                        if preview is not None:
                            self._choose_results_destination(preview)
                elif event == "document_failed":
                    self._set_busy(False, "Document processing stopped; saved progress is available.")
                    messagebox.showerror(
                        "Document processing stopped",
                        f"{payload['error']}\n\n"
                        f"Saved job folder:\n{payload.get('job_dir', 'unknown')}\n\n"
                        "Use 'Resume unfinished job…' to continue after fixing the problem.",
                        parent=self.root,
                    )
                elif event == "overwrite_approval_requested":
                    relative_path, response_event, decision = payload
                    self.status_var.set(f"Waiting for approval to replace {relative_path!r}…")
                    try:
                        decision["approved"] = messagebox.askyesno(
                            "Approve file overwrite?",
                            f"The agent wants to replace the existing file:\n\n{relative_path}\n\n"
                            "This replaces its current contents and cannot be automatically undone.\n"
                            "Approve this write?",
                            parent=self.root,
                        )
                    finally:
                        response_event.set()
                elif event == "task_started":
                    self.current_task_id = payload
                    self.status_var.set(f"Running task {payload}…")
                    self.refresh_tasks()
                elif event == "task_finished":
                    result = payload
                    self._set_busy(False, f"Task {result['id']} finished with status: {result['status']}.")
                    self.refresh_tasks()
                    self._show_status(f"Task {result['id']} finished: {result['status']}.")
                elif event == "task_failed":
                    self._set_busy(False, "Task failed.")
                    self.refresh_tasks()
                    error = payload.get("error", "Unknown error")
                    self._show_status(f"Task error: {error}")
                    messagebox.showerror("Task failed", error, parent=self.root)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def _show_status(self, message: str) -> None:
        self.status_var.set(f"{datetime.now().strftime('%H:%M:%S')} — {message}")

    def _periodic_refresh(self) -> None:
        self.refresh_tasks()
        self.root.after(3000, self._periodic_refresh)

    def _on_close(self) -> None:
        if self.busy:
            should_close = messagebox.askyesno(
                "Task may be interrupted",
                "An operation is still running. Closing the window may interrupt it; "
                "you can inspect or resume the task when you reopen the app. Close anyway?",
                parent=self.root,
            )
            if not should_close:
                return
        self.root.destroy()


def _ask_results_destination(parent: tk.Misc) -> str | None:
    """Show a small modal asking how the user wants to open new results."""
    dialog = tk.Toplevel(parent)
    dialog.title("Results are ready")
    dialog.transient(parent)
    dialog.resizable(False, False)
    result: dict[str, str | None] = {"choice": None}

    body = ttk.Frame(dialog, padding=18)
    body.pack(fill="both", expand=True)
    ttk.Label(
        body,
        text="Your results have been saved. How would you like to open them?",
        wraplength=360,
        justify="left",
    ).pack(anchor="w", pady=(0, 16))

    buttons = ttk.Frame(body)
    buttons.pack(fill="x")

    def choose(choice: str | None) -> None:
        result["choice"] = choice
        dialog.destroy()

    ttk.Button(buttons, text="View in browser", command=lambda: choose("browser")).pack(
        side="left", padx=(0, 8)
    )
    ttk.Button(buttons, text="Open results folder", command=lambda: choose("folder")).pack(
        side="left", padx=(0, 8)
    )
    ttk.Button(buttons, text="Not now", command=lambda: choose(None)).pack(side="right")
    dialog.protocol("WM_DELETE_WINDOW", lambda: choose(None))
    dialog.bind("<Escape>", lambda _event: choose(None))
    dialog.update_idletasks()
    width = dialog.winfo_reqwidth()
    height = dialog.winfo_reqheight()
    x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
    dialog.geometry(f"+{x}+{y}")
    dialog.grab_set()
    parent.wait_window(dialog)
    return result["choice"]


def _open_file(path: Path) -> None:
    """Open a saved document or HTML preview with its registered application."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"The result file does not exist: {path}")
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _open_directory(path: Path) -> None:
    """Open a directory with the user's normal file manager."""
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _center_window(root: tk.Tk) -> None:
    """Center the configured window on the screen after Tk has measured it."""
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"+{x}+{y}")



def _friendly_error(exc: Exception) -> str:
    """Return useful error text without exposing known configured API keys."""
    message = str(exc) or type(exc).__name__
    try:
        values = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
        for key, value in values.items():
            if "KEY" in key and value and len(value) >= 8:
                message = message.replace(str(value), "[redacted]")
    except Exception:
        pass
    return f"{type(exc).__name__}: {message}"


def main() -> int:
    root = tk.Tk()
    RuntimeWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
