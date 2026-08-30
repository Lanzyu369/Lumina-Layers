"""Contracts for native-SVG 3MF and real-slicer validation evidence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_native_svg_slicer_outputs.py"
WORKFLOW = ROOT / ".github" / "workflows" / "native-svg-core.yml"


def _write_minimal_3mf(path: Path) -> None:
    model = b"""<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <object id="1" type="model"><mesh><vertices>
      <vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/>
      <vertex x="0" y="1" z="0"/>
    </vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>
  </resources>
  <build><item objectid="1"/></build>
</model>
"""
    settings = b"""<?xml version="1.0" encoding="UTF-8"?>
<config><object id="1"><metadata key="name" value="Red"/>
<part id="1" subtype="normal_part"><metadata key="extruder" value="2"/>
</part></object></config>
"""
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("3D/3dmodel.model", model)
        package.writestr("Metadata/model_settings.config", settings)


def test_three_mf_inspection_and_toolpath_fingerprint_are_deterministic(
    tmp_path: Path,
) -> None:
    from scripts.verify_native_svg_slicer_outputs import (
        _inspect_3mf,
        _toolpath_metrics,
    )

    project = tmp_path / "fixture.3mf"
    _write_minimal_3mf(project)
    inspection = _inspect_3mf(project)

    assert inspection["object_count"] == 1
    assert inspection["build_item_count"] == 1
    assert inspection["triangle_count"] == 1
    assert inspection["material_count"] == 1
    assert len(inspection["sha256"]) == 64

    first = _toolpath_metrics(
        b"; generated 2026-08-31\nT0\nG1 X1 Y2 E0.1\nG1 Z0.2\n"
    )
    second = _toolpath_metrics(
        b"; generated at a different time\r\nT0\r\n"
        b"G1 X1 Y2 E0.1\r\nG1 Z0.2\r\n"
    )
    assert first == second
    assert first["motion_command_count"] == 2
    assert first["extrusion_move_count"] == 1
    assert first["tool_change_count"] == 1
    assert len(first["fingerprint"]) == 64


def test_slicer_command_treats_allow_newer_file_as_a_flag(
    tmp_path: Path,
) -> None:
    from scripts.verify_native_svg_slicer_outputs import _validation_command

    command = _validation_command(
        tmp_path / "slicer",
        tmp_path / "project.3mf",
        tmp_path / "output",
    )

    flag_index = command.index("--allow-newer-file")
    assert command[flag_index + 1] == "--slice"
    assert command[-1].endswith("project.3mf")


def test_slicer_process_is_isolated_in_its_artifact_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from scripts import verify_native_svg_slicer_outputs as reality

    project = tmp_path / "fixture.3mf"
    _write_minimal_3mf(project)
    executable = tmp_path / "slicer"
    executable.touch()
    working_directories: list[Path | None] = []

    def fake_run_command(command, *, timeout_seconds, cwd=None):
        working_directories.append(cwd)
        if "--help" in command:
            return 0, "BambuStudio-test:\n", "", 0.01
        (cwd / "plate_1.gcode").write_text(
            "T0\nG1 X1 Y2 E0.1\n",
            encoding="utf-8",
        )
        return 0, "", "", 0.01

    monkeypatch.setattr(reality, "_run_command", fake_run_command)
    output_root = tmp_path / "toolpaths"
    reality._validate_slicer(
        "BambuStudio",
        executable,
        project,
        output_root,
        timeout_seconds=10,
        validation_runs=2,
    )

    expected = output_root / "BambuStudio"
    assert working_directories
    assert all(
        directory.parent == expected and directory.name.startswith("run-")
        for directory in working_directories
    )
    result = reality._validate_slicer(
        "BambuStudio",
        executable,
        project,
        output_root,
        timeout_seconds=10,
        validation_runs=2,
    )
    assert result["status"] == "passed"
    assert result["stable_across_runs"] is True
    assert len(result["runs"]) == 2
    assert len({run["toolpath"]["fingerprint"] for run in result["runs"]}) == 1


def test_cli_reports_missing_slicers_as_unavailable_not_passed(
    tmp_path: Path,
) -> None:
    bambu_project = tmp_path / "bambu.3mf"
    orca_project = tmp_path / "orca.3mf"
    _write_minimal_3mf(bambu_project)
    _write_minimal_3mf(orca_project)
    report_path = tmp_path / "report.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--no-auto-detect",
            "--bambu-3mf",
            str(bambu_project),
            "--orca-3mf",
            str(orca_project),
            "--report",
            str(report_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 20
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "reality_dependency_unavailable"
    assert report["slicers"]["BambuStudio"]["status"] == (
        "reality_dependency_unavailable"
    )
    assert report["slicers"]["OrcaSlicer"]["status"] == (
        "reality_dependency_unavailable"
    )
    assert "passed" not in {
        result["status"] for result in report["slicers"].values()
    }


def test_native_svg_workflow_covers_all_release_realities() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for platform_id in (
        "manylinux-x86_64",
        "windows-amd64",
        "macos-arm64",
        "macos-x86_64",
    ):
        assert platform_id in workflow
    for job_or_probe in (
        "docker-reality",
        "windows-onefile-reality",
        "product-artifacts",
        "--native-svg-self-test",
        "verify_native_svg_slicer_outputs.py",
        "lumina-native-svg-reality",
    ):
        assert job_or_probe in workflow
    assert "docker build" in workflow
    assert "pyinstaller --noconfirm --clean lumina_studio.spec" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "cd native/lumina-svg-core" in workflow
