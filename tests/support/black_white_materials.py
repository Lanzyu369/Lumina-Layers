"""Current black/white profile fixtures with real portable captures."""
from uuid import uuid4

from core.backed_gradient_backing_store import (
    backing_material_snapshot, create_black_white_pair, list_backing_materials,
)
from core.backed_gradient_material import BackedGradientMaterialModel, BackedGradientReference
from core.backed_gradient_store import THICKNESSES_MM
from core.black_white_material_profiles import publish_black_white_profiles


def register_black_white(store, reference):
    parsed = BackedGradientReference.from_dict(reference)
    names = reference.get("source", {}).get("materials", {"W": "Original White", "K": "Original Black"})
    create_black_white_pair(store, {"white": {"name": names["W"]}, "black": {"name": names["K"]}})
    pair = {item["role"]: item for item in list_backing_materials(store) if item["status"] == "draft"}
    entries = []
    for role, item in pair.items():
        component = parsed.white if role == "W" else parsed.black
        opposite = "K" if role == "W" else "W"
        model = BackedGradientMaterialModel(parsed)
        for thickness in (*THICKNESSES_MM, 0.):
            store.save_capture(item["dataset_id"], {
                "capture_id": str(uuid4()), "measurement_id": str(uuid4()), "material_symbol": role,
                "backing": opposite if thickness else role, "sample_role": "coated" if thickness else "bare_backing",
                "overlay_mm": thickness, "reflectance_percent_xyz": model.predict_backed(component, opposite, thickness or 3.).tolist(),
            })
        snapshot = backing_material_snapshot(store, item["dataset_id"])
        entries.append((snapshot, {"component": component.to_dict(), "reference": reference, "status": "complete"}))
    return {item["role"]: item for item in publish_black_white_profiles(store, entries)}
