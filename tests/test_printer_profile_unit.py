"""Unit tests for printer hardware registry and native export settings.
打印机硬件注册表与原生导出配置单元测试。

Covers:
  - Task 7.1: Registry queries, default fallback, export settings loading
  - Task 7.2: 3MF export uses the correct native printer_model
  - Task 0.2 nozzle support: profile metadata and nozzle-size-aware resolution
"""

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
from utils.bambu_3mf_writer import load_export_project_settings

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
)


# ====================================================================
# Registry queries, default selection, and native export settings
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

    def test_normalize_qidi_studio_software_id(self) -> None:
        assert normalize_slicer_software_id("qidi studio") == "QIDIStudio"


class TestProfileRequiredFields:
    """Every profile has all required fields."""

    @pytest.mark.parametrize("printer_id", list(PRINTER_PROFILES.keys()))
    def test_profile_has_all_required_fields(self, printer_id: str) -> None:
        profile = PRINTER_PROFILES[printer_id]
        for field in REQUIRED_FIELDS:
            assert hasattr(profile, field), f"{printer_id} missing field: {field}"
            assert getattr(profile, field) is not None, f"{printer_id}.{field} is None"


class TestLoadExportProjectSettings:
    """load_export_project_settings() returns non-empty dicts."""

    def test_h2d_template_non_empty(self) -> None:
        template = load_export_project_settings("bambu-h2d")
        assert isinstance(template, dict)
        assert len(template) > 0

    def test_a1_mini_template_non_empty(self) -> None:
        template = load_export_project_settings("bambu-a1-mini")
        assert isinstance(template, dict)
        assert len(template) > 0

    def test_anycubic_template_uses_anycubic_slicer_mapping(self) -> None:
        template = load_export_project_settings("anycubic-kobra-s1", slicer="AnycubicSlicerNext")
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
        template = load_export_project_settings(
            printer_id,
            slicer="FlashStudio",
            nozzle_size=nozzle_size,
        )

        assert template["printer_model"] == model
        assert template["printer_settings_id"] == source_profile_name
        assert template["nozzle_diameter"] == [nozzle_size] * physical_tools
        assert template["version"] == "02.06.00.51"
        assert template["filament_vendor"] == ["Flashforge"]
        assert "Flashforge" in str(template["default_filament_profile"])

    @pytest.mark.parametrize(
        ("printer_id", "model", "nozzle_size"),
        [
            ("qidi-q2", "Q2", "0.2"),
            ("qidi-q2", "Q2", "0.4"),
            ("qidi-q2c", "Q2C", "0.2"),
            ("qidi-q2c", "Q2C", "0.4"),
            ("qidi-x-max-4", "X-Max 4", "0.2"),
            ("qidi-x-max-4", "X-Max 4", "0.4"),
            ("qidi-x-plus-5", "X-Plus 5", "0.4"),
        ],
    )
    def test_qidi_sources_keep_native_machine_and_default_process_identity(
        self,
        printer_id: str,
        model: str,
        nozzle_size: str,
    ) -> None:
        template = load_export_project_settings(
            printer_id,
            slicer="QIDIStudio",
            nozzle_size=nozzle_size,
        )

        assert template["printer_model"] == model
        assert template["printer_settings_id"] == f"{model} {nozzle_size} nozzle"
        assert template["printer_variant"] == nozzle_size
        assert template["nozzle_diameter"] == [nozzle_size]
        assert template["version"] == "02.07.02.60"
        assert template["layer_height"] == ("0.1" if nozzle_size == "0.2" else "0.2")
        assert template["line_width"] == ("0.22" if nozzle_size == "0.2" else "0.42")

    def test_load_export_project_settings_reads_0_2_variant(self) -> None:
        template = load_export_project_settings("bambu-p1s", nozzle_size=0.2)
        assert template["nozzle_diameter"] == ["0.2"]
        assert "0.2 nozzle" in template["default_print_profile"]

    def test_h2d_0_2_template_uses_official_0_2_process_preset_ids(self) -> None:
        template = load_export_project_settings("bambu-h2d", nozzle_size="0.2")
        assert template["print_settings_id"] == "0.10mm Standard @BBL H2D 0.2 nozzle"
        assert template["default_print_profile"] == template["print_settings_id"]
        assert template["top_surface_line_width"] == "0.22"
        assert template["support_line_width"] == "0.22"

    @pytest.mark.parametrize(
        ("printer_id", "process_id"),
        [
            ("bambu-lab-a2l", "0.10mm Standard @BBL A2L 0.2 nozzle"),
            ("bambu-lab-x2d", "0.10mm Standard @BBL X2D 0.2 nozzle"),
        ],
    )
    def test_new_bambu_0_2_templates_keep_official_process_identity(
        self,
        printer_id: str,
        process_id: str,
    ) -> None:
        template = load_export_project_settings(printer_id, nozzle_size="0.2")

        assert template["print_settings_id"] == process_id
        assert template["default_print_profile"] == process_id
        assert template["print_compatible_printers"] == [template["printer_settings_id"]]


# ====================================================================
# Task 7.2 — 3MF export uses correct template
# ====================================================================


class TestTemplatePrinterModelKey:
    """Templates contain correct printer_model key."""

    def test_h2d_template_has_printer_model(self) -> None:
        template = load_export_project_settings("bambu-h2d")
        assert "printer_model" in template

    def test_p1s_template_has_correct_printer_model(self) -> None:
        template = load_export_project_settings("bambu-p1s")
        assert "printer_model" in template
        # The template's printer_model should identify the P1S
        assert "P1S" in template["printer_model"]

    def test_invalid_id_falls_back_to_valid_template(self) -> None:
        template = load_export_project_settings("invalid-id")
        assert isinstance(template, dict)
        assert len(template) > 0


@pytest.mark.parametrize(
    ("slicer", "nozzle_size"),
    (
        ("BambuStudio", "0.4"),
        ("BambuStudio", "0.2"),
        ("OrcaSlicer", "0.4"),
        ("OrcaSlicer", "0.2"),
    ),
)
def test_a1_mini_waiting_temperature_compensation_is_marked_as_flush(
    slicer: str,
    nozzle_size: str,
) -> None:
    """Keep the purge-chute extrusion out of printable-bed validation.

    保证废料口补偿挤出被标记为冲刷路径，不参与热床边界校验。
    """

    template = load_export_project_settings(
        "bambu-a1-mini",
        slicer=slicer,
        nozzle_size=nozzle_size,
    )
    gcode = str(template["change_filament_gcode"])
    marker = "Compensate for filament spillage during waiting temperature"
    marker_offset = gcode.index(marker)
    flush_start = gcode.rfind("; FLUSH_START", 0, marker_offset)
    flush_end = gcode.find("; FLUSH_END", marker_offset)

    assert flush_start >= 0
    assert flush_end > marker_offset


def test_orca_native_tower_defaults_reach_placement() -> None:
    """Placement must include the ribs and spacing used by the real slicer."""
    from utils.fatcat_metadata import read_project_layout

    template = load_export_project_settings("bambu-p1s", slicer="OrcaSlicer")
    layout = read_project_layout(template, slicer_id="OrcaSlicer")

    assert layout["uses_rib_wall"] is True
    assert layout["tower_rib_width"] == pytest.approx(8.0)
    assert layout["tower_infill_spacing_ratio"] == pytest.approx(1.5)
