"""Download the chosen app image (if needed) and make the Windows icon."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = ROOT / "assets"
SOURCE_IMAGE = ASSET_DIR / "task-runner-icon.jpg"
ICON_FILE = ASSET_DIR / "task-runner.ico"
IMAGE_URL = "https://i.imgur.com/rgNSMeV.jpg"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _download_source_image() -> bytes:
    request = Request(
        IMAGE_URL,
        headers={"User-Agent": "task-runner-icon-builder/1.0"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            image_data = response.read(MAX_IMAGE_BYTES + 1)
    except (OSError, URLError, TimeoutError) as exc:
        raise RuntimeError(
            f"Could not download the task runner icon from {IMAGE_URL}. "
            "Check the connection, or save the image manually as "
            "assets/task-runner-icon.jpg and run the build again."
        ) from exc

    if len(image_data) > MAX_IMAGE_BYTES:
        raise RuntimeError("The app icon image is larger than 12 MB.")
    try:
        with Image.open(BytesIO(image_data)) as image:
            image.verify()
    except Exception as exc:
        raise RuntimeError(
            f"The URL did not return image data (received {content_type or 'an unknown content type'}). "
            "Open the image in your browser and save the actual image as "
            "assets/task-runner-icon.jpg, then run the build again."
        ) from exc
    return image_data


def prepare_icon() -> Path:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    if not SOURCE_IMAGE.is_file():
        SOURCE_IMAGE.write_bytes(_download_source_image())

    try:
        with Image.open(SOURCE_IMAGE) as image:
            image.load()
            image = ImageOps.exif_transpose(image).convert("RGB")
            # A square crop gives Windows consistent artwork at taskbar sizes.
            icon_image = ImageOps.fit(
                image,
                (256, 256),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            icon_image.save(ICON_FILE, format="ICO", sizes=[(size, size) for size in ICON_SIZES])
    except Exception as exc:
        raise RuntimeError(
            f"Could not convert {SOURCE_IMAGE} into a Windows icon. "
            "Replace it with a valid JPG, PNG, or WEBP image and retry."
        ) from exc

    print(f"App icon source: {SOURCE_IMAGE}")
    print(f"Windows icon created: {ICON_FILE}")
    return ICON_FILE


if __name__ == "__main__":
    prepare_icon()
