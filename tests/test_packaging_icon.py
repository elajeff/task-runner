"""Tests for converting the app icon source."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "task_runner_prepare_icon", PROJECT_ROOT / "packaging" / "prepare_icon.py"
)
assert SPEC is not None and SPEC.loader is not None
prepare_icon_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_icon_module)


def test_prepare_icon_creates_windows_icon_from_png(tmp_path, monkeypatch):
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    png_path = asset_dir / "task-runner-icon.png"
    icon_path = asset_dir / "task-runner.ico"

    Image.new("RGBA", (320, 240), (120, 20, 180, 255)).save(png_path)

    monkeypatch.setattr(prepare_icon_module, "PNG_SOURCE", png_path)
    monkeypatch.setattr(prepare_icon_module, "ICON_FILE", icon_path)

    result = prepare_icon_module.prepare_icon()

    assert result == icon_path
    assert icon_path.is_file()
    with Image.open(icon_path) as icon:
        assert icon.format == "ICO"
        assert icon.size == (256, 256)
