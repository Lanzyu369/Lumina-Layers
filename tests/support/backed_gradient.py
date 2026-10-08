"""Deterministic same-batch inputs for backed-gradient core and API tests."""
from __future__ import annotations

import numpy as np

from core.backed_gradient_optics import BackedGradientOptics, CORE_MATERIAL_SYMBOLS, MATERIAL_SYMBOLS
from core.backed_gradient_store import THICKNESSES_MM


def synthetic_operator(family: str, *, optional_materials: bool = False) -> BackedGradientOptics:
    values = np.ones((len(MATERIAL_SYMBOLS), 3, 2))
    if family == "affine":
        values[..., 0] = 3
        values[..., 1] = .4
        values[3, :, 0] = .8
        values[3, :, 1] = 1
        values[4, :, 0] = 8
        values[4, :, 1] = .02
        values[0, :, 1] = [.5, .2, .1]
        values[1, :, 1] = [1.08, .9, .1]
        values[2, :, 1] = [.05, .1, .6]
    else:
        values[..., 0] = .4
        values[..., 1] = 1
        values[3, :, 0] = .03
        values[3, :, 1] = 3
        values[4, :, 0] = 7
        values[4, :, 1] = .08
        values[0, :, 0] = [.3, 2, 3]
        values[2, :, 0] = [3, 2, .3]
    present = MATERIAL_SYMBOLS if optional_materials else CORE_MATERIAL_SYMBOLS
    return BackedGradientOptics(family, values, {"W": [97, 98, 100.5], "K": [0, 0, 0]}, fitted_materials=present)


def synthetic_snapshot(family: str = "affine", *, optional_materials: bool = False) -> dict:
    model = synthetic_operator(family, optional_materials=optional_materials)
    samples = [{"record_id": f"{symbol}-{backing}-{thickness}", "material_symbol": symbol,
                "backing": backing, "overlay_mm": thickness,
                "reflectance_percent_xyz": model.predict_backed(symbol, backing, thickness).tolist(),
                "sample_role": "coated"}
               for symbol in model.fitted_materials for backing in ("W", "K") for thickness in THICKNESSES_MM]
    return {"dataset_id": "synthetic-batch", "dataset_revision": 1, "input_hash": "synthetic-input",
            "materials": {symbol: symbol for symbol in model.fitted_materials},
            "reference_anchors": {key: value.tolist() for key, value in model.anchors.items()},
            "conditions": {"total_mm": 3., "observation_face": "bed_contact", "diffuser_removed": True},
            "samples": samples, "selected_record_ids": [row["record_id"] for row in samples]}
