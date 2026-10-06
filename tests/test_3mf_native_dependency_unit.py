"""Contracts for the native 3MF writer dependency and frozen packaging."""

from __future__ import annotations

from importlib import metadata
from importlib.machinery import EXTENSION_SUFFIXES
import hashlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
from packaging.requirements import Requirement

from scripts.fatcat_packaging_contract import (
    FATCAT_DISTRIBUTION, FATCAT_MODULE, FATCAT_VERSION,
    FATCAT_WRITER_DISTRIBUTION, FATCAT_WRITER_VERSION,
    FATCAT_REQUIRED_ENTRY_POINTS, FATCAT_REQUIRED_DATA_FILES,
    FATCAT_REPOSITORY, FATCAT_SOURCE_COMMIT, FATCAT_WRITER_PATCH,
    FATCAT_WRITER_PATCH_SHA256, FATCAT_WRITER_SOURCE_COMMIT,
)


ROOT = Path(__file__).resolve().parents[1]


def _neroued_requirement() -> Requirement:
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if line.strip().lower().startswith("neroued-3mf"):
            return Requirement(line.strip())
    raise AssertionError("requirements.txt does not declare neroued-3mf")


def test_neroued_requirement_selects_first_zero_copy_release() -> None:
    requirement = _neroued_requirement()

    assert str(requirement.specifier) == f"=={FATCAT_WRITER_VERSION}"
    assert str(requirement.marker) == 'python_version >= "3.12"'
    assert "0.3.99" not in requirement.specifier
    assert "0.6.0" not in requirement.specifier


def test_native_requirement_is_pinned_for_python_313_plus() -> None:
    requirements = (ROOT / "requirements-3mf-native.txt").read_text(encoding="utf-8")

    assert f'{FATCAT_DISTRIBUTION}=={FATCAT_VERSION}; python_version >= "3.12"' in requirements
    assert FATCAT_REPOSITORY in requirements
    assert FATCAT_SOURCE_COMMIT in requirements


def test_fatcat_build_contract_uses_public_root_and_exact_b7_patch() -> None:
    build_script = (ROOT / "scripts" / "build_3mf_native_wheels.py").read_text(
        encoding="utf-8",
    )
    patch = ROOT / FATCAT_WRITER_PATCH

    assert FATCAT_REPOSITORY == "https://github.com/MOVIBALE/fatcat-metadata"
    assert len(FATCAT_SOURCE_COMMIT) == 40
    assert len(FATCAT_WRITER_SOURCE_COMMIT) == 40
    assert FATCAT_WRITER_VERSION == "0.4.0+fatcat.b7"
    assert FATCAT_WRITER_PATCH == "reference/neroued-patches/neroued-3mf-v0.4.0-b7.patch"
    assert patch.is_file()
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == FATCAT_WRITER_PATCH_SHA256
    assert 'fatcat_root / "pyproject.toml"' in build_script
    assert 'patch_path = ROOT / WRITER_PATCH_RELATIVE' in build_script
    assert '"project_root": "."' in build_script
    assert 'fatcat_root / "cpp"' not in build_script


@pytest.mark.parametrize("missing_target", ["bambu-studio-02.08.02.61.json", "orca-slicer-2.4.2.json"])
def test_shared_fatcat_packaging_contract_rejects_missing_target_data(
    monkeypatch,
    tmp_path: Path,
    missing_target: str,
) -> None:
    from scripts.fatcat_packaging_contract import validate_fatcat_packaging_contract

    module_path = tmp_path / "site-packages" / f"{FATCAT_MODULE}.py"
    data_root = module_path.parent / "fatcat_metadata_data"
    for relative_path in FATCAT_REQUIRED_DATA_FILES:
        path = data_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    (data_root / "translations" / "targets" / missing_target).unlink()
    fatcat = SimpleNamespace(
        __file__=str(module_path),
        **{name: lambda *_args: None for name in FATCAT_REQUIRED_ENTRY_POINTS},
    )
    writer = SimpleNamespace()
    versions = {
        FATCAT_DISTRIBUTION: FATCAT_VERSION,
        FATCAT_WRITER_DISTRIBUTION: FATCAT_WRITER_VERSION,
    }
    monkeypatch.setattr(metadata, "version", versions.__getitem__)

    with pytest.raises(FileNotFoundError, match=missing_target):
        validate_fatcat_packaging_contract(fatcat, writer)


