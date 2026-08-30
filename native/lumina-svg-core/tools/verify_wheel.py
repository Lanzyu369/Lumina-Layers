"""Verify wheel contents or the installed extension in a clean environment."""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile


def verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    assert any(name.endswith((".pyd", ".so")) for name in names)
    assert any(name.endswith("LICENSE") for name in names)
    assert any(name.endswith("THIRD_PARTY_NOTICES.md") for name in names)
    for license_name in (
        "Clipper2.txt",
        "FreeType-Project.txt",
        "LunaSVG.txt",
        "PlutoVG.txt",
        "stb.txt",
    ):
        assert any(
            name.endswith(f"THIRD_PARTY_LICENSES/{license_name}")
            for name in names
        )
    assert not any(name.endswith((".a", ".lib")) for name in names)
    assert not any("/include/" in name or "/cmake/" in name for name in names)


def verify_installed_extension() -> None:
    import lumina_svg_core

    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 10'>"
        "<rect x='1' y='1' width='8' height='6' fill='#f00'/>"
        "<path d='M2 8H18' fill='none' stroke='#00f' stroke-width='2'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )
    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.visible.coordinates.dtype.name == "int64"
    assert not result.visible.coordinates.flags.writeable


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", nargs="?", type=Path)
    parser.add_argument("--contents-only", action="store_true")
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    if args.wheel is not None:
        verify_wheel(args.wheel)
    if args.installed or not args.contents_only:
        verify_installed_extension()


if __name__ == "__main__":
    main()
