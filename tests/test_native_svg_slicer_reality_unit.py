"""Contracts for native-SVG 3MF and real-slicer validation evidence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_native_svg_slicer_outputs.py"
WORKFLOW = ROOT / ".github" / "workflows" / "native-svg-core.yml"
CHECKED_IN_REPORT = ROOT / "progress" / "native-svg-slicer-reality.json"


def _write_minimal_3mf(
    path: Path,
    *,
    extruders: tuple[str, ...] = ("1",),
) -> None:
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
    parts = "".join(
        "<part id=\"{index}\" subtype=\"normal_part\">"
        "<metadata key=\"extruder\" value=\"{extruder}\"/>"
        "</part>".format(index=index, extruder=extruder)
        for index, extruder in enumerate(extruders, start=1)
    )
    settings = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<config><object id="1"><metadata key="name" value="Red"/>'
        f"{parts}</object></config>"
    ).encode("utf-8")
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
    assert inspection["expected_tool_ids"] == [0]
    assert len(inspection["sha256"]) == 64

    first = _toolpath_metrics(
        b"; generated 2026-08-31\n; FEATURE: Outer wall\n"
        b"T0\nG1 X1 Y2 E0.1\nG1 Z0.2\n"
    )
    second = _toolpath_metrics(
        b"; generated at a different time\r\nT0\r\n"
        b"; FEATURE: Outer wall\r\n"
        b"G1 X1 Y2 E0.1\r\nG1 Z0.2\r\n"
    )
    assert first == second
    assert first["motion_command_count"] == 2
    assert first["extrusion_move_count"] == 1
    assert first["tool_change_count"] == 1
    assert len(first["fingerprint"]) == 64


def test_toolpath_metrics_count_only_positive_extrusion_deltas() -> None:
    from scripts.verify_native_svg_slicer_outputs import _toolpath_metrics

    metrics = _toolpath_metrics(
        b"M82\nT0\nG92 E0\n; FEATURE: Outer wall\n"
        b"G1 X1 E0\n"
        b"G1 X2 E1\n"
        b"G1 X3 E0.5\n"
        b"G1 X4 E0.5\n"
        b"M83\n"
        b"G1 X5 E-0.2\n"
        b"G1 X6 E0\n"
        b"G1 X7 E0.25\n"
        b"T1\nG92 E10\nM82\n"
        b"G1 X8 E10\n"
        b"G1 X9 E10.5\n"
    )

    assert metrics["extrusion_move_count"] == 3
    assert metrics["positive_extrusion_by_tool"] == {"0": 2, "1": 1}
    assert metrics["positive_extrusion_tool_ids"] == [0, 1]


def test_toolpath_metrics_reject_pure_e_and_auxiliary_extrusion() -> None:
    from scripts.verify_native_svg_slicer_outputs import _toolpath_metrics

    metrics = _toolpath_metrics(
        b"M83\nT0\n"
        b"; FEATURE: Custom\nG1 E5\n"
        b"; FEATURE: Prime tower\nG1 X10 Y10 E1\n"
        b"; FEATURE: Outer wall\nG1 E0.5\n"
    )

    assert metrics["extrusion_move_count"] == 0
    assert metrics["positive_extrusion_by_tool"] == {}
    assert metrics["positive_extrusion_tool_ids"] == []


def test_toolpath_metrics_keeps_absolute_e_global_across_tool_changes() -> None:
    from scripts.verify_native_svg_slicer_outputs import _toolpath_metrics

    metrics = _toolpath_metrics(
        b"M82\nG92 E0\n; FEATURE: Outer wall\n"
        b"T0\nG1 X1 Y1 E10\n"
        b"T1\nG1 X2 Y2 E10\n"
        b"G1 X3 Y3 E10.5\n"
    )

    assert metrics["extrusion_move_count"] == 2
    assert metrics["positive_extrusion_by_tool"] == {"0": 1, "1": 1}
    assert metrics["positive_extrusion_tool_ids"] == [0, 1]


def test_coverage_probe_rejects_an_empty_interior_despite_material_extrusion() -> None:
    from scripts.verify_native_svg_slicer_outputs import _toolpath_metrics

    probe = {"x_mm": 5, "y_mm": 5, "z_mm": 0.08, "max_distance_mm": 0.12}
    wall_only = (
        b"G90\nM83\nG1 X0 Y0 Z0.08\n; FEATURE: Outer wall\n"
        b"G1 X10 Y0 E1\nG1 X10 Y10 E1\nG1 X0 Y10 E1\nG1 X0 Y0 E1\n"
    )
    missing = _toolpath_metrics(wall_only, coverage_probes=[probe])
    filled = _toolpath_metrics(
        wall_only + b"; FEATURE: Internal solid infill\nG1 X0 Y5\nG1 X10 Y5 E1\n",
        coverage_probes=[probe],
    )

    assert missing["extrusion_move_count"] > 0
    assert missing["coverage"][0]["covered"] is False
    assert missing["coverage"][0]["nearest_mm"] == pytest.approx(5)
    assert filled["coverage"][0]["covered"] is True


def test_coverage_probe_requires_the_requested_layer_and_material() -> None:
    from scripts.verify_native_svg_slicer_outputs import _toolpath_metrics

    probe = {
        "x_mm": 5, "y_mm": 5, "z_mm": 0.16,
        "max_distance_mm": 0.12, "tool_id": 1,
    }
    wrong = (
        b"G90\nM83\nG1 X0 Y5 Z0.08\n; FEATURE: Internal solid infill\n"
        b"T1\nG1 X10 E1\nG1 X0 Z0.16\nT0\nG1 X10 E1\n"
        b"; FEATURE: Prime tower\nT1\nG1 X0 E1\n"
    )
    assert not _toolpath_metrics(wrong, coverage_probes=[probe])["coverage"][0]["covered"]
    right = wrong + b"; FEATURE: Internal solid infill\nG1 X10 E1\n"
    assert _toolpath_metrics(right, coverage_probes=[probe])["coverage"][0]["covered"]


@pytest.mark.parametrize("command,y", [(b"G2", 1.0), (b"G3", -1.0)])
def test_coverage_probe_measures_arcs_instead_of_their_chords(
    command: bytes, y: float,
) -> None:
    from scripts.verify_native_svg_slicer_outputs import _toolpath_metrics

    metrics = _toolpath_metrics(
        b"G90\nM83\nG1 X-1 Y0 Z0.08\n; FEATURE: Outer wall\n"
        + command + b" X1 Y0 I1 J0 E1\n",
        coverage_probes=[
            {"x_mm": 0, "y_mm": y, "z_mm": 0.08, "max_distance_mm": 0.01},
            {"x_mm": 0, "y_mm": 0, "z_mm": 0.08, "max_distance_mm": 0.01},
        ],
    )

    assert [item["covered"] for item in metrics["coverage"]] == [True, False]


def test_coverage_probe_tracks_relative_z_and_full_circle_extrusion() -> None:
    from scripts.verify_native_svg_slicer_outputs import _toolpath_metrics

    metrics = _toolpath_metrics(
        b"G90\nM83\nG1 X-1 Y0 Z0.08\nG91\nG1 Z0.08\n"
        b"; FEATURE: Outer wall\nG2 I1 J0 E1\n",
        coverage_probes=[
            {"x_mm": 0, "y_mm": 1, "z_mm": z, "max_distance_mm": 0.01}
            for z in (0.08, 0.16)
        ],
    )

    assert metrics["extrusion_move_count"] == 1
    assert [item["covered"] for item in metrics["coverage"]] == [False, True]


def test_coverage_probe_rejects_a_move_between_layers() -> None:
    from scripts.verify_native_svg_slicer_outputs import _toolpath_metrics

    metrics = _toolpath_metrics(
        b"G90\nM83\nG1 X0 Y0 Z0.08\n; FEATURE: Outer wall\n"
        b"G1 X10 Y0 Z0.16 E1\n",
        coverage_probes=[
            {"x_mm": 5, "y_mm": 0, "z_mm": 0.16, "max_distance_mm": 0.01},
        ],
    )

    assert metrics["coverage"][0]["covered"] is False


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
            "; FEATURE: Outer wall\nT0\nG1 X1 Y2 E0.1\n",
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
    assert result["executable"] == "slicer"
    assert result["command"][0] == "<BambuStudio-executable>"
    assert result["command"][-1] == "fixture.3mf"
    assert result["command"][-2] == "<isolated-run-directory>"
    assert str(tmp_path) not in json.dumps(result)


def test_slicer_validation_requires_positive_extrusion_for_every_material(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from scripts import verify_native_svg_slicer_outputs as reality

    project = tmp_path / "two-materials.3mf"
    _write_minimal_3mf(project, extruders=("1", "2"))
    executable = tmp_path / "slicer"
    executable.touch()

    def fake_run_command(command, *, timeout_seconds, cwd=None):
        if "--help" in command:
            return 0, "BambuStudio-test:\n", "", 0.01
        (cwd / "plate_1.gcode").write_text(
            "M83\n; FEATURE: Outer wall\nT0\nG1 X1 Y2 E0.1\n",
            encoding="utf-8",
        )
        return 0, "", "", 0.01

    monkeypatch.setattr(reality, "_run_command", fake_run_command)
    result = reality._validate_slicer(
        "BambuStudio",
        executable,
        project,
        tmp_path / "toolpaths",
        timeout_seconds=10,
        validation_runs=2,
    )

    assert result["status"] == "failed"
    assert result["reason"] == "toolpath_missing_material_extrusion"
    assert result["runs"][0]["missing_expected_tool_ids"] == [1]


def test_slicer_validation_fails_when_a_printable_region_has_no_toolpath(
    tmp_path: Path, monkeypatch,
) -> None:
    from scripts import verify_native_svg_slicer_outputs as reality

    project = tmp_path / "fixture.3mf"
    _write_minimal_3mf(project)
    executable = tmp_path / "slicer"
    executable.touch()

    def fake_run_command(command, *, timeout_seconds, cwd=None):
        if "--help" in command:
            return 0, "BambuStudio-test:\n", "", 0.01
        (cwd / "plate_1.gcode").write_text(
            "G90\nM83\nG1 X0 Y0 Z0.08\n; FEATURE: Outer wall\nG1 X10 E1\n",
            encoding="utf-8",
        )
        return 0, "", "", 0.01

    monkeypatch.setattr(reality, "_run_command", fake_run_command)
    result = reality._validate_slicer(
        "BambuStudio", executable, project, tmp_path / "toolpaths",
        timeout_seconds=10,
        coverage_probes=[
            {"x_mm": 5, "y_mm": 5, "z_mm": 0.08, "max_distance_mm": 0.12},
        ],
    )

    assert result["status"] == "failed"
    assert result["reason"] == "toolpath_missing_region_extrusion"


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


def test_checked_in_reality_report_is_portable_and_material_complete() -> None:
    report_text = CHECKED_IN_REPORT.read_text(encoding="utf-8")
    report = json.loads(report_text)

    assert report["status"] == "passed"
    assert "/Applications/" not in report_text
    assert "/private/tmp/" not in report_text
    assert ":\\" not in report_text
    assert report["artifacts"]["native_version"] == "0.1.1"
    for slicer_name in ("BambuStudio", "OrcaSlicer"):
        slicer = report["slicers"][slicer_name]
        expected_tool_ids = set(slicer["input"]["expected_tool_ids"])
        assert expected_tool_ids == {0, 1, 2, 3, 4}
        assert slicer["status"] == "passed"
        assert slicer["stable_across_runs"] is True
        assert slicer["command"][0] == f"<{slicer_name}-executable>"
        assert slicer["command"][-2] == "<isolated-run-directory>"
        for run_index, run in enumerate(slicer["runs"], start=1):
            assert run["output_directory"] == f"run-{run_index}"
            assert run["missing_expected_tool_ids"] == []
            positive = {
                int(tool_id): count
                for tool_id, count in run["toolpath"][
                    "positive_extrusion_by_tool"
                ].items()
            }
            assert all(positive[tool_id] > 0 for tool_id in expected_tool_ids)
