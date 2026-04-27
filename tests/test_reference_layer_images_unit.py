from __future__ import annotations

import os
import tempfile

import numpy as np
from PIL import Image

from api.file_registry import FileRegistry
from api.routers.converter.preview import get_layer_images
from api.session_store import SessionStore
from core.converter import generate_preview_cached


def test_reference_colordb_layer_images_are_available() -> None:
    """ReferenceDB previews should expose per-layer preview images through the layer-images route."""
    lut_path = os.path.join(
        "reference",
        "ChromaPrint3D",
        "data",
        "dbs",
        "PLA",
        "BambuLab",
        "RYBW_008_5L.json",
    )
    image = np.zeros((20, 20, 4), dtype=np.uint8)
    image[:10, :10, :3] = [255, 255, 255]
    image[:10, 10:, :3] = [255, 230, 0]
    image[10:, :10, :3] = [220, 20, 60]
    image[10:, 10:, :3] = [0, 100, 240]
    image[:, :, 3] = 255

    with tempfile.TemporaryDirectory() as tmpdir:
        image_path = os.path.join(tmpdir, "reference_layer_preview.png")
        Image.fromarray(image).save(image_path)

        _preview, cache, _status = generate_preview_cached(
            image_path=image_path,
            lut_path=lut_path,
            target_width_mm=20,
            color_mode="4-Color (RYBW)",
            modeling_mode="high-fidelity",
            color_layers=5,
            layer_height_mm=0.08,
            quantize_colors=8,
            enable_cleanup=False,
            is_dark=True,
            hue_weight=0.0,
            chroma_gate=15.0,
        )

    store = SessionStore(ttl=60)
    registry = FileRegistry()
    session_id = store.create()
    store.put(session_id, "preview_cache", cache)

    response = get_layer_images(session_id=session_id, store=store, registry=registry)

    assert response["session_id"] == session_id
    assert len(response["layers"]) == 5
    assert response["layers"][0]["name"] == "White"
    assert response["layers"][-1]["name"] == "Layer 4"
    assert all(layer["url"].startswith("/api/files/") for layer in response["layers"])
