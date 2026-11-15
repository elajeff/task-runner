"""Create the Windows icon from the project's supplied image."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
PNG_SOURCE = ROOT / "assets" / "task-runner-icon.png"
ICON_FILE = ROOT / "assets" / "task-runner.ico"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def prepare_icon() -> Path:
    with Image.open(PNG_SOURCE) as image:
        # Keep PNG transparency so transparent icon backgrounds stay transparent.
        icon_image = ImageOps.fit(
            image.convert("RGBA"),
            (256, 256),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        icon_image.save(
            ICON_FILE,
            format="ICO",
            sizes=[(size, size) for size in ICON_SIZES],
        )
    print(f"Windows icon created: {ICON_FILE}")
    return ICON_FILE


if __name__ == "__main__":
    prepare_icon()