def test_installed_neroued_exposes_explicit_zero_copy_mesh_view() -> None:
    import neroued_3mf

    assert metadata.version("neroued-3mf").startswith("0.4.0")
    assert callable(
        getattr(
            neroued_3mf.DocumentBuilder(),
            "add_mesh_object_zero_copy",
            None,
        )
    )


def test_pyinstaller_collects_neroued_extension_and_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    collected: list[str] = []

    def fake_collect_all(package_name: str):
        collected.append(package_name)
        if package_name == "neroued_3mf":
            return (
                [("n3mf-data", "neroued_3mf")],
                [("n3mf-extension", "neroued_3mf")],
                ["neroued_3mf._neroued_3mf"],
            )
        return [], [], []

    hooks_module = ModuleType("PyInstaller.utils.hooks")
    hooks_module.collect_all = fake_collect_all
    fatcat_module_path = tmp_path / "site-packages" / f"{FATCAT_MODULE}.py"
    fatcat_data_root = fatcat_module_path.parent / "fatcat_metadata_data"
    for relative_path in FATCAT_REQUIRED_DATA_FILES:
        path = fatcat_data_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    fatcat_runtime = ModuleType(FATCAT_MODULE)
    fatcat_runtime.__file__ = str(fatcat_module_path)
    for name in FATCAT_REQUIRED_ENTRY_POINTS:
        setattr(fatcat_runtime, name, lambda *_args: None)
    writer_runtime = ModuleType("neroued_3mf")
    monkeypatch.setitem(sys.modules, FATCAT_MODULE, fatcat_runtime)
    monkeypatch.setitem(sys.modules, "neroued_3mf", writer_runtime)
    versions = {
        FATCAT_DISTRIBUTION: FATCAT_VERSION,
        FATCAT_WRITER_DISTRIBUTION: FATCAT_WRITER_VERSION,
    }
    monkeypatch.setattr(metadata, "version", versions.__getitem__)

    def fake_get_module_file_attribute(module_name: str) -> str:
        if module_name == FATCAT_MODULE:
            return str(fatcat_module_path)
        return str(Path("/tmp") / f"_lumina_svg_core{EXTENSION_SUFFIXES[0]}")

    hooks_module.get_module_file_attribute = fake_get_module_file_attribute
    utils_module = ModuleType("PyInstaller.utils")
    pyinstaller_module = ModuleType("PyInstaller")
    monkeypatch.setitem(sys.modules, "PyInstaller", pyinstaller_module)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", utils_module)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks_module)
    monkeypatch.chdir(ROOT)
    monkeypatch.delitem(sys.modules, "scripts.fatcat_packaging_contract", raising=False)
    monkeypatch.delitem(sys.modules, "scripts", raising=False)
    monkeypatch.setattr(
        sys,
        "path",
        [entry for entry in sys.path if Path(entry or ".").resolve() != ROOT],
    )

    def fake_analysis(*_args, **kwargs):
        return SimpleNamespace(
            pure=[],
            zipped_data=[],
            scripts=[],
            binaries=kwargs.get("binaries", []),
            datas=kwargs.get("datas", []),
        )

    namespace = {
        "SPEC": str(ROOT / "lumina_studio.spec"),
        "SPECPATH": str(ROOT),
        "Analysis": fake_analysis,
        "PYZ": lambda *_args, **_kwargs: object(),
        "EXE": lambda *_args, **_kwargs: object(),
    }
    spec_source = (ROOT / "lumina_studio.spec").read_text(encoding="utf-8")
    exec(compile(spec_source, str(ROOT / "lumina_studio.spec"), "exec"), namespace)

    assert collected.count("neroued_3mf") == 1
    assert ("n3mf-data", "neroued_3mf") in namespace["backend_datas"]
    assert ("n3mf-extension", "neroued_3mf") in namespace["backend_binaries"]
    assert "neroued_3mf" in namespace["backend_hiddenimports"]
    assert "neroued_3mf._neroued_3mf" in namespace["backend_hiddenimports"]


