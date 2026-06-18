# Material Registry Package v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement issue #241 phase 1: v2 material package metadata, safe import/export compatibility, and local `_sync/index.json` tracking.

**Architecture:** Keep the current saved-material directory layout and existing v1 ZIP manifest for compatibility. Add a root-level `lumina_material_bundle.json` v2 manifest that records stable material/revision identities, file hashes, content hash, display metadata, and source directory. On v2 import, verify hashes before copying and record installed revisions in `materials/_sync/index.json`.

**Identity model:** `material_id` is the cloud lineage identity, `revision_id` is one immutable published version, `content_hash` proves core material content equivalence, and `local_directory` is the local install path. Installed-state matching should prefer `local_directory + content_hash` for exact local-content matches, then fall back to `material_id` for lineage/update/rollback decisions. The full Chinese design note lives in `docs/superpowers/specs/2026-06-08-material-registry-sync-design.md`.

**Tech Stack:** Python stdlib `zipfile`, `hashlib`, `json`, existing `core/single_stage/materials.py`, pytest.

---

### Task 1: Export v2 bundle manifest and exclude local-only files

**Files:**
- Modify: `core/single_stage/materials.py`
- Test: `tests/test_single_stage_unit.py`

- [ ] **Step 1: Write the failing test**

Add a test named `test_export_saved_stage_a_material_archives_writes_v2_bundle_manifest_and_excludes_local_only_files` near the existing export/import tests:

```python
def test_export_saved_stage_a_material_archives_writes_v2_bundle_manifest_and_excludes_local_only_files(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "BrandA" / "pla-basic"
    material_dir.mkdir(parents=True)
    (material_dir / "material.json").write_text(
        json.dumps(
            {
                "brand": "BrandA",
                "material_name": "PLA Basic",
                "material_type": "PLA",
                "color_name": "Blue",
                "stage_a_params_file": "stage_A_parameters.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (material_dir / "stage_A_parameters.json").write_text(
        json.dumps({"parameters": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (material_dir / "usage_stats.json").write_text("{}", encoding="utf-8")
    (material_dir / "_solver_cache").mkdir()
    (material_dir / "_solver_cache" / "cache.npz").write_bytes(b"cache")
    zip_output = tmp_path / "materials_export.zip"

    export_saved_stage_a_material_archives(
        directory_names=["BrandA/pla-basic"],
        materials_dir=str(materials_root),
        output_path=str(zip_output),
    )

    with zipfile.ZipFile(zip_output, "r") as archive:
        members = set(archive.namelist())
        assert "lumina_material_export.json" in members
        assert "lumina_material_bundle.json" in members
        assert "materials/BrandA/pla-basic/material.json" in members
        assert "materials/BrandA/pla-basic/stage_A_parameters.json" in members
        assert "materials/BrandA/pla-basic/usage_stats.json" not in members
        assert "materials/BrandA/pla-basic/_solver_cache/cache.npz" not in members
        manifest = json.loads(
            archive.read("lumina_material_bundle.json").decode("utf-8")
        )
        material_bytes = archive.read("materials/BrandA/pla-basic/material.json")
        stage_a_bytes = archive.read(
            "materials/BrandA/pla-basic/stage_A_parameters.json"
        )

    assert manifest["kind"] == "lumina_material_bundle"
    assert manifest["schema_version"] == "2.0"
    package = manifest["packages"][0]
    assert package["local_directory"] == "BrandA/pla-basic"
    assert package["display"]["brand"] == "BrandA"
    assert package["display"]["material_name"] == "PLA Basic"
    file_hashes = {item["path"]: item["sha256"] for item in package["files"]}
    assert file_hashes["materials/BrandA/pla-basic/material.json"] == (
        hashlib.sha256(material_bytes).hexdigest()
    )
    assert file_hashes["materials/BrandA/pla-basic/stage_A_parameters.json"] == (
        hashlib.sha256(stage_a_bytes).hexdigest()
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest tests/test_single_stage_unit.py::test_export_saved_stage_a_material_archives_writes_v2_bundle_manifest_and_excludes_local_only_files -q
```

Expected: FAIL because `lumina_material_bundle.json` is not written and local-only files are still exported.

- [ ] **Step 3: Implement minimal export support**

In `core/single_stage/materials.py`, add `hashlib` import, v2 constants, helpers to hash file bytes, skip `_solver_cache` and `usage_stats.json`, build deterministic `material_id` / `revision_id`, and write root `lumina_material_bundle.json` alongside the existing v1 manifest.

- [ ] **Step 4: Run export tests**

Run:

```powershell
python -m pytest tests/test_single_stage_unit.py::test_export_saved_stage_a_material_archives_writes_manifest_and_files tests/test_single_stage_unit.py::test_export_saved_stage_a_material_archives_writes_v2_bundle_manifest_and_excludes_local_only_files -q
```

Expected: PASS.

### Task 2: Import v2 bundle and update `_sync/index.json`

**Files:**
- Modify: `core/single_stage/materials.py`
- Test: `tests/test_single_stage_unit.py`

- [ ] **Step 1: Write the failing test**

Add a test named `test_import_saved_stage_a_material_archives_accepts_v2_bundle_and_writes_sync_index`:

