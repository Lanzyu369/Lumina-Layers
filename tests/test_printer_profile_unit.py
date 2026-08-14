"""Unit tests for printer profile registry and template loading.
打印机配置注册表与模板加载单元测试。

Covers:
  - Task 7.1: Registry queries, default fallback, template loading
  - Task 7.2: 3MF export uses correct template (printer_model key, cache)
  - Task 0.2 nozzle support: profile metadata and nozzle-size-aware resolution
"""

import json
from pathlib import Path
import pytest

from config import (
    PrinterProfile,
    PRINTER_PROFILES,
    DEFAULT_PRINTER_ID,
    get_printer_profile,
    list_printer_profiles,
    normalize_printer_profile_id,
    normalize_slicer_software_id,
)
from utils.bambu_3mf_writer import load_printer_template, _PRINTER_TEMPLATE_CACHE

# ── Required fields every PrinterProfile must have ──

REQUIRED_FIELDS = (
    "id",
    "display_name",
    "brand",
    "bed_width",
    "bed_depth",
    "bed_height",
    "nozzle_count",
    "is_dual_head",
    "supported_nozzle_sizes",
    "template_file",
)


# ====================================================================
# Task 7.1 — Registry queries, default fallback, template loading
# ====================================================================


class TestListPrinterProfiles:
    """list_printer_profiles() returns all registered printers."""

    def test_returns_all_printers(self) -> None:
        profiles = list_printer_profiles()
        assert len(profiles) == len(PRINTER_PROFILES)

    def test_returns_list_of_printer_profiles(self) -> None:
        profiles = list_printer_profiles()
        for p in profiles:
            assert isinstance(p, PrinterProfile)


class TestGetPrinterProfile:
    """get_printer_profile() returns correct profile or falls back."""

    def test_h2d_returns_correct_profile(self) -> None:
        profile = get_printer_profile("bambu-h2d")
        assert profile.id == "bambu-h2d"
        assert profile.display_name == "Bambu Lab H2D"
        assert profile.bed_width == 350
        assert profile.bed_depth == 320
        assert profile.bed_height == 325
        assert profile.nozzle_count == 2
        assert profile.is_dual_head is True

    def test_invalid_id_falls_back_to_h2d(self) -> None:
        profile = get_printer_profile("invalid-id")
        assert profile.id == DEFAULT_PRINTER_ID
        assert profile.id == "bambu-h2d"

    def test_a1_mini_returns_correct_profile(self) -> None:
        profile = get_printer_profile("bambu-a1-mini")
        assert profile.id == "bambu-a1-mini"
        assert profile.display_name == "Bambu Lab A1 mini"
        assert profile.bed_width == 180
        assert profile.bed_depth == 180
        assert profile.bed_height == 180
        assert profile.nozzle_count == 1
        assert profile.is_dual_head is False

    def test_legacy_underscore_id_is_normalized(self) -> None:
        profile = get_printer_profile("bambu_h2d")
        assert profile.id == "bambu-h2d"

    def test_supported_nozzle_sizes_include_0_2_for_p1s(self) -> None:
        profile = get_printer_profile("bambu-p1s")
        assert "0.2" in profile.supported_nozzle_sizes
        assert "0.4" in profile.supported_nozzle_sizes


class TestNormalizeSettingsIdentifiers:
    """Legacy settings IDs are normalized to canonical values."""

    def test_normalize_printer_profile_id(self) -> None:
        assert normalize_printer_profile_id("BAMBU_H2D") == "bambu-h2d"

    def test_normalize_slicer_software_id(self) -> None:
        assert normalize_slicer_software_id("orca_slicer") == "OrcaSlicer"

    def test_normalize_anycubic_slicer_software_id(self) -> None:
        assert normalize_slicer_software_id("anycubic_slicer_next") == "AnycubicSlicerNext"

    def test_normalize_flash_studio_software_id(self) -> None:
        assert normalize_slicer_software_id("flash studio desktop") == "FlashStudio"


class TestProfileRequiredFields:
    """Every profile has all required fields."""

    @pytest.mark.parametrize("printer_id", list(PRINTER_PROFILES.keys()))
    def test_profile_has_all_required_fields(self, printer_id: str) -> None:
        profile = PRINTER_PROFILES[printer_id]
        for field in REQUIRED_FIELDS:
            assert hasattr(profile, field), f"{printer_id} missing field: {field}"
            assert getattr(profile, field) is not None, f"{printer_id}.{field} is None"


