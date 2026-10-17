"""A small, bounded registry of tools the model is allowed to request."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any, Callable

from filelock import FileLock, Timeout


MAX_TEXT_FILE_BYTES = 100_000
MAX_LISTED_FILES = 100
MAX_WORKSPACE_ENTRIES_SCANNED = 5_000

_BLOCKED_NAMES = {
    "credentials",
    "credentials.json",
    "secrets",
    "secrets.json",
    "token.json",
    "service-account.json",
    "id_rsa",
    "id_ed25519",
    "authorized_keys",
    "known_hosts",
    "id_rsa.pub",
    "id_ed25519.pub",
}
_BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".p7b", ".p7c"}
_WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_EXCLUDED_DIRECTORIES = {".git", ".venv", "venv", "__pycache__", "node_modules"}


class ToolError(ValueError):
    """An invalid or unsafe tool request."""


class ToolRegistry:
    def __init__(
        self,
        workspace: Path,
        approval_callback: Callable[[str], bool] | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.approval_callback = approval_callback
        self._tools: dict[str, tuple[str, Callable[[dict[str, Any]], Any]]] = {
            "list_files": (
                "List up to 100 non-hidden text files in the workspace. Takes no arguments.",
                self._list_files,
            ),
            "read_text_file": (
                "Read a UTF-8 text file by workspace-relative path. Arguments: path (string). Hidden or credential-like paths are not allowed.",
                self._read_text_file,
            ),
            "write_text_file": (
                "Write or replace a UTF-8 text file in the workspace. Arguments: path and content (strings). Replacing different existing content requires user approval.",
                self._write_text_file,
            ),
        }

    def descriptions(self) -> dict[str, str]:
        return {name: details[0] for name, details in self._tools.items()}

    def execute(self, name: str, arguments: Any) -> Any:
        if not isinstance(name, str) or name not in self._tools:
            raise ToolError(f"Tool is not allowed: {name}")
        if not isinstance(arguments, dict):
            raise ToolError("Tool arguments must be a JSON object.")
        _, function = self._tools[name]
        return function(arguments)

    def _check_arguments(self, arguments: dict[str, Any], required: set[str]) -> None:
        if any(not isinstance(key, str) for key in arguments):
            raise ToolError("Tool argument names must be strings.")
        missing = required - arguments.keys()
        extra = arguments.keys() - required
        if missing:
            raise ToolError(f"Missing argument(s): {', '.join(sorted(missing))}")
        if extra:
            raise ToolError(f"Unexpected argument(s): {', '.join(sorted(extra))}")

    @staticmethod
    def _blocked_component(component: str) -> bool:
        lowered = component.lower()
        windows_base_name = lowered.split(".", 1)[0]
        return (
            component.startswith(".")
            or ":" in component  # Avoid Windows alternate data streams.
            or lowered in _BLOCKED_NAMES
            or windows_base_name in _WINDOWS_RESERVED_NAMES
            or Path(lowered).suffix in _BLOCKED_SUFFIXES
        )

    @staticmethod
    def _is_link_or_junction(path: Path) -> bool:
        is_junction = getattr(path, "is_junction", None)
        return path.is_symlink() or (callable(is_junction) and is_junction())

    def _resolve_path(self, value: Any) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ToolError("path must be a non-empty string.")
        if "\x00" in value:
            raise ToolError("path contains an invalid null character.")
        if len(value) > 1000:
            raise ToolError("path is too long (limit: 1,000 characters).")

        relative = Path(value)
        windows_relative = PureWindowsPath(value)
        if relative.is_absolute() or windows_relative.is_absolute() or windows_relative.drive:
            raise ToolError("Only workspace-relative paths are allowed.")
        if any(part in {".", ".."} for part in relative.parts):
            raise ToolError("Use a normalized path inside the workspace; '.' and '..' are not allowed.")
        if any(self._blocked_component(part) for part in relative.parts):
            raise ToolError("Hidden or credential-like paths are not available to agent tools.")

        candidate = self.workspace
        for part in relative.parts:
            candidate = candidate / part
            # Reject symlinks even if they currently point back into the workspace.
            # This avoids surprising path changes between list/read/write operations.
            if self._is_link_or_junction(candidate):
                raise ToolError("Symbolic links and directory junctions are not available to agent tools.")
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise ToolError("The requested path could not be resolved safely.") from exc
        if resolved == self.workspace:
            raise ToolError("path must identify a file inside the workspace.")
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise ToolError("The path must stay inside the workspace.") from exc
        return resolved

    def _list_files(self, arguments: dict[str, Any]) -> list[str]:
        self._check_arguments(arguments, set())
        paths: list[str] = []
        scanned = 0
        for root, directories, filenames in os.walk(self.workspace, topdown=True, followlinks=False):
            current = Path(root)
            scanned += len(directories) + len(filenames)
            if scanned > MAX_WORKSPACE_ENTRIES_SCANNED:
                raise ToolError(
                    "The workspace contains too many entries to scan safely "
                    f"(limit: {MAX_WORKSPACE_ENTRIES_SCANNED} entries)."
                )
            directories[:] = sorted(
                name
                for name in directories
                if name not in _EXCLUDED_DIRECTORIES
                and not self._blocked_component(name)
                and not self._is_link_or_junction(current / name)
            )
            for filename in sorted(filenames):
                path = current / filename
                if self._is_link_or_junction(path) or self._blocked_component(filename) or not path.is_file():
                    continue
                paths.append(path.relative_to(self.workspace).as_posix())
                if len(paths) >= MAX_LISTED_FILES:
                    return sorted(paths)
        return sorted(paths)

    def _read_text_file(self, arguments: dict[str, Any]) -> str:
        self._check_arguments(arguments, {"path"})
        path = self._resolve_path(arguments["path"])
        try:
            if not path.is_file():
                raise ToolError(f"File not found: {arguments['path']}")
            # Do not rely only on stat(): the file could grow between the size
            # check and the read. Read at most one byte beyond the configured cap.
            with path.open("rb") as handle:
                content = handle.read(MAX_TEXT_FILE_BYTES + 1)
            if len(content) > MAX_TEXT_FILE_BYTES:
                raise ToolError(
                    f"File is too large to read (limit: {MAX_TEXT_FILE_BYTES // 1000} KB)."
                )
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError("The file is not valid UTF-8 text.") from exc
        except OSError as exc:
            raise ToolError(f"Could not read the requested file: {exc.strerror or 'I/O error'}.") from exc

    def _write_text_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._check_arguments(arguments, {"path", "content"})
        path = self._resolve_path(arguments["path"])
        content = arguments["content"]
        if not isinstance(content, str):
            raise ToolError("content must be a string.")
        try:
            content_bytes = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ToolError("content contains text that cannot be encoded as UTF-8.") from exc
        if len(content_bytes) > MAX_TEXT_FILE_BYTES:
            raise ToolError(
                f"Content is too large to write (limit: {MAX_TEXT_FILE_BYTES // 1000} KB)."
            )

        # Different tasks can run in separate CLI/GUI processes. Lock the target so
        # one write cannot race between checking existing content and replacing it.
        relative_path = path.relative_to(self.workspace).as_posix()
        lock_dir = self.workspace / ".runtime-locks"
        try:
            lock_dir.mkdir(parents=True, exist_ok=True)
            lock_name = hashlib.sha256(relative_path.encode("utf-8")).hexdigest() + ".lock"
            with FileLock(str(lock_dir / lock_name), timeout=0):
                return self._write_locked(path, relative_path, content_bytes)
        except Timeout as exc:
            raise ToolError(
                f"Another operation is already writing '{relative_path}'. Retry after it finishes."
            ) from exc
        except OSError as exc:
            raise ToolError("Could not prepare a safe file-write operation.") from exc

    def _write_locked(
        self, path: Path, relative_path: str, content_bytes: bytes
    ) -> dict[str, Any]:
        if path.exists():
            if not path.is_file():
                raise ToolError("The target exists and is not a regular file.")
            try:
                if path.stat().st_size > MAX_TEXT_FILE_BYTES:
                    raise ToolError(
                        "The existing file exceeds the workspace file-size limit and will not be replaced."
                    )
                current = path.read_bytes()
            except OSError as exc:
                raise ToolError("Could not inspect the existing file before writing.") from exc
            # Safe replay after a crash: do not ask twice when the prior write already
            # left exactly the requested content on disk.
            if current == content_bytes:
                return {
                    "path": relative_path,
                    "bytes_written": len(content_bytes),
                    "unchanged": True,
                }
            if self.approval_callback is None:
                raise ToolError(
                    f"Refusing to overwrite existing file '{relative_path}' without user approval. "
                    "Choose another path or run with an approval handler."
                )
            try:
                approved = bool(self.approval_callback(relative_path))
            except Exception as exc:
                raise ToolError("Could not obtain approval to overwrite the existing file.") from exc
            if not approved:
                raise ToolError(
                    f"User declined to overwrite '{relative_path}'. Existing content was kept."
                )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ToolError("Could not create the destination directory.") from exc

        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(content_bytes)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
        except OSError as exc:
            raise ToolError(
                f"Could not write the requested file: {exc.strerror or 'I/O error'}."
            ) from exc
        finally:
            if temporary_name and os.path.exists(temporary_name):
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass

        return {
            "path": relative_path,
            "bytes_written": len(content_bytes),
            "unchanged": False,
        }
