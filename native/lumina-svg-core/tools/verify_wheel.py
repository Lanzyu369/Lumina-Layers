"""Verify wheel contents or the installed extension in a clean environment."""

from __future__ import annotations

import argparse
from pathlib import Path
import tempfile
import zipfile


def verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    assert any(name.endswith((".pyd", ".so")) for name in names)
    assert any(
        Path(name).name.startswith("_lumina_svg_compensation")
        and name.endswith((".pyd", ".so")) for name in names
    )
    assert any(name.endswith("LICENSE") for name in names)
    assert "lumina_svg_core/THIRD_PARTY_NOTICES.md" in names
    for license_name in (
        "Clipper2.txt",
        "FreeType-Project.txt",
        "LunaSVG.txt",
        "PlutoVG.txt",
        "stb.txt",
        "pybind11.txt",
        "ChromaPrint3D.txt",
    ):
        assert (
            f"lumina_svg_core/THIRD_PARTY_LICENSES/{license_name}" in names
        )
    assert not any(name.endswith((".a", ".lib")) for name in names)
    assert not any("/include/" in name or "/cmake/" in name for name in names)


def verify_installed_compensation() -> None:
    """Exercise the required 2D compensation binary with an enclosed hole.
    用封闭小孔验证随包分发的二维补偿扩展。
    """
    import numpy as np
    from lumina_svg_core._lumina_svg_compensation import find_holes_mm

    shell = np.array([[0., 0.], [10., 0.], [10., 10.], [0., 10.]])
    hole = np.array([[4.8, 4.8], [4.8, 5.2], [5.2, 5.2], [5.2, 4.8]])
    patches, coverage = find_holes_mm([shell, hole], 0.5, 0.0)
    assert len(patches) == len(coverage) == 1
    assert patches[0][0].dtype == np.float64
    assert not coverage[0][1]


def verify_installed_extension() -> None:
    import lumina_svg_core
    from shapely.geometry import Polygon

    assert callable(getattr(lumina_svg_core, "canonicalize_grid_regions", None))
    triangle = [(0, 0), (1, 0), (0, 1000), (0, 0)]
    canonical = lumina_svg_core.canonicalize_grid_regions([[triangle]])
    assert sum(
        Polygon(shell, holes).area for shell, holes in canonical[0]
    ) == 500

    result = lumina_svg_core.analyze_svg_svg(
        "<svg viewBox='0 0 20 10'>"
        "<rect x='1' y='1' width='8' height='5' fill='#f00'/>"
        "<path d='M2 8H18' fill='none' stroke='#00f' stroke-width='2'/>"
        "</svg>",
        target_width_mm=20.0,
        tolerance_mm=0.02,
    )
    assert result.status == "supported"
    assert result.raw.geometry_count == 2
    assert result.visible.coordinates.dtype.name == "int64"
    assert not result.visible.coordinates.flags.writeable

    with tempfile.TemporaryDirectory(prefix="lumina-svg-") as directory:
        unicode_path = Path(directory) / "中文-🐉" / "图像-😀.svg"
        unicode_path.parent.mkdir()
        unicode_path.write_text(
            "<svg viewBox='0 0 10 10'>"
            "<rect width='10' height='10' fill='#123456'/>"
            "</svg>",
            encoding="utf-8",
        )
        unicode_result = lumina_svg_core.analyze_svg(
            unicode_path,
            target_width_mm=10.0,
            tolerance_mm=0.02,
        )
        assert unicode_result.status == "supported", (
            unicode_result.reason_code
        )
        assert unicode_result.raw.geometry_count == 1
    verify_installed_compensation()


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
