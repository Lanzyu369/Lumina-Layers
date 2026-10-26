"""JSON command contracts for packaged material sampling diagnostics."""

from __future__ import annotations

from importlib import resources
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

import api_server
from core import material_candidate_sampling as sampling


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "status": "ok", "resource_present": True, "dimensions": 10,
    "sample_count": 1024, "sobol_unique_points": 1024,
    "candidate_budget": 4096, "candidate_count": 4096,
}


@pytest.fixture
def diagnostic_boundary(monkeypatch):
    monkeypatch.setattr(
        "api.structured_logging.configure_structured_logging", lambda: None,
    )

    def forbidden_server(_env):
        raise AssertionError("diagnostic commands must not start a server")

    monkeypatch.setattr(api_server, "_run_server", forbidden_server)


def test_material_sampling_cli_exercises_installed_scipy_without_server(
    diagnostic_boundary, capsys,
) -> None:
    assert api_server.main(["--material-sampling-self-test"]) == 0
    assert json.loads(capsys.readouterr().out) == EXPECTED


def test_material_sampling_cli_succeeds_in_fresh_process() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "api_server.py"), "--material-sampling-self-test"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == EXPECTED


def test_material_sampling_cli_rejects_missing_resource_even_with_rng_fallback(
    diagnostic_boundary, monkeypatch, capsys, tmp_path,
) -> None:
    monkeypatch.setattr(resources, "files", lambda _package: tmp_path)
    assert api_server.main(["--material-sampling-self-test"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "error", "error_type": "MaterialSamplingSelfTestError",
        "reason_code": "sobol_resource_missing",
    }
    assert str(tmp_path) not in json.dumps(payload)


@pytest.mark.parametrize("fault", ["collapsed", "short", "nan", "out_of_range"])
def test_material_sampling_cli_rejects_bad_sobol_instead_of_hiding_it(
    diagnostic_boundary, monkeypatch, capsys, fault: str,
) -> None:
    def broken(count, layers, seed):
        points = np.random.default_rng(seed).random((count, layers))
        if fault == "collapsed":
            points[:] = 0.25
        elif fault == "short":
            points = points[:-1]
        else:
            points[0, 0] = np.nan if fault == "nan" else 1.0
        return points

    monkeypatch.setattr(sampling, "_sobol_points", broken)
    assert api_server.main(["--material-sampling-self-test"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "error", "error_type": "MaterialSamplingSelfTestError",
        "reason_code": "sobol_samples_invalid",
    }


def test_material_sampling_cli_rejects_underfilled_real_recipe_path(
    diagnostic_boundary, monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(
        sampling, "generate_candidate_recipes",
        lambda **_kwargs: SimpleNamespace(recipes=np.zeros((61, 10), dtype=np.uint16)),
    )
    assert api_server.main(["--material-sampling-self-test"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "error", "error_type": "MaterialSamplingSelfTestError",
        "reason_code": "candidate_samples_invalid",
    }


@pytest.mark.parametrize("unsafe_reason_code", [False, True])
def test_material_sampling_cli_sanitizes_unexpected_dependency_errors(
    diagnostic_boundary, monkeypatch, capsys, unsafe_reason_code: bool,
) -> None:
    def unavailable(*_args):
        error = OSError("/private/customer/path/scipy-resource.npz")
        if unsafe_reason_code:
            error.reason_code = "/private/customer/path/scipy-resource.npz"
        raise error

    monkeypatch.setattr(sampling, "_sobol_points", unavailable)
    assert api_server.main(["--material-sampling-self-test"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "error", "error_type": "OSError",
        "reason_code": "material_sampling_self_test_failed",
    }
    assert "/private/customer" not in json.dumps(payload)
