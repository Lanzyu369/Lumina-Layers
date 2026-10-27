"""Coating follows the selected materials without a separate material choice."""

import pytest

from core import export_materials


@pytest.mark.parametrize(("types", "expected"), [
    (["PLA", "PLA"], "PLA"),
    (["PLA Basic", "PLA+"], "PLA"),
    (["PETG", "PETG"], "PETG"),
    (["petg", "PETG HF"], "PETG"),
    (["PETG", "PETG", "PLA"], "PLA"),
    (["PLA", "PETG"], "PLA"),
    (["ABS", "ABS"], "ABS"),
    ([None, None], "PLA"),
    ([], "PLA"),
])
def test_coating_automatically_follows_a_uniform_material_type(types, expected):
    names = [f"材料 {index}" for index in range(len(types))]
    material = export_materials.resolve_coating_material(
        None, slot_names=names, preview_colors={},
        material_types={**dict(zip(names, types)), "unselected": "TPU"},
    )
    assert material.name == "Coating"
    assert material.material_type == expected


@pytest.mark.parametrize("reference", [
    None, {}, {"source": "palette", "key": "removed"},
    {"source": "material_archive", "key": "missing-clear-pla"},
])
def test_legacy_coating_choices_cannot_block_or_override_automatic_material(reference):
    material = export_materials.resolve_coating_material(
        reference, slot_names=["白", "蓝"], preview_colors={},
        material_types={"白": "PETG", "蓝": "PETG"},
    )
    assert material.name == "Coating"
    assert material.material_type == "PETG"


def test_legacy_material_names_can_supply_missing_polymer_metadata():
    material = export_materials.resolve_coating_material(
        None, slot_names=["白 PETG", "PETG 蓝"], preview_colors={},
        material_types={"白 PETG": None, "PETG 蓝": None},
    )
    assert material.material_type == "PETG"


def test_configure_coating_preserves_source_materials_and_optical_palette():
    ctx = {
        "enable_coating": True,
        "slot_names": ["七色白", "七色蓝"],
        "preview_colors": {0: [250, 250, 250, 255], 1: [20, 40, 230, 255]},
        "material_types": {"七色白": "PETG", "七色蓝": "PETG"},
    }
    material = export_materials.configure_coating_material(ctx)
    assert ctx["resolved_coating_material"] == material
    assert ctx["slot_names"] == ["七色白", "七色蓝"]
    assert ctx["material_types"] == {"七色白": "PETG", "七色蓝": "PETG", "Coating": "PETG"}
    assert ctx["preview_colors"][0] == [250, 250, 250, 255]
    assert ctx["preview_colors"]["Coating"] == [*material.rgb, 255]


def test_disabled_coating_does_not_add_a_material():
    ctx = {"enable_coating": False}
    assert export_materials.configure_coating_material(ctx) is None
    assert ctx == {"enable_coating": False}


@pytest.mark.parametrize(("types", "expected"), [
    (["PETG", "PETG"], "PETG"), (["PETG", "PLA"], "PLA"),
])
def test_native_preflight_uses_the_same_automatic_material(types, expected):
    from config import LUTMetadata, PaletteEntry
    from core.export_material_selection import _source_materials

    records = _source_materials(
        {"enable_coating": True},
        {"lut_metadata": LUTMetadata(palette=[
            PaletteEntry(color=name, material=kind)
            for name, kind in zip(["白", "蓝"], types)
        ])},
    )
    assert records[-1] == {
        "name": "Coating", "colour": "#C8C8C8", "material_type": expected,
    }