class TestLoadPrinterTemplate:
    """load_printer_template() returns non-empty dicts."""

    def test_h2d_template_non_empty(self) -> None:
        template = load_printer_template("bambu-h2d")
        assert isinstance(template, dict)
        assert len(template) > 0

    def test_a1_mini_template_non_empty(self) -> None:
        template = load_printer_template("bambu-a1-mini")
        assert isinstance(template, dict)
        assert len(template) > 0

    def test_legacy_slicer_id_resolves_orca_template(self) -> None:
        profile = get_printer_profile("bambu-h2d")
        assert profile.get_template_file("orca_slicer") == "orca_h2d.json"

    def test_nozzle_size_resolves_0_2_sibling_template(self) -> None:
        profile = get_printer_profile("bambu-p1s")
        assert profile.get_template_file("BambuStudio", nozzle_size=0.2) == "bambu_p1s_0_2.json"
        assert profile.get_template_file("OrcaSlicer", nozzle_size="0.2") == "orca_p1s_0_2.json"

    def test_anycubic_template_uses_anycubic_slicer_mapping(self) -> None:
        template = load_printer_template("anycubic-kobra-s1", slicer="AnycubicSlicerNext")
        assert template["printer_model"] == "Anycubic Kobra S1"
        assert template["printable_area"] == ["0x0", "250x0", "250x250", "0x250"]
        assert template["printable_height"] == "250"

    @pytest.mark.parametrize(
        ("printer_id", "model", "nozzle_size", "physical_tools", "source_profile_name"),
        [
            *[
                ("flashforge-ad5x", "Flashforge AD5X", nozzle, 1, f"Flashforge AD5X {nozzle} nozzle")
                for nozzle in ("0.25", "0.4")
            ],
            *[
                ("flashforge-creator-5", "Flashforge Creator 5", nozzle, 4, f"Flashforge Creator 5 {nozzle} nozzle")
                for nozzle in ("0.25", "0.4")
            ],
            *[
                ("flashforge-creator-5-pro", "Flashforge Creator 5 Pro", nozzle, 4, f"Flashforge Creator 5 Pro {nozzle} nozzle")
                for nozzle in ("0.25", "0.4")
            ],
            ("flashforge-guider-3-ultra", "Flashforge Guider 3 Ultra", "0.4", 2, "Flashforge Guider 3 Ultra 0.4 Nozzle"),
            *[
                (
                    "flashforge-guider4",
                    "Flashforge Guider4",
                    nozzle,
                    1,
                    f"Flashforge Guider4 {nozzle} nozzle",
                )
                for nozzle in ("0.25", "0.4")
            ],
            *[
                (
                    "flashforge-guider4-pro",
                    "Flashforge Guider4 Pro",
                    nozzle,
                    1,
                    f"Flashforge Guider4 Pro {nozzle} nozzle",
                )
                for nozzle in ("0.25", "0.4")
            ],
        ],
    )
    def test_flashforge_templates_keep_native_nozzle_and_machine_identity(
        self,
        printer_id: str,
        model: str,
        nozzle_size: str,
        physical_tools: int,
        source_profile_name: str,
    ) -> None:
        profile = get_printer_profile(printer_id)
        template_name = profile.get_template_file("FlashStudio", nozzle_size=nozzle_size)
        template = load_printer_template(
            printer_id,
            slicer="FlashStudio",
            nozzle_size=nozzle_size,
        )

        assert (Path("printer_profiles") / template_name).exists()
        assert template["printer_model"] == model
        assert template["printer_settings_id"] == source_profile_name
        assert template["nozzle_diameter"] == [nozzle_size] * physical_tools
        assert template["version"] == "2.3.2"
        assert template["filament_vendor"] == ["Flashforge"] * 8
        assert "Flashforge" in str(template["default_filament_profile"])

    def test_load_printer_template_reads_0_2_variant(self) -> None:
        template = load_printer_template("bambu-p1s", nozzle_size=0.2)
        assert template["nozzle_diameter"] == ["0.2"]
        assert "0.2 nozzle" in template["default_print_profile"]

    def test_h2d_0_2_template_uses_official_0_2_process_preset_ids(self) -> None:
        template = load_printer_template("bambu-h2d", nozzle_size="0.2")
        assert template["print_settings_id"] == "0.08mm Extra Fine @BBL H2D 0.2 nozzle"
        assert template["inherits_group"][0] == "0.08mm Extra Fine @BBL H2D 0.2 nozzle"
        assert template["top_surface_line_width"] == "0.22"
        assert template["support_line_width"] == "0.22"

    @pytest.mark.parametrize(
        ("printer_id", "process_id"),
        [
            ("bambu-lab-a2l", "0.08mm High Quality @BBL A2L 0.2 nozzle"),
            ("bambu-lab-x2d", "0.08mm High Quality @BBL X2D 0.2 nozzle"),
        ],
    )
    def test_new_bambu_0_2_templates_keep_official_process_identity(
        self,
        printer_id: str,
        process_id: str,
    ) -> None:
        template = load_printer_template(printer_id, nozzle_size="0.2")

        assert template["print_settings_id"] == process_id
        assert template["inherits_group"][0] == process_id
        assert "0.2 nozzle" in template["default_print_profile"]
        assert template["print_compatible_printers"] == [template["printer_settings_id"]]


