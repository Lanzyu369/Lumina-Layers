"""Contracts for the native 3MF writer dependency and frozen packaging."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]


def _neroued_requirement() -> Requirement:
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if line.strip().lower().startswith("neroued-3mf"):
            return Requirement(line.strip())
    raise AssertionError("requirements.txt does not declare neroued-3mf")


def test_neroued_requirement_selects_first_zero_copy_release() -> None:
    requirement = _neroued_requirement()

    assert "0.4.0" in requirement.specifier
    assert "0.3.99" not in requirement.specifier
    assert "0.5.0" not in requirement.specifier


def test_installed_neroued_exposes_explicit_zero_copy_mesh_view() -> None:
    import neroued_3mf

    assert metadata.version("neroued-3mf") == "0.4.0"
    assert callable(
        getattr(
            neroued_3mf.DocumentBuilder(),
            "add_mesh_object_zero_copy",
            None,
        )
    )


def test_pyinstaller_collects_neroued_extension_and_runtime(monkeypatch) -> None:
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
    utils_module = ModuleType("PyInstaller.utils")
    pyinstaller_module = ModuleType("PyInstaller")
    monkeypatch.setitem(sys.modules, "PyInstaller", pyinstaller_module)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", utils_module)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks_module)
    monkeypatch.chdir(ROOT)

    def fake_analysis(*_args, **kwargs):
        return SimpleNamespace(
            pure=[],
            zipped_data=[],
            scripts=[],
            binaries=kwargs.get("binaries", []),
            datas=kwargs.get("datas", []),
        )

    namespace = runpy.run_path(
        str(ROOT / "lumina_studio.spec"),
        init_globals={
            "Analysis": fake_analysis,
            "PYZ": lambda *_args, **_kwargs: object(),
            "EXE": lambda *_args, **_kwargs: object(),
        },
    )

    assert collected.count("neroued_3mf") == 1
    assert ("n3mf-data", "neroued_3mf") in namespace["backend_datas"]
    assert ("n3mf-extension", "neroued_3mf") in namespace["backend_binaries"]
    assert "neroued_3mf" in namespace["backend_hiddenimports"]
    assert "neroued_3mf._neroued_3mf" in namespace["backend_hiddenimports"]
