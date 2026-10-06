"""Packaging contracts for the retired native Vector engine."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_build_does_not_build_or_mark_retired_native_vector_engine() -> None:
    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(
        encoding="utf-8"
    )

    assert "scripts/build_native_extensions.py" not in build_script
    assert "NATIVE_VECTOR_MESH_MARKER" not in build_script
    assert "clipper2_batch" not in build_script


def test_electron_backend_does_not_enable_retired_native_vector_engine() -> None:
    electron_main = (ROOT / "electron" / "main.cjs").read_text(encoding="utf-8")

    assert "NATIVE_VECTOR_MESH_MARKER" not in electron_main
    assert "LUMINA_VECTOR_NATIVE_MESH" not in electron_main


def test_runtime_does_not_emit_retired_native_vector_telemetry() -> None:
    vector_branch = (ROOT / "core" / "pipeline" / "vector_branch.py").read_text(
        encoding="utf-8"
    )
    vector_engine = (ROOT / "core" / "vector_engine.py").read_text(
        encoding="utf-8"
    )

    assert "_native_mesh_timing_fields" not in vector_branch
    assert "last_native_vector_mesh_stats" not in vector_engine


def test_pyinstaller_spec_excludes_retired_native_vector_extension() -> None:
    spec = (ROOT / "lumina_studio.spec").read_text(encoding="utf-8")

    assert "clipper2_batch" not in spec
    assert "native_binaries" not in spec


def test_ci_does_not_run_retired_native_vector_engine_gate() -> None:
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    )

    assert "clipper2_batch" not in workflows
    assert "test_vector_native_mesh_unit.py" not in workflows
    assert "LUMINA_VECTOR_NATIVE_MESH" not in workflows


def test_layered_geometry_ci_keeps_windows_and_linux_host_gates() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "layered-mesh-geometry.yml"
    ).read_text(encoding="utf-8")

    assert "branches: [dev-refactor, main]" in workflow
    assert "runs-on: windows-latest" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert (
        "python -m pip install -r requirements.txt -r requirements-glb-v2.txt"
    ) in workflow
    assert "tests/test_layered_surface_mesh_unit.py" in workflow
    assert "tests/test_vector_engine_mesh_weld_unit.py" in workflow
    assert "tests/test_bambu_3mf_writer_unit.py" in workflow


def test_pyinstaller_spec_collects_default_glb_v2_dependencies() -> None:
    spec = (ROOT / "lumina_studio.spec").read_text(encoding="utf-8")

    assert "collect_all" in spec
    assert '"rasterio"' in spec
    assert '"manifold3d"' in spec
    assert '"rasterio.features"' in spec
    assert "glb_v2_binaries" in spec
