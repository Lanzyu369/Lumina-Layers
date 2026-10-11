"""Native SVG wheels include and execute the compensation extension."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "svg_compensation_wheel_verifier",
    ROOT / "native/lumina-svg-core/tools/verify_wheel.py",
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.mark.parametrize("missing", ["_lumina_svg_compensation.so", "THIRD_PARTY_LICENSES/ChromaPrint3D.txt"])
def test_wheel_cannot_ship_without_compensation_or_its_license(tmp_path, missing):
    wheel = tmp_path / "incomplete.whl"
    names = ["_lumina_svg_core.so", "_lumina_svg_compensation.so", "LICENSE", "THIRD_PARTY_NOTICES.md"]
    names += [f"THIRD_PARTY_LICENSES/{name}.txt" for name in (
        "Clipper2", "FreeType-Project", "LunaSVG", "PlutoVG", "stb", "pybind11", "ChromaPrint3D",
    )]
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in names:
            if name != missing:
                archive.writestr(f"lumina_svg_core/{name}", "test archive entry")
    with pytest.raises(AssertionError):
        verifier.verify_wheel(wheel)


def test_installed_wheel_exercises_real_compensation():
    verifier.verify_installed_compensation()


def test_cli_exercises_compensation_before_server_start():
    completed = subprocess.run(
        [sys.executable, str(ROOT / "api_server.py"), "--svg-hole-compensation-self-test"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["status"] == "ok"
    assert result["filled_holes"] == 1
    assert result["input_regions"] == 2
    assert result["output_regions"] == 3
    assert result["added_area_mm2"] == pytest.approx(0.16)