```python
def test_import_saved_stage_a_material_archives_accepts_v2_bundle_and_writes_sync_index(
    tmp_path: Path,
) -> None:
    exported_zip = tmp_path / "materials_import_v2.zip"
    material_payload = json.dumps(
        {
            "brand": "BrandA",
            "material_name": "PLA Basic Imported",
            "stage_a_params_file": "stage_A_parameters.json",
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    stage_a_payload = json.dumps(
        {"parameters": {}},
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    material_hash = hashlib.sha256(material_payload).hexdigest()
    stage_a_hash = hashlib.sha256(stage_a_payload).hexdigest()
    content_hash = hashlib.sha256(
        f"material.json:{material_hash}\nstage_A_parameters.json:{stage_a_hash}".encode(
            "utf-8"
        )
    ).hexdigest()
    with zipfile.ZipFile(exported_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("materials/BrandA/pla-basic/material.json", material_payload)
        archive.writestr(
            "materials/BrandA/pla-basic/stage_A_parameters.json",
            stage_a_payload,
        )
        archive.writestr(
            "lumina_material_bundle.json",
            json.dumps(
                {
                    "kind": "lumina_material_bundle",
                    "schema_version": "2.0",
                    "exported_at": "2026-06-08T00:00:00Z",
                    "packages": [
                        {
                            "material_id": "mat_test123",
                            "revision_id": "rev_test123",
                            "content_hash": f"sha256:{content_hash}",
                            "channel": "team",
                            "visibility": "team",
                            "local_directory": "BrandA/pla-basic",
                            "display": {
                                "brand": "BrandA",
                                "material_name": "PLA Basic Imported",
                            },
                            "files": [
                                {
                                    "path": "materials/BrandA/pla-basic/material.json",
                                    "role": "material_archive",
                                    "sha256": material_hash,
                                    "bytes": len(material_payload),
                                    "required": True,
                                },
                                {
                                    "path": "materials/BrandA/pla-basic/stage_A_parameters.json",
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
                indent=2,
            ),
        )

    materials_root = tmp_path / "materials"
    result = import_saved_stage_a_material_archives(
        archive_path=str(exported_zip),
        materials_dir=str(materials_root),
    )

    assert len(result.imported_materials) == 1
    assert result.imported_materials[0]["directory_name"] == "BrandA/pla-basic"
    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    installed = index["installed"]["mat_test123"]
    assert installed["revision_id"] == "rev_test123"
    assert installed["content_hash"] == f"sha256:{content_hash}"
    assert installed["channel"] == "team"
    assert installed["local_directory"] == "BrandA/pla-basic"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest tests/test_single_stage_unit.py::test_import_saved_stage_a_material_archives_accepts_v2_bundle_and_writes_sync_index -q
```

Expected: FAIL because v2 bundle manifests are ignored and `_sync/index.json` is not written.

- [ ] **Step 3: Implement v2 import support**

Load `lumina_material_bundle.json`, validate `kind` and `schema_version`, map package `local_directory` values to staged material directories, verify required file hashes, copy materials using existing collision-safe destination logic, and write `_sync/index.json` entries for v2 packages after successful copy.

- [ ] **Step 4: Run import compatibility tests**

Run:

```powershell
python -m pytest tests/test_single_stage_unit.py::test_import_saved_stage_a_material_archives_copies_materials_and_renames_collisions tests/test_single_stage_unit.py::test_import_saved_stage_a_material_archives_accepts_v2_bundle_and_writes_sync_index -q
```

Expected: PASS.

### Task 3: Reject tampered v2 package files

**Files:**
- Modify: `core/single_stage/materials.py`
- Test: `tests/test_single_stage_unit.py`

- [ ] **Step 1: Write the failing test**

Add a test named `test_import_saved_stage_a_material_archives_rejects_v2_hash_mismatch` that writes `lumina_material_bundle.json` with a deliberately wrong SHA-256 for `material.json`, then asserts `import_saved_stage_a_material_archives(...)` raises `ValueError` and does not create a material directory.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest tests/test_single_stage_unit.py::test_import_saved_stage_a_material_archives_rejects_v2_hash_mismatch -q
```

Expected: FAIL because hash mismatch is not currently checked.

- [ ] **Step 3: Implement hash rejection**

Make v2 import call the file verification helper before any copy occurs. If any declared required file is missing, has a size mismatch, or has a SHA-256 mismatch, raise `ValueError` with the package path.

- [ ] **Step 4: Run focused phase 1 tests**

Run:

```powershell
python -m pytest tests/test_single_stage_unit.py::test_export_saved_stage_a_material_archives_writes_manifest_and_files tests/test_single_stage_unit.py::test_export_saved_stage_a_material_archives_writes_v2_bundle_manifest_and_excludes_local_only_files tests/test_single_stage_unit.py::test_import_saved_stage_a_material_archives_copies_materials_and_renames_collisions tests/test_single_stage_unit.py::test_import_saved_stage_a_material_archives_accepts_v2_bundle_and_writes_sync_index tests/test_single_stage_unit.py::test_import_saved_stage_a_material_archives_rejects_v2_hash_mismatch -q
```

Expected: PASS.

### Task 4: Final verification

**Files:**
- Verify: `core/single_stage/materials.py`
- Verify: `tests/test_single_stage_unit.py`

- [ ] **Step 1: Run broader single-stage tests**

Run:

```powershell
python -m pytest tests/test_single_stage_unit.py -q
```

Expected: PASS.

- [ ] **Step 2: Check UTF-8/mojibake and diff**

Run:

```powershell
rg -n "锟|鎷|鍙|涓" core/single_stage/materials.py tests/test_single_stage_unit.py docs/superpowers/plans/2026-06-08-material-registry-package-v2.md
git diff --check
git status --short
```

Expected: no mojibake matches, no whitespace errors, only intended files modified.