# ====================================================================
# Task 7.2 — 3MF export uses correct template
# ====================================================================


class TestTemplatePrinterModelKey:
    """Templates contain correct printer_model key."""

    def test_h2d_template_has_printer_model(self) -> None:
        template = load_printer_template("bambu-h2d")
        assert "printer_model" in template

    def test_p1s_template_has_correct_printer_model(self) -> None:
        template = load_printer_template("bambu-p1s")
        assert "printer_model" in template
        # The template's printer_model should identify the P1S
        assert "P1S" in template["printer_model"]

    def test_invalid_id_falls_back_to_valid_template(self) -> None:
        template = load_printer_template("invalid-id")
        assert isinstance(template, dict)
        assert len(template) > 0


class TestTemplateCache:
    """Template cache returns same data on repeated calls."""

    def test_cache_returns_same_data(self) -> None:
        first = load_printer_template("bambu-h2d")
        second = load_printer_template("bambu-h2d")
        assert first == second

    def test_cache_distinguishes_nozzle_size_variants(self) -> None:
        _PRINTER_TEMPLATE_CACHE.clear()
        load_printer_template("bambu-p1s", nozzle_size=0.2)
        load_printer_template("bambu-p1s", nozzle_size=0.4)
        assert len(_PRINTER_TEMPLATE_CACHE) == 2


class TestCheckedInNozzleVariants:
    """Repository contains 0.2 siblings for profiles that declare 0.2 support."""

    def test_every_base_template_has_0_2_sibling(self) -> None:
        profiles_dir = Path(__file__).resolve().parents[1] / "printer_profiles"
        base_template_names: set[str] = set()
        for profile in list_printer_profiles():
            if "0.2" not in profile.supported_nozzle_sizes:
                continue
            slicers = list(profile.slicer_templates)
            if profile.template_file.startswith("bambu_"):
                slicers.append("BambuStudio")
            for slicer in slicers:
                base_template_names.add(profile.get_template_file(slicer, nozzle_size="0.4"))

        missing = [
            name
            for name in sorted(base_template_names)
            if not (profiles_dir / name).with_name(
                f"{Path(name).stem}_0_2.json"
            ).exists()
        ]

        assert not missing, f"Missing 0.2 template siblings: {missing}"


class TestLuminaLayerHeightContract:
    """Slicer layers must not span multiple physical Lumina material layers."""

    def test_first_layer_print_height_matches_0_08_model_layer(self) -> None:
        profiles_dir = Path(__file__).resolve().parents[1] / "printer_profiles"
        template_names: set[str] = set()
        for profile in list_printer_profiles():
            slicers = {*profile.slicer_templates, "BambuStudio", "OrcaSlicer"}
            for slicer in slicers:
                for nozzle_size in ("0.4", "0.2"):
                    template_names.add(
                        profile.get_template_file(
                            slicer,
                            nozzle_size=nozzle_size,
                        )
                    )

        mismatches = []
        for template_name in sorted(template_names):
            template_path = profiles_dir / template_name
            if not template_path.is_file():
                continue
            settings = json.loads(template_path.read_text(encoding="utf-8"))
            layer_height = str(settings.get("layer_height") or "").strip()
            first_layer_height = str(
                settings.get("initial_layer_print_height") or ""
            ).strip()
            if layer_height == "0.08" and first_layer_height != layer_height:
                mismatches.append(
                    (template_name, layer_height, first_layer_height)
                )

        assert mismatches == []


class TestSlicerTemplateCompatibilityContract:
    """Generated projects must be sliceable by their declared printer."""

    @pytest.mark.parametrize("nozzle_size", ["0.4", "0.2"])
    def test_orca_p2s_process_declares_its_p2s_printer(
        self,
        nozzle_size: str,
    ) -> None:
        profile = get_printer_profile("bambu-p2s")
        template_name = profile.get_template_file(
            "OrcaSlicer",
            nozzle_size=nozzle_size,
        )
        template_path = (
            Path(__file__).resolve().parents[1]
            / "printer_profiles"
            / template_name
        )
        template = json.loads(template_path.read_text(encoding="utf-8"))

        assert template["print_compatible_printers"] == [
            template["printer_settings_id"]
        ]
