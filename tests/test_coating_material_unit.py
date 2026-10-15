"""Explicit auxiliary material identity follows the source palette and archives."""

from types import SimpleNamespace

import pytest

from core import export_materials


def resolve(reference):
    return export_materials.resolve_coating_material(
        reference,
        slot_names=["七色白", "七色蓝"],
        preview_colors={0: [250, 250, 250, 255], 1: [20, 40, 230, 255]},
        material_types={"七色白": "PETG", "七色蓝": "PETG"},
    )


def test_selected_palette_material_preserves_name_type_and_rgb():
    material = resolve({"source": "palette", "key": "七色白"})
    assert material.name == "七色白"
    assert material.material_type == "PETG"
    assert material.rgb == (250, 250, 250)


def test_independent_archive_preserves_intentional_mixed_type(monkeypatch):
    loaded = []

    def load(names):
        loaded.extend(names)
        return [SimpleNamespace(name="透明", material_type="PLA", estimated_rgb=[240, 241, 242])]

    monkeypatch.setattr(export_materials, "load_materials", load)
    material = resolve({"source": "material_archive", "key": "clear-archive"})
    assert loaded == ["clear-archive"]
    assert material.material_type == "PLA"
    assert material.rgb == (240, 241, 242)
    assert material.name == "Coating: 透明"


def test_legacy_palette_type_remains_unknown_for_native_preset_resolution():
    material = export_materials.resolve_coating_material(
        {"source": "palette", "key": "White PETG"}, slot_names=["White PETG"],
        preview_colors={0: [250, 250, 250, 255]}, material_types={"White PETG": None},
    )
    assert material.name == "White PETG"
    assert material.material_type is None


@pytest.mark.parametrize("reference", [None, {}, {"source": "palette", "key": "removed"}, {"source": "guess", "key": "PLA"}])
def test_missing_or_stale_selection_never_guesses_pla(reference):
    with pytest.raises(ValueError, match="[Cc]oating"):
        resolve(reference)


def test_configure_coating_binds_export_facts_without_changing_optical_palette():
    ctx = {
        "enable_coating": True,
        "coating_material": {"source": "palette", "key": "七色白"},
        "slot_names": ["七色白", "七色蓝"],
        "preview_colors": {0: [250, 250, 250, 255], 1: [20, 40, 230, 255]},
        "material_types": {"七色白": "PETG", "七色蓝": "PETG"},
    }
    export_materials.configure_coating_material(ctx)
    assert ctx["resolved_coating_material"].name == "七色白"
    assert ctx["slot_names"] == ["七色白", "七色蓝"]
    assert ctx["material_types"]["七色白"] == "PETG"


def test_native_preflight_includes_exact_coating_facts(monkeypatch):
    from config import LUTMetadata, PaletteEntry
    from core.export_material_selection import _source_materials

    monkeypatch.setattr(export_materials, "load_materials", lambda names: [
        SimpleNamespace(name="透明", material_type="PLA", estimated_rgb=[240, 241, 242]),
    ])
    records = _source_materials(
        {"enable_coating": True, "coating_material": {"source": "material_archive", "key": "clear"},
         "native_filament_profiles": {"Coating: 透明": "Bambu PLA Basic @BBL H2D"}},
        {"lut_metadata": LUTMetadata(palette=[PaletteEntry(color="白", material="PETG")])},
    )
    assert records[-1] == {
        "name": "Coating: 透明", "colour": "#F0F1F2", "material_type": "PLA",
        "native_filament_profile_name": "Bambu PLA Basic @BBL H2D",
    }
