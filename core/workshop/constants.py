"""Creative Workshop package and runtime limits."""

from __future__ import annotations


WORKSHOP_API_VERSION = "1.0.0"
WORKSHOP_MANIFEST_VERSION = 1

MAX_PACKAGE_BYTES = 100 * 1024 * 1024
MAX_UNPACKED_BYTES = 300 * 1024 * 1024
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_FILE_COUNT = 2_000
MAX_COMPRESSION_RATIO = 100.0

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_EDGE = 16_384
MAX_IMAGE_PIXELS = 64_000_000
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ICON_BYTES = 2 * 1024 * 1024
MAX_ICON_PIXELS = 1_048_576
MAX_GALLERY_FILES = 20
MAX_GALLERY_FILE_BYTES = 5 * 1024 * 1024
MAX_GALLERY_PIXELS = 16_000_000
MAX_TEXT_DOCUMENT_BYTES = 1024 * 1024

REQUIRED_PACKAGE_FILES = frozenset(
    {
        "manifest.json",
        "ui/index.html",
        "assets/icon.png",
        "README.md",
        "LICENSE",
    }
)
ALLOWED_PERMISSION_NAMES = frozenset(
    {
        "image.pick",
        "project.storage",
        "color-library.read",
        "handoff.image",
    }
)