def test_desktop_fatcat_collection_has_no_optional_warning_fallback() -> None:
    spec = (ROOT / "lumina_studio.spec").read_text(encoding="utf-8")
    build_script = (ROOT / "scripts" / "build_desktop.py").read_text(
        encoding="utf-8",
    )

    assert "LUMINA_REQUIRE_FATCAT_B4" not in spec
    assert "WARNING: Fat Cat" not in spec
    assert "LUMINA_REQUIRE_FATCAT_B4" not in build_script
    assert "validate_fatcat_packaging_contract" in spec
    assert "validate_fatcat_packaging_contract" in build_script


def test_spec_bootstraps_repo_root_before_shared_contract_import() -> None:
    spec = (ROOT / "lumina_studio.spec").read_text(encoding="utf-8")

    bootstrap = spec.index("SPEC_ROOT = Path(SPEC).resolve().parent")
    shared_import = spec.index(
        "from scripts.fatcat_packaging_contract import validate_fatcat_packaging_contract"
    )

    assert "sys.path.insert(0, str(SPEC_ROOT))" in spec
    assert bootstrap < shared_import


def test_ci_native_wheel_bootstrap_uses_the_same_pinned_inputs() -> None:
    action = (
        ROOT / ".github" / "actions" / "prepare-3mf-native-wheels" / "action.yml"
    ).read_text(encoding="utf-8")

    assert "--get FATCAT_WRITER_SOURCE_COMMIT" in action
    assert "--get FATCAT_WRITER_PATCH" in action
    assert "--install" in action
    assert "scripts/build_3mf_native_wheels.py" in action
    assert "--output-dir \"$GITHUB_WORKSPACE/wheelhouse/3mf\"" in action


def test_ci_pins_the_fatcat_0100_source_revision() -> None:
    action = (
        ROOT / ".github" / "actions" / "prepare-3mf-native-wheels" / "action.yml"
    ).read_text(encoding="utf-8")
    assert "scripts/fatcat_packaging_contract.py" in action
    assert "--get FATCAT_SOURCE_COMMIT" in action
    assert "--get FATCAT_WRITER_SOURCE_COMMIT" in action
    assert f"{FATCAT_DISTRIBUTION}=={FATCAT_VERSION}" in (
        ROOT / "requirements-3mf-native.txt"
    ).read_text(encoding="utf-8")


def test_public_fatcat_source_builds_without_a_token() -> None:
    action = (
        ROOT / ".github" / "actions" / "prepare-3mf-native-wheels" / "action.yml"
    ).read_text(encoding="utf-8")
    build_script = (ROOT / "scripts" / "build_3mf_native_wheels.py").read_text(
        encoding="utf-8",
    )

    assert 'git clone --no-checkout "$FATCAT_REPOSITORY"' in action
    assert '"$GITHUB_WORKSPACE/$writer_patch"' in action
    assert "fatcat-token" not in action
    assert "FATCAT_TOKEN" not in action
    assert "http.extraheader" not in action
    assert "fatcat_root / \"pyproject.toml\"" in build_script

    for workflow in (
        ROOT / ".github" / "workflows" / "build.yml",
        ROOT / ".github" / "workflows" / "layered-mesh-geometry.yml",
        ROOT / ".github" / "workflows" / "native-svg-core.yml",
    ):
        text = workflow.read_text(encoding="utf-8")
        assert "FATCAT_REPO_TOKEN" not in text
        assert "fatcat-token:" not in text
        assert "--secret id=fatcat_token" not in text
