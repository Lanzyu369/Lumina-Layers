"""Derive 0.2 nozzle printer profile templates from the checked-in 0.4 set.

This script is deterministic:
- It reads the reference sample `元数据分析/0.2 P1S.3mf`
- It extracts the `Metadata/project_settings.config` payload
- It compares that sample against `printer_profiles/bambu_p1s.json`
- It applies the resulting nozzle-specific rule set to every base template JSON

The output is written as sibling `*_0_2.json` files under `printer_profiles/`.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

LINE_WIDTH_KEYS = (
    "initial_layer_line_width",
    "inner_wall_line_width",
    "internal_solid_infill_line_width",
    "line_width",
    "outer_wall_line_width",
    "skeleton_infill_line_width",
    "skin_infill_line_width",
    "sparse_infill_line_width",
    "support_line_width",
    "top_surface_line_width",
)

STRING_REPLACEMENTS = (
    (re.compile(r"\b0\.4 nozzle\b"), "0.2 nozzle"),
    (re.compile(r"\(0\.4 nozzle\)"), "(0.2 nozzle)"),
    (re.compile(r"\bP1S-0\.4\b"), "P1S-0.2"),
)

OFFICIAL_BAMBU_0_2_PROCESS_PRESETS = {
    "bambu_a2l": "0.08mm High Quality @BBL A2L 0.2 nozzle",
    "bambu_h2d": "0.08mm Extra Fine @BBL H2D 0.2 nozzle",
    "bambu_h2c": "0.08mm High Quality @BBL H2C 0.2 nozzle",
    "bambu_h2s": "0.08mm High Quality @BBL H2S 0.2 nozzle",
    "bambu_h2d_pro": "0.08mm Extra Fine @BBL H2DP 0.2 nozzle",
    "bambu_x2d": "0.08mm High Quality @BBL X2D 0.2 nozzle",
}

OFFICIAL_BAMBU_0_2_DEFAULT_PROFILES = {
    "bambu_h2d_pro": "0.10mm Standard @BBL H2DP 0.2 nozzle",
}

OFFICIAL_BAMBU_0_2_FILAMENT_PROFILES = {
    "bambu_h2d_pro": "Bambu PLA Basic @BBL H2DP 0.2 nozzle",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_reference_sample(sample_path: Path) -> dict[str, Any]:
    """Load the reference project_settings payload from a sample 3MF archive."""
    with zipfile.ZipFile(sample_path) as zf:
        raw = zf.read("Metadata/project_settings.config").decode("utf-8")
    return json.loads(raw)


def build_sample_driven_rules(sample_settings: dict[str, Any], base_settings: dict[str, Any]) -> dict[str, Any]:
    """Build the curated 0.2-nozzle rule set from the P1S reference pair."""
    scalar_overrides: dict[str, Any] = {}
    for key in LINE_WIDTH_KEYS + ("wall_generator",):
        if key in sample_settings and sample_settings.get(key) != base_settings.get(key):
            scalar_overrides[key] = sample_settings[key]

    target_nozzle = str(sample_settings["nozzle_diameter"][0])
    return {
        "target_nozzle": target_nozzle,
        "target_default_print_profile": str(sample_settings["default_print_profile"]),
        "scalar_overrides": scalar_overrides,
    }


def _replace_strings(value: Any) -> Any:
    """Recursively rewrite nozzle-labelled strings without touching unrelated numbers."""
    if isinstance(value, str):
        updated = value
        for pattern, replacement in STRING_REPLACEMENTS:
            updated = pattern.sub(replacement, updated)
        return updated
    if isinstance(value, list):
        return [_replace_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_strings(item) for key, item in value.items()}
    return value


def _ensure_nozzle_suffix(current: str, target_nozzle: str) -> str:
    """Ensure a human-readable profile label carries the target nozzle suffix."""
    rewritten = _replace_strings(current.strip())
    if f"{target_nozzle} nozzle" in rewritten:
        return rewritten
    return f"{rewritten} {target_nozzle} nozzle".strip()


def _rewrite_default_print_profile(current: str, target_profile: str, target_nozzle: str) -> str:
    """Replace the profile-height prefix while preserving the printer label suffix."""
    if "@" not in current or "@" not in target_profile:
        return _ensure_nozzle_suffix(current, target_nozzle)
    _, current_suffix = current.split("@", 1)
    target_head, _ = target_profile.split("@", 1)
    rewritten_suffix = _ensure_nozzle_suffix(current_suffix, target_nozzle)
    return f"{target_head.strip()} @{rewritten_suffix.strip()}"


def _rewrite_nozzle_diameter(value: Any, target_nozzle: str) -> Any:
    """Preserve shape while converting nozzle diameter values to the target nozzle."""
    if isinstance(value, list):
        return [target_nozzle for _ in value]
    if isinstance(value, str):
        return target_nozzle
    return value


def derive_template(
    base_template: dict[str, Any],
    rules: dict[str, Any],
    *,
    base_stem: str,
    sample_settings: dict[str, Any] | None = None,
    use_sample_as_base: bool = False,
) -> dict[str, Any]:
    """Derive one 0.2 template from its 0.4 base template."""
    target_nozzle = str(rules["target_nozzle"])
    target_default_print_profile = str(rules["target_default_print_profile"])
    if use_sample_as_base and sample_settings is not None:
        derived = copy.deepcopy(sample_settings)
    else:
        derived = _replace_strings(copy.deepcopy(base_template))

    if "printer_variant" in derived:
        derived["printer_variant"] = target_nozzle

    if "nozzle_diameter" in derived:
        derived["nozzle_diameter"] = _rewrite_nozzle_diameter(derived["nozzle_diameter"], target_nozzle)

    for key, value in rules["scalar_overrides"].items():
        if key in derived:
            derived[key] = value

    if isinstance(derived.get("default_print_profile"), str):
        derived["default_print_profile"] = _rewrite_default_print_profile(
            derived["default_print_profile"],
            target_default_print_profile,
            target_nozzle,
        )

    if isinstance(derived.get("default_filament_profile"), list):
        derived["default_filament_profile"] = [
            _ensure_nozzle_suffix(item, target_nozzle) if isinstance(item, str) and "@" in item else item
            for item in derived["default_filament_profile"]
        ]

    if base_stem in OFFICIAL_BAMBU_0_2_DEFAULT_PROFILES:
        derived["default_print_profile"] = OFFICIAL_BAMBU_0_2_DEFAULT_PROFILES[base_stem]

    official_process_preset = OFFICIAL_BAMBU_0_2_PROCESS_PRESETS.get(base_stem)
    if official_process_preset:
        derived["print_settings_id"] = official_process_preset
        inherits_group = derived.get("inherits_group")
        if isinstance(inherits_group, list) and inherits_group:
            inherits_group[0] = official_process_preset
        else:
            derived["inherits_group"] = [official_process_preset, "", "", "", "", ""]

    official_filament_profile = OFFICIAL_BAMBU_0_2_FILAMENT_PROFILES.get(base_stem)
    if official_filament_profile:
        if isinstance(derived.get("default_filament_profile"), list) and derived["default_filament_profile"]:
            derived["default_filament_profile"][0] = official_filament_profile
        if isinstance(derived.get("filament_settings_id"), list):
            derived["filament_settings_id"] = [official_filament_profile for _ in derived["filament_settings_id"]]
    elif base_stem.startswith("bambu_") and isinstance(derived.get("filament_settings_id"), list):
        derived["filament_settings_id"] = [
            _ensure_nozzle_suffix(item, target_nozzle) if isinstance(item, str) and "@BBL" in item else item
            for item in derived["filament_settings_id"]
        ]

    return derived


def iter_base_templates(printer_profiles_dir: Path) -> list[Path]:
    """Return all checked-in base printer profile templates."""
    return sorted(
        path
        for path in printer_profiles_dir.glob("*.json")
        if not path.name.endswith("_0_2.json")
    )


def derive_all_templates(
    printer_profiles_dir: Path,
    sample_path: Path,
    *,
    write: bool,
) -> list[Path]:
    """Derive every `*_0_2.json` sibling from the current base template set."""
    sample_settings = load_reference_sample(sample_path)
    base_reference = json.loads((printer_profiles_dir / "bambu_p1s.json").read_text(encoding="utf-8"))
    rules = build_sample_driven_rules(sample_settings, base_reference)

    written_paths: list[Path] = []
    for base_path in iter_base_templates(printer_profiles_dir):
        base_template = json.loads(base_path.read_text(encoding="utf-8"))
        derived = derive_template(
            base_template,
            rules,
            base_stem=base_path.stem,
            sample_settings=sample_settings,
            use_sample_as_base=(base_path.stem == "bambu_p1s"),
        )
        output_path = base_path.with_name(f"{base_path.stem}_0_2.json")
        if write:
            output_path.write_text(
                json.dumps(derived, ensure_ascii=False, indent=4) + "\n",
                encoding="utf-8",
            )
        written_paths.append(output_path)

    return written_paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    root = _repo_root()
    return argparse.ArgumentParser(description=__doc__).parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _ = parse_args(argv or sys.argv[1:])
    root = _repo_root()
    printer_profiles_dir = root / "printer_profiles"
    sample_path = root / "元数据分析" / "0.2 P1S.3mf"

    written_paths = derive_all_templates(
        printer_profiles_dir,
        sample_path,
        write=True,
    )
    print(f"Derived {len(written_paths)} nozzle-0.2 templates from {sample_path.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
