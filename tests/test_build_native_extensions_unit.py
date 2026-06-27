"""Tests for repository-native extension build metadata."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def test_clipper2_extension_uses_product_sources() -> None:
    from scripts.build_native_extensions import ROOT, get_clipper2_extension

    extension = get_clipper2_extension()

    assert extension.name == "clipper2_batch"
    source_paths = [str((ROOT / source).resolve()) for source in extension.sources]
    assert all("/native/clipper2_batch/" in path for path in source_paths)
    assert all("/.scratch/" not in path for path in source_paths)

    source_names = {path.rsplit("/", 1)[-1] for path in source_paths}
    assert {
        "clipper2_batch_module.cpp",
        "clipper.engine.cpp",
        "clipper.offset.cpp",
        "clipper.triangulation.cpp",
    }.issubset(source_names)


def test_clipper2_extension_include_dirs_are_product_paths() -> None:
    from scripts.build_native_extensions import ROOT, get_clipper2_extension

    extension = get_clipper2_extension()

    include_dirs = [str((ROOT / include_dir).resolve()) for include_dir in extension.include_dirs]
    assert include_dirs
    assert all("/.scratch/" not in path for path in include_dirs)
    assert any("/native/clipper2_batch/" in path for path in include_dirs)


def test_clipper2_extension_includes_numpy_headers_for_array_outputs() -> None:
    from scripts.build_native_extensions import ROOT, get_clipper2_extension

    extension = get_clipper2_extension()

    include_dirs = {str((ROOT / include_dir).resolve()) for include_dir in extension.include_dirs}

    assert str(Path(np.get_include()).resolve()) in include_dirs


def test_dockerfile_builds_native_extension_after_copy() -> None:
    from scripts.build_native_extensions import ROOT

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    copy_index = dockerfile.index("COPY . /app/")
    build_index = dockerfile.index("python scripts/build_native_extensions.py")
    assert copy_index < build_index


def test_docker_runtime_enables_native_vector_mesh() -> None:
    from scripts.build_native_extensions import ROOT

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "LUMINA_VECTOR_NATIVE_MESH=1" in dockerfile
    assert "LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE=1" in dockerfile


def test_desktop_build_invokes_native_extension_before_pyinstaller() -> None:
    from scripts.build_native_extensions import ROOT

    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(encoding="utf-8")

    native_index = build_script.index("scripts/build_native_extensions.py")
    pyinstaller_index = build_script.index("pyinstaller lumina_studio.spec")
    assert native_index < pyinstaller_index


def test_desktop_build_treats_native_extension_as_optional() -> None:
    from scripts.build_native_extensions import ROOT

    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(encoding="utf-8")

    assert "NATIVE_VECTOR_MESH_MARKER" in build_script
    assert "build_native_extensions_optional" in build_script
    assert "subprocess.CalledProcessError" in build_script


def test_electron_production_backend_enables_native_vector_mesh() -> None:
    from scripts.build_native_extensions import ROOT

    electron_main = (ROOT / "electron" / "main.cjs").read_text(encoding="utf-8")

    assert "NATIVE_VECTOR_MESH_MARKER" in electron_main
    assert "env.LUMINA_VECTOR_NATIVE_MESH = \"1\"" in electron_main
    assert "env.LUMINA_VECTOR_NATIVE_MESH_VALIDATE_SURFACE = \"1\"" in electron_main
    production_start = electron_main.index("const backendExe = path.join")
    native_spawn = electron_main.index(
        "spawnChild(\"Backend\", backendExe, [], ROOT_DIR, backendRuntimeEnv())",
    )
    assert production_start < native_spawn


def test_pyinstaller_spec_includes_native_extension_binary() -> None:
    from scripts.build_native_extensions import ROOT

    spec = (ROOT / "lumina_studio.spec").read_text(encoding="utf-8")

    assert "clipper2_batch" in spec
    assert "native_binaries" in spec
    assert "backend_hiddenimports" in spec


def test_pyinstaller_spec_collects_default_glb_v2_dependencies() -> None:
    from scripts.build_native_extensions import ROOT

    spec = (ROOT / "lumina_studio.spec").read_text(encoding="utf-8")

    assert "collect_all" in spec
    assert '"rasterio"' in spec
    assert '"manifold3d"' in spec
    assert '"rasterio.features"' in spec
    assert "glb_v2_binaries" in spec


def test_clipper2_extension_exports_difference_paths_api() -> None:
    from scripts.build_native_extensions import ROOT

    source = (
        ROOT / "native" / "clipper2_batch" / "clipper2_batch_module.cpp"
    ).read_text(encoding="utf-8")

    assert "DifferencePaths" in source
    assert '"difference_paths"' in source


def test_clipper2_extension_uses_numpy_array_output_api() -> None:
    from scripts.build_native_extensions import ROOT

    source = (
        ROOT / "native" / "clipper2_batch" / "clipper2_batch_module.cpp"
    ).read_text(encoding="utf-8")

    assert "#include <numpy/arrayobject.h>" in source
    assert "import_array" in source
    assert "PyArray_SimpleNew" in source
