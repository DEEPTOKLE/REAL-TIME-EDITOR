"""
Handles storage and retrieval of image files for the Synapse editor.
Images are stored in data/images/ with a UUID-based filename.
"""
import os
import pathlib

IMAGE_DIR = pathlib.Path("data/images")
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "image/png":  ".png",
    "image/jpeg": ".jpg",
    "image/gif":  ".gif",
    "image/webp": ".webp",
}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def save_image_file(image_bytes: bytes, content_type: str) -> str:
    """Save image bytes to disk. Returns the img_id (filename without ext)."""
    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        raise ValueError("Image exceeds 10 MB limit")
    ext = ALLOWED_EXTENSIONS.get(content_type, ".png")
    img_id = pathlib.Path(_generate_id()).name
    path = IMAGE_DIR / f"{img_id}{ext}"
    path.write_bytes(image_bytes)
    return img_id


def load_image_file(img_id: str):
    """Load image bytes from disk. Returns (bytes, content_type)."""
    for content_type, ext in ALLOWED_EXTENSIONS.items():
        path = IMAGE_DIR / f"{img_id}{ext}"
        if path.exists():
            return path.read_bytes(), content_type
    raise FileNotFoundError(f"Image not found: {img_id}")


def delete_image_file(img_id: str) -> bool:
    """Delete an image from disk. Returns True if deleted."""
    for ext in ALLOWED_EXTENSIONS.values():
        path = IMAGE_DIR / f"{img_id}{ext}"
        if path.exists():
            path.unlink()
            return True
    return False


def _generate_id() -> str:
    import uuid
    return uuid.uuid4().hex
