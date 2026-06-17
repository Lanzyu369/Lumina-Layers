"""Material seed bootstrap tests."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from api.material_seed import install_material_seed_if_needed


def _write_seed_archive(zip_path: Path) -> str:
    material_payload = json.dumps(
        {
            "brand": "SeedBrand",
            "material_name": "Seed PLA",
            "stage_a_params_file": "stage_A_parameters.json",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    stage_a_payload = json.dumps(
        {"parameters": {"channels": [{"color_name": "Seed PLA"}]}},
        ensure_ascii=False,
    ).encode("utf-8")
    material_hash = hashlib.sha256(material_payload).hexdigest()
    stage_a_hash = hashlib.sha256(stage_a_payload).hexdigest()
    content_hash = hashlib.sha256(
        f"material.json:{material_hash}\nstage_A_parameters.json:{stage_a_hash}".encode(
            "utf-8"
        )
    ).hexdigest()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("materials/SeedBrand/seed-pla/material.json", material_payload)
        archive.writestr(
            "materials/SeedBrand/seed-pla/stage_A_parameters.json",
            stage_a_payload,
        )
        archive.writestr(
            "lumina_material_bundle.json",
            json.dumps(
                {
                    "kind": "lumina_material_bundle",
                    "schema_version": "2.0",
                    "packages": [
                        {
                            "material_id": "mat_seed",
                            "revision_id": "rev_seed",
                            "content_hash": f"sha256:{content_hash}",
                            "channel": "official",
                            "visibility": "official",
                            "local_directory": "SeedBrand/seed-pla",
                            "display": {
                                "brand": "SeedBrand",
                                "material_name": "Seed PLA",
                            },
                            "files": [
                                {
                                    "path": "materials/SeedBrand/seed-pla/material.json",
                                    "role": "material_archive",
                                    "sha256": material_hash,
                                    "bytes": len(material_payload),
                                    "required": True,
                                },
                                {
                                    "path": "materials/SeedBrand/seed-pla/stage_A_parameters.json",
                                    "role": "stage_a_parameters",
                                    "sha256": stage_a_hash,
                                    "bytes": len(stage_a_payload),
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
    return hashlib.sha256(zip_path.read_bytes()).hexdigest()


def test_material_seed_installs_when_runtime_materials_are_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "lumina-materials-seed.zip"
    seed_sha256 = _write_seed_archive(seed_path)
    materials_root = tmp_path / "materials"
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(seed_path))
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_SHA256", seed_sha256)

    result = install_material_seed_if_needed(materials_dir=str(materials_root))

    assert result is not None
    assert result["installed_count"] == 1
    assert (materials_root / "SeedBrand" / "seed-pla" / "material.json").is_file()
    assert (materials_root / "_sync" / "index.json").is_file()


def test_material_seed_does_not_overwrite_existing_runtime_materials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "lumina-materials-seed.zip"
    _write_seed_archive(seed_path)
    materials_root = tmp_path / "materials"
    existing_material = materials_root / "UserBrand" / "local-pla" / "material.json"
    existing_material.parent.mkdir(parents=True)
    existing_material.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(seed_path))

    result = install_material_seed_if_needed(materials_dir=str(materials_root))

    assert result is None
    assert existing_material.read_text(encoding="utf-8") == "{}"
    assert not (materials_root / "SeedBrand" / "seed-pla").exists()


def test_material_seed_rejects_sha256_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "lumina-materials-seed.zip"
    _write_seed_archive(seed_path)
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(seed_path))
    monkeypatch.setenv("LUMINA_MATERIALS_SEED_SHA256", "0" * 64)

    with pytest.raises(ValueError, match="sha256 mismatch"):
        install_material_seed_if_needed(materials_dir=str(tmp_path / "materials"))
