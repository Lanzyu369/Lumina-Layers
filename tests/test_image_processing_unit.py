from __future__ import annotations

import logging
from unittest.mock import patch

import numpy as np

from core import image_processing


def _minimal_lut_payload() -> dict:
    return {
        "lut_rgb": np.array([[255, 255, 255]], dtype=np.uint8),
        "lut_lab": np.array([[255.0, 128.0, 128.0]], dtype=np.float64),
        "ref_stacks": np.zeros((1, 5), dtype=np.int32),
        "kdtree": None,
        "layer_count": 5,
    }


def test_lut_constrained_disables_hue_protection_with_structured_event(
    caplog,
) -> None:
    target_logger = logging.getLogger(image_processing.log.name)
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)

    try:
        with patch.object(
            image_processing.LuminaImageProcessor,
            "_load_lut_data",
            return_value=_minimal_lut_payload(),
        ):
            processor = image_processing.LuminaImageProcessor(
                "unused.npz",
                "4-Color (RYBW)",
                hue_weight=0.5,
                use_lut_constrained=True,
            )
    finally:
        target_logger.removeHandler(caplog.handler)

    assert processor.use_lut_constrained is True
    assert processor.hue_weight == 0.0
    assert processor.hue_matcher is None
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None)
        == "image_processor_hue_protection_disabled"
    ]
    assert len(records) == 1
    assert records[0].requested_hue_weight == 0.5
    assert records[0].reason == "lut_constrained"
