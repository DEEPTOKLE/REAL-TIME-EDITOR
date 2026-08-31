"""
Handles storage and retrieval of image files for the Synapse editor.
Images are stored in data/images/ with a UUID-based filename.
"""
import os
import pathlib
import re
from io import BytesIO

from PIL import Image

IMAGE_DIR = pathlib.Path("data/images")
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "image/png":  ".png",
    "image/jpeg": ".jpg",
    "image/gif":  ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}
CONTENT_TYPE_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/x-ms-bmp": "image/bmp",
    "image/x-tiff": "image/tiff",
}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
IMAGE_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def _validate_image_id(img_id: str) -> str:
    if not isinstance(img_id, str) or not IMAGE_ID_PATTERN.fullmatch(img_id):
        raise FileNotFoundError("Image not found")
    return img_id


def save_image_file(image_bytes: bytes, content_type: str) -> str:
    """Validate and save a browser-renderable image, returning its ID.

    BMP and TIFF are converted to PNG because browser support is inconsistent.
    PNG, JPEG, GIF, and WebP retain their original formats (and animation).
    """
    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        raise ValueError("Image exceeds 10 MB limit")

    content_type = CONTENT_TYPE_ALIASES.get(content_type.lower(), content_type.lower())
    if content_type not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported image type")

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
        with Image.open(BytesIO(image_bytes)) as image:
            if content_type in {"image/bmp", "image/tiff"}:
                # Convert formats that are often embedded in Word documents but
                # are not consistently rendered by browsers.
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                output = BytesIO()
                image.save(output, format="PNG")
                image_bytes = output.getvalue()
                content_type = "image/png"
    except Exception as exc:
        raise ValueError("Invalid or corrupted image file") from exc

    ext = ALLOWED_EXTENSIONS[content_type]
    img_id = pathlib.Path(_generate_id()).name
    path = IMAGE_DIR / f"{img_id}{ext}"
    path.write_bytes(image_bytes)
    return img_id


def load_image_file(img_id: str):
    """Load image bytes from disk. Returns (bytes, content_type)."""
    img_id = _validate_image_id(img_id)
    for content_type, ext in ALLOWED_EXTENSIONS.items():
        path = IMAGE_DIR / f"{img_id}{ext}"
        if path.exists():
            return path.read_bytes(), content_type
    raise FileNotFoundError(f"Image not found: {img_id}")


def delete_image_file(img_id: str) -> bool:
    """Delete an image from disk. Returns True if deleted."""
    img_id = _validate_image_id(img_id)
    for ext in ALLOWED_EXTENSIONS.values():
        path = IMAGE_DIR / f"{img_id}{ext}"
        if path.exists():
            path.unlink()
            return True
    return False


def _generate_id() -> str:
    import uuid
    return uuid.uuid4().hex
