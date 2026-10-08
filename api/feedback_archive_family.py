"""Shared material-archive source classification for bug-report assembly.

Both Stage A archives and Lumina Box archives use the converter's material
archive workflow.  Keep that discriminator in one place so feedback capture,
attachment assembly, and ticket rendering cannot drift apart.
"""

from __future__ import annotations

from typing import Any, Literal

MaterialArchiveProfileKind = Literal["stage_a", "lumina_box"]


def is_material_archive_source(value: Any) -> bool:
    """Return whether a submitted source version uses material archives.

    Args:
        value: Untrusted source-version value from a bug-report context.

    Returns:
        ``True`` for Stage A (``material``) and Lumina Box archives.
    """

    return value == "material" or value == "lumina_box"


def material_archive_profile_kind(
    value: Any,
) -> MaterialArchiveProfileKind | None:
    """Map a bug-report source version to its archive-profile discriminator.

    Args:
        value: Untrusted source-version value from a bug-report context.

    Returns:
        The profile kind used by bundle collection, or ``None`` for non-archive
        sources.
    """

    if value == "material":
        return "stage_a"
    if value == "lumina_box":
        return "lumina_box"
    return None
