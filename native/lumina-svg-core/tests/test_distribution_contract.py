"""Distribution boundary tests for the standalone native SVG package."""

from __future__ import annotations

from pathlib import Path
import tomllib


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_distribution_pins_native_dependencies_and_licenses() -> None:
    dependencies = (
        PACKAGE_ROOT / "cmake" / "Dependencies.cmake"
    ).read_text(encoding="utf-8")
    notices = (PACKAGE_ROOT / "THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8"
    )

    assert "59690a23981489acc3f73b8db229ef57bb69c544" in dependencies
    assert "21ebba05db8894f0c7217ad35ea518080f324946" in dependencies
    assert "LunaSVG" in notices
    assert "PlutoVG" in notices
    assert "Clipper2" in notices
    assert "FreeType" in notices


def test_python_distribution_is_exactly_versioned_for_cpython_312() -> None:
    metadata = tomllib.loads(
        (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert metadata["project"]["name"] == "lumina-svg-core"
    assert metadata["project"]["version"] == "0.1.0"
    assert metadata["project"]["requires-python"] == "==3.12.*"
    assert metadata["project"]["license"] == "Apache-2.0"
    assert metadata["project"]["license-files"] == [
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
    ]


def test_readme_declares_workspace_extraction_boundary() -> None:
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")

    assert "independent repository" in readme
    assert "Lumina Studio" in readme
    assert "VectorAnalysis" not in readme
