"""Unit tests for the lossless dense-buffer proof harness."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import MultiPolygon, Polygon


def test_geometry_fingerprint_tracks_product_semantics() -> None:
    from scripts.profile_geos_buffer_fast_proof import geometry_fingerprint

    geometry = MultiPolygon(
        [
            Polygon(
                [(0, 0), (4, 0), (4, 4), (0, 4)],
                holes=[[(1, 1), (2, 1), (2, 2), (1, 2)]],
            ),
            Polygon([(10, 0), (12, 0), (12, 2), (10, 2)]),
        ]
    )

    result = geometry_fingerprint(geometry)

    assert result["valid"] is True
    assert result["geom_type"] == "MultiPolygon"
    assert result["components"] == 2
    assert result["holes"] == 1
    assert result["area"] == 19.0
    assert result["bounds"] == [0.0, 0.0, 12.0, 4.0]
    assert len(result["normalized_wkb_sha256"]) == 64


def test_compare_geometry_rejects_equal_area_with_changed_region() -> None:
    from scripts.profile_geos_buffer_fast_proof import compare_geometry

    stock = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    shifted = Polygon([(1, 0), (3, 0), (3, 2), (1, 2)])

    result = compare_geometry(stock, shifted)

    assert result["pass"] is False
    assert result["symmetric_difference_empty"] is False
    assert result["symmetric_difference_area"] == 4.0


def test_compare_geometry_accepts_component_order_only_difference() -> None:
    from scripts.profile_geos_buffer_fast_proof import compare_geometry

    first = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    second = Polygon([(4, 0), (6, 0), (6, 2), (4, 2)])
    stock = MultiPolygon([first, second])
    reordered = MultiPolygon([second, first])

    result = compare_geometry(stock, reordered)

    assert result["pass"] is True
    assert result["symmetric_difference_empty"] is True


def test_proof_builder_is_pinned_and_scratch_only() -> None:
    from scripts.build_geos_buffer_fast_proof import (
        GEOS_REF,
        GEOS_REPOSITORY,
        PATCH_PATH,
        PROOF_ROOT,
        ROOT,
    )

    assert GEOS_REF == "3.13.1"
    assert GEOS_REPOSITORY == "https://github.com/libgeos/geos.git"
    assert PROOF_ROOT == ROOT / ".scratch" / "geos_buffer_fast_proof"
    assert PATCH_PATH == (
        ROOT
        / "native"
        / "geos_buffer_fast"
        / "patches"
        / "geos-3.13.1-buffer-subgraph-index.patch"
    )


def test_proof_builder_commands_are_argument_lists() -> None:
    from scripts.build_geos_buffer_fast_proof import (
        BUILD_ROOT,
        GEOS_REF,
        PATCH_PATH,
        SOURCE_ROOT,
        apply_command,
        build_command,
        clone_command,
        configure_command,
    )

    clone = clone_command()
    apply = apply_command()
    configure = configure_command()
    build = build_command(parallel=3)

    assert clone == [
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        GEOS_REF,
        "https://github.com/libgeos/geos.git",
        str(SOURCE_ROOT),
    ]
    assert apply == ["git", "-C", str(SOURCE_ROOT), "apply", str(PATCH_PATH)]
    assert configure[:5] == ["cmake", "-S", str(SOURCE_ROOT), "-B", str(BUILD_ROOT)]
    assert "-DCMAKE_BUILD_TYPE=Release" in configure
    assert "-DBUILD_TESTING=OFF" in configure
    assert "-DBUILD_DOCUMENTATION=OFF" in configure
    assert "-DBUILD_GEOSOP=OFF" in configure
    assert build == [
        "cmake",
        "--build",
        str(BUILD_ROOT),
        "--config",
        "Release",
        "--parallel",
        "3",
    ]
    assert all(isinstance(command, list) for command in (clone, apply, configure, build))


def test_proof_builder_refuses_broad_rebuild_targets() -> None:
    from scripts.build_geos_buffer_fast_proof import PROOF_ROOT, ROOT, validate_rebuild_target

    assert validate_rebuild_target(PROOF_ROOT) == PROOF_ROOT.resolve()
    with pytest.raises(ValueError):
        validate_rebuild_target(Path("/"))
    with pytest.raises(ValueError):
        validate_rebuild_target(ROOT)
    with pytest.raises(ValueError):
        validate_rebuild_target(ROOT / ".scratch")


def test_geos_fast_buffer_readme_documents_proof_boundary() -> None:
    from scripts.build_geos_buffer_fast_proof import ROOT

    readme = (
        ROOT / "native" / "geos_buffer_fast" / "README.md"
    ).read_text(encoding="utf-8")

    assert "LGPL-2.1-or-later" in readme
    assert ".scratch/geos_buffer_fast_proof" in readme
    assert "must not replace Shapely" in readme
    assert "production" in readme.lower()
