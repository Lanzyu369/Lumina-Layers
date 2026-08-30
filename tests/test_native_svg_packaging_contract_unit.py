"""Packaging contracts for the required native SVG runtime."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from shapely.geometry import box

from core.native_svg_adapter import NativeSvgFallback, NativeSvgGeometry


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_requirement_is_an_exact_workspace_package() -> None:
    native_requirements = (
        ROOT / "requirements-native-svg.txt"
    ).read_text(encoding="utf-8")
    requirement_lines = [
        line.strip()
        for line in native_requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert requirement_lines == ["./native/lumina-svg-core"]

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "-r requirements-native-svg.txt" in requirements.splitlines()

    pyproject = (
        ROOT / "native" / "lumina-svg-core" / "pyproject.toml"
    ).read_text(encoding="utf-8")
    assert 'version = "0.1.0"' in pyproject
    assert 'requires-python = "==3.12.*"' in pyproject


def test_docker_builds_native_runtime_with_python312_before_requirements() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.startswith("FROM python:3.12-slim\n")
    native_copy_index = dockerfile.index(
        "COPY native/lumina-svg-core /app/native/lumina-svg-core"
    )
    requirements_install_index = dockerfile.index(
        "RUN pip install --no-cache-dir -r requirements.txt"
    )
    assert native_copy_index < requirements_install_index
    assert "requirements-native-svg.txt" in dockerfile


def test_pyinstaller_collects_native_svg_as_a_required_binary() -> None:
    spec = (ROOT / "lumina_studio.spec").read_text(encoding="utf-8")

    assert 'LUMINA_SVG_CORE_PACKAGE = "lumina_svg_core"' in spec
    assert '"lumina_svg_core._lumina_svg_core"' in spec
    assert "lumina_svg_core_datas" in spec
    assert "lumina_svg_core_binaries" in spec
    assert "lumina_svg_core_hiddenimports" in spec
    assert "collect_all(LUMINA_SVG_CORE_PACKAGE)" in spec
    assert "console=True" in spec


def test_desktop_build_requires_native_svg_before_pyinstaller() -> None:
    build_script = (
        ROOT / "scripts" / "build_desktop.py"
    ).read_text(encoding="utf-8")

    assert '"lumina_svg_core"' in build_script
    dependency_check_index = build_script.rindex(
        "check_core_geometry_dependencies_available()"
    )
    pyinstaller_index = build_script.index("pyinstaller lumina_studio.spec")
    assert dependency_check_index < pyinstaller_index


def _geometry_outcome() -> NativeSvgGeometry:
    geometry = box(0.0, 0.0, 10.0, 5.0)
    return NativeSvgGeometry(
        shape_data=[
            {
                "poly": geometry,
                "color": (18, 52, 86),
                "source_kind": "fill",
            }
        ],
        clipped_shapes=[
            {
                "geometry": geometry,
                "color": (18, 52, 86),
                "draw_order": 0,
            }
        ],
        silhouette=geometry,
        scale_factor=2.0,
        bbox=(0.0, 0.0, 10.0, 5.0),
        stage_timings={"geometry_backend": "native"},
        native_version="0.1.0",
        native_schema_version=1,
    )


def test_api_server_native_self_test_reports_stable_public_geometry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    api_server = importlib.import_module("api_server")
    monkeypatch.setattr(
        "core.native_svg_adapter.analyze_native_svg",
        lambda *_args, **_kwargs: _geometry_outcome(),
    )

    first_code = api_server.main(
        ["--native-svg-self-test", "fixture.svg"]
    )
    first_payload = json.loads(capsys.readouterr().out)
    second_code = api_server.main(
        ["--native-svg-self-test", "fixture.svg"]
    )
    second_payload = json.loads(capsys.readouterr().out)

    assert first_code == second_code == 0
    assert first_payload == second_payload
    assert first_payload["status"] == "ok"
    assert first_payload["geometry_backend"] == "native"
    assert first_payload["raw_geometry_count"] == 1
    assert first_payload["visible_geometry_count"] == 1
    assert first_payload["silhouette_component_count"] == 1
    assert len(first_payload["fingerprint_sha256"]) == 64


def test_api_server_native_self_test_rejects_fallback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    api_server = importlib.import_module("api_server")
    monkeypatch.setattr(
        "core.native_svg_adapter.analyze_native_svg",
        lambda *_args, **_kwargs: NativeSvgFallback(
            reason_code="unsupported_marker",
            native_version="0.1.0",
        ),
    )

    exit_code = api_server.main(
        ["--native-svg-self-test", "fixture.svg"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload == {
        "error_type": "NativeSvgSelfTestError",
        "reason_code": "unsupported_marker",
        "status": "error",
    }


def test_api_server_native_self_test_runs_real_installed_extension() -> None:
    pytest.importorskip("lumina_svg_core")
    fixture = ROOT / "tests" / "fixtures" / "native_svg" / "fill_rules_transforms.svg"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "api_server.py"),
            "--native-svg-self-test",
            str(fixture),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["status"] == "ok"
    assert payload["geometry_backend"] == "native"
    assert payload["raw_geometry_count"] > 0
    assert payload["visible_geometry_count"] > 0
    assert payload["silhouette_component_count"] > 0
