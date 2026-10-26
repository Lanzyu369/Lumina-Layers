"""Regression contract for the retired Vector extrusion implementation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from packaging.requirements import Requirement
from packaging.version import Version

import core.layered_meshing as layered_meshing
from core.layered_meshing import LayeredMeshPolicy, build_labeled_surface_mesh


_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_shapely_runtime_contract_supports_constrained_cap_triangulation() -> None:
    """Frozen/local installs must include the holed-cap API used in production."""

    requirements = [
        Requirement(line.strip())
        for line in (_REPO_ROOT / "requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
        and not line.lstrip().startswith(("#", "-r ", "--requirement "))
    ]
    shapely_requirement = next(
        requirement
        for requirement in requirements
        if requirement.name.lower() == "shapely"
    )

    assert Version("2.1.0") in shapely_requirement.specifier
    assert Version("2.0.9") not in shapely_requirement.specifier




def test_production_layered_meshing_does_not_run_full_output_audits(
    monkeypatch,
) -> None:
    """Expensive whole-output audits remain an explicit development option."""

    assert LayeredMeshPolicy().validate_output is False
    monkeypatch.setattr(
        layered_meshing,
        "_validate_component_arrays",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("production called the full mesh audit")
        ),
    )
    monkeypatch.setattr(
        layered_meshing,
        "_indexed_face_edges_are_paired",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("production scanned every generated edge")
        ),
    )

    labels = np.array([[[1, 1], [1, -1]]], dtype=np.int16)
    mesh = build_labeled_surface_mesh(labels, material_id=1, height_px=2)

    assert mesh is not None
    assert mesh.is_watertight
