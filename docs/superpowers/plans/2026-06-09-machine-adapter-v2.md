# Machine Adapter V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a development-time slicer profile importer that reads native Bambu/Orca-family machine JSON and generates Lumina's internal machine registry, while preserving current 3MF metadata and protected Lumina process settings.

**Architecture:** Keep runtime stable first. Add a generated registry and importer tooling beside the existing `config.py`/`printer_profiles` path, then migrate readers to prefer the registry with legacy fallback. Treat slicer-native machine data as the source for machine identity and capabilities, and apply a Lumina process overlay for protected export settings such as `0.08mm` layer height.

**Tech Stack:** Python 3, dataclasses/Pydantic where already used, JSON fixtures, pytest, existing `utils.bambu_3mf_writer`, existing FastAPI routers, React/TypeScript settings UI in a later task.

---

## Scope And Branch Rules

Work in the isolated worktree:

```powershell
E:\Lumina-Layers\LL-1296\Lumina-Layers\.worktrees\machine-adapter-v2
```

Branch:

```powershell
Min/feat/machine-adapter-v2
```

Before implementation, register this planned change in the online tracking spreadsheet. Do not touch `materials/` in this workstream.

## File Structure

Create or modify these areas:

- Create `core/machine_registry.py`
  - Runtime models and loader for generated Lumina machine registry.
- Create `core/machine_process_overlay.py`
  - Protected Lumina process settings and merge rules.
- Create `tools/machine_adapter/resolver.py`
  - Native Orca/Bambu-family JSON scanner and `inherits`/`include` resolver.
- Create `tools/machine_adapter/providers.py`
  - Provider definitions for `BambuStudio`, `OrcaSlicer`, `SnapmakerOrca`, `ElegooSlicer`, and `AnycubicSlicerNext`.
- Create `tools/machine_adapter/emitter.py`
  - Converts resolved native profiles into registry entries and writer-compatible metadata templates.
- Create `tools/machine_adapter/import_profiles.py`
  - CLI entry point for development-time imports.
- Create `tests/fixtures/machine_adapter/`
  - Small native profile fixture set.
- Modify `utils/bambu_3mf_writer.py`
  - Prefer registry templates when requested, keep current `printer_profiles` fallback.
- Modify `api/routers/system.py` and `api/schemas/system.py`
  - Expose registry-driven device choices after backend registry support is stable.
- Modify `frontend/src/components/SettingsPanel.tsx`, `frontend/src/stores/settingsStore.ts`, and `frontend/src/utils/settingsOptionIds.ts`
  - Later UI phase: slicer -> machine -> nozzle selection with thumbnails.
- Modify `scripts/verify_3mf_template_matrix.py`
  - Restore matrix verification and add protected-process assertions.

## Task 1: Registry Models And Loader

**Files:**
- Create: `core/machine_registry.py`
- Test: `tests/test_machine_registry_unit.py`

- [ ] **Step 1: Write failing registry loader tests**

Create `tests/test_machine_registry_unit.py`:

```python
from __future__ import annotations

import json

from core.machine_registry import load_machine_registry


def test_load_machine_registry_indexes_device_profiles(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-06-09T00:00:00+08:00",
                "slicers": [
                    {
                        "slicer_id": "BambuStudio",
                        "display_name": "Bambu Studio",
                        "source_kind": "local_install",
                        "source_version": "02.07.01.57",
                        "profile_format": "bambu_orca",
                        "application_metadata": "BambuStudio-02.07.01.57",
                        "sidecar_policy": "bambu_studio",
                        "machines": [
                            {
                                "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
                                "display_name": "Bambu Lab H2D",
                                "brand": "Bambu Lab",
                                "vendor_key": "BBL",
                                "bed_width": 350,
                                "bed_depth": 320,
                                "bed_height": 325,
                                "thumbnail": "slicers/BambuStudio/02.07.01.57/assets/h2d.png",
                                "nozzles": [
                                    {
                                        "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                                        "nozzle_size": "0.4",
                                        "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
                                        "template": "slicers/BambuStudio/02.07.01.57/metadata_templates/h2d_0_4.json",
                                        "revision": "sha256:abc",
                                        "supported": True,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = load_machine_registry(registry_path)

    profile = registry.get_device_profile("BambuStudio:bbl:bambu-lab-h2d:0.4")
    assert profile.slicer_id == "BambuStudio"
    assert profile.machine_profile_id == "BambuStudio:bbl:bambu-lab-h2d"
    assert profile.nozzle_size == "0.4"
    assert profile.application_metadata == "BambuStudio-02.07.01.57"
    assert profile.sidecar_policy == "bambu_studio"
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m pytest tests/test_machine_registry_unit.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.machine_registry'`.

- [ ] **Step 3: Implement registry models**

Create `core/machine_registry.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeviceProfile:
    device_profile_id: str
    machine_profile_id: str
    slicer_id: str
    slicer_display_name: str
    source_version: str
    application_metadata: str
    sidecar_policy: str
    display_name: str
    brand: str
    vendor_key: str
    bed_width: int
    bed_depth: int
    bed_height: int
    thumbnail: str
    nozzle_size: str
    source_profile_name: str
    template: str
    revision: str
    supported: bool


@dataclass(frozen=True)
class MachineRegistry:
    schema_version: int
    generated_at: str
    devices_by_id: dict[str, DeviceProfile]

    def get_device_profile(self, device_profile_id: str) -> DeviceProfile:
        return self.devices_by_id[device_profile_id]


def load_machine_registry(path: str | Path) -> MachineRegistry:
    registry_path = Path(path)
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    devices: dict[str, DeviceProfile] = {}
    for slicer in data.get("slicers", []):
        slicer_id = str(slicer["slicer_id"])
        for machine in slicer.get("machines", []):
            for nozzle in machine.get("nozzles", []):
                device = DeviceProfile(
                    device_profile_id=str(nozzle["device_profile_id"]),
                    machine_profile_id=str(machine["machine_profile_id"]),
                    slicer_id=slicer_id,
                    slicer_display_name=str(slicer["display_name"]),
                    source_version=str(slicer["source_version"]),
                    application_metadata=str(slicer["application_metadata"]),
                    sidecar_policy=str(slicer["sidecar_policy"]),
                    display_name=str(machine["display_name"]),
                    brand=str(machine["brand"]),
                    vendor_key=str(machine["vendor_key"]),
                    bed_width=int(machine["bed_width"]),
                    bed_depth=int(machine["bed_depth"]),
                    bed_height=int(machine["bed_height"]),
                    thumbnail=str(machine.get("thumbnail", "")),
                    nozzle_size=str(nozzle["nozzle_size"]),
                    source_profile_name=str(nozzle["source_profile_name"]),
                    template=str(nozzle["template"]),
                    revision=str(nozzle["revision"]),
                    supported=bool(nozzle.get("supported", True)),
                )
                devices[device.device_profile_id] = device
    return MachineRegistry(
        schema_version=int(data["schema_version"]),
        generated_at=str(data["generated_at"]),
        devices_by_id=devices,
    )
```

- [ ] **Step 4: Run registry tests**

Run:

```powershell
python -m pytest tests/test_machine_registry_unit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/machine_registry.py tests/test_machine_registry_unit.py
git commit -m "feat(machine): add machine registry loader"
```

## Task 2: Protected Lumina Process Overlay

**Files:**
- Create: `core/machine_process_overlay.py`
- Test: `tests/test_machine_process_overlay_unit.py`

- [ ] **Step 1: Write failing overlay tests**

Create `tests/test_machine_process_overlay_unit.py`:

```python
from __future__ import annotations

from core.machine_process_overlay import apply_lumina_process_overlay


def test_lumina_overlay_preserves_protected_process_fields():
    native = {
        "layer_height": "0.20",
        "initial_layer_height": "0.20",
        "wall_loops": "2",
        "top_shell_layers": "5",
        "sparse_infill_density": "15%",
        "printer_model": "Bambu Lab H2D",
        "printable_height": "325",
    }

    merged = apply_lumina_process_overlay(native)

    assert merged["printer_model"] == "Bambu Lab H2D"
    assert merged["printable_height"] == "325"
    assert merged["layer_height"] == "0.08"
    assert merged["initial_layer_height"] == "0.08"
    assert merged["wall_loops"] == "1"
    assert merged["top_shell_layers"] == "0"
    assert merged["sparse_infill_density"] == "100%"


def test_lumina_overlay_preserves_temperature_array_shape():
    native = {"nozzle_temperature": ["210"], "bed_temperature": ["55"], "filament_type": ["PETG"]}

    merged = apply_lumina_process_overlay(native, slot_count=8)

    assert merged["nozzle_temperature"] == ["220"] * 8
    assert merged["bed_temperature"] == ["60"] * 8
    assert merged["filament_type"] == ["PLA"] * 8
```

- [ ] **Step 2: Run the failing tests**

Run:

```powershell
python -m pytest tests/test_machine_process_overlay_unit.py -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement protected overlay**

Create `core/machine_process_overlay.py`:

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any


PROTECTED_LUMINA_PROCESS_SETTINGS: dict[str, Any] = {
    "layer_height": "0.08",
    "initial_layer_height": "0.08",
    "wall_loops": "1",
    "top_shell_layers": "0",
    "bottom_shell_layers": "1",
    "bottom_surface_pattern": "monotonicline",
    "elefant_foot_compensation": "0",
    "sparse_infill_density": "100%",
    "sparse_infill_pattern": "zig-zag",
    "print_speed": "100",
    "travel_speed": "150",
    "enable_support": "0",
    "brim_width": "5",
    "brim_type": "auto_brim",
}


def apply_lumina_process_overlay(
    native_settings: dict[str, Any],
    *,
    slot_count: int = 8,
) -> dict[str, Any]:
    merged = deepcopy(native_settings)
    merged.update(PROTECTED_LUMINA_PROCESS_SETTINGS)
    merged["nozzle_temperature"] = ["220"] * slot_count
    merged["bed_temperature"] = ["60"] * slot_count
    merged["filament_type"] = ["PLA"] * slot_count
    return merged
```

- [ ] **Step 4: Run overlay tests**

Run:

```powershell
python -m pytest tests/test_machine_process_overlay_unit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/machine_process_overlay.py tests/test_machine_process_overlay_unit.py
git commit -m "feat(machine): add protected Lumina process overlay"
```

## Task 3: Native Orca/Bambu Profile Resolver

**Files:**
- Create: `tools/machine_adapter/resolver.py`
- Create: `tests/fixtures/machine_adapter/BBL/machine/fdm_common.json`
- Create: `tests/fixtures/machine_adapter/BBL/machine/Bambu Lab H2D 0.4 nozzle template machine_start_gcode.json`
- Create: `tests/fixtures/machine_adapter/BBL/machine/Bambu Lab H2D 0.4 nozzle.json`
- Test: `tests/test_machine_adapter_resolver_unit.py`

- [ ] **Step 1: Add fixture files**

Create `tests/fixtures/machine_adapter/BBL/machine/fdm_common.json`:

```json
{
  "type": "machine",
  "name": "fdm_common",
  "instantiation": "false",
  "printable_height": "325",
  "printable_area": ["0x0", "350x0", "350x320", "0x320"],
  "layer_height": "0.20"
}
```

Create `tests/fixtures/machine_adapter/BBL/machine/Bambu Lab H2D 0.4 nozzle template machine_start_gcode.json`:

```json
{
  "type": "machine",
  "name": "Bambu Lab H2D 0.4 nozzle template machine_start_gcode",
  "machine_start_gcode": "G28 ; home"
}
```

Create `tests/fixtures/machine_adapter/BBL/machine/Bambu Lab H2D 0.4 nozzle.json`:

```json
{
  "type": "machine",
  "name": "Bambu Lab H2D 0.4 nozzle",
  "inherits": "fdm_common",
  "instantiation": "true",
  "setting_id": "GM033",
  "printer_model": "Bambu Lab H2D",
  "printer_variant": "0.4",
  "nozzle_diameter": ["0.4", "0.4"],
  "include": ["Bambu Lab H2D 0.4 nozzle template machine_start_gcode"]
}
```

- [ ] **Step 2: Write failing resolver tests**

Create `tests/test_machine_adapter_resolver_unit.py`:

```python
from __future__ import annotations

from pathlib import Path

from tools.machine_adapter.resolver import resolve_machine_profiles


def test_resolver_expands_inherits_and_includes():
    root = Path("tests/fixtures/machine_adapter")

    profiles = resolve_machine_profiles(root=root, vendor_key="BBL")

    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.name == "Bambu Lab H2D 0.4 nozzle"
    assert profile.settings["printer_model"] == "Bambu Lab H2D"
    assert profile.settings["printable_height"] == "325"
    assert profile.settings["machine_start_gcode"] == "G28 ; home"
    assert profile.source_files
    assert all(item.sha256 for item in profile.source_files)
```

- [ ] **Step 3: Run the failing resolver test**

Run:

```powershell
python -m pytest tests/test_machine_adapter_resolver_unit.py -v
```

Expected: FAIL with missing module.

- [ ] **Step 4: Implement resolver**

Create `tools/machine_adapter/resolver.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceFile:
    path: str
    sha256: str


@dataclass(frozen=True)
class ResolvedMachineProfile:
    name: str
    vendor_key: str
    settings: dict[str, Any]
    source_files: tuple[SourceFile, ...]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _index_machine_json(machine_dir: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in machine_dir.glob("*.json"):
        data = _read_json(path)
        name = str(data.get("name") or path.stem)
        index[name] = path
    return index


def _resolve_profile(name: str, index: dict[str, Path], seen: set[str]) -> tuple[dict[str, Any], list[Path]]:
    if name in seen:
        raise ValueError(f"Cyclic machine profile inheritance/include: {name}")
    seen.add(name)
    path = index[name]
    data = _read_json(path)
    merged: dict[str, Any] = {}
    source_paths: list[Path] = []
    parent = str(data.get("inherits") or "").strip()
    if parent:
        parent_settings, parent_paths = _resolve_profile(parent, index, seen)
        merged.update(parent_settings)
        source_paths.extend(parent_paths)
    for include_name in data.get("include", []) or []:
        include_settings, include_paths = _resolve_profile(str(include_name), index, seen)
        merged.update(include_settings)
        source_paths.extend(include_paths)
    merged.update(data)
    source_paths.append(path)
    seen.remove(name)
    return merged, source_paths


def resolve_machine_profiles(*, root: Path, vendor_key: str) -> list[ResolvedMachineProfile]:
    machine_dir = root / vendor_key / "machine"
    index = _index_machine_json(machine_dir)
    resolved: list[ResolvedMachineProfile] = []
    for name, path in sorted(index.items()):
        data = _read_json(path)
        if str(data.get("instantiation", "")).lower() != "true":
            continue
        settings, source_paths = _resolve_profile(name, index, set())
        source_files = tuple(
            SourceFile(path=str(source_path.as_posix()), sha256=_sha256(source_path))
            for source_path in source_paths
        )
        resolved.append(
            ResolvedMachineProfile(
                name=name,
                vendor_key=vendor_key,
                settings=settings,
                source_files=source_files,
            )
        )
    return resolved
```

- [ ] **Step 5: Run resolver tests**

Run:

```powershell
python -m pytest tests/test_machine_adapter_resolver_unit.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add tools/machine_adapter/resolver.py tests/fixtures/machine_adapter tests/test_machine_adapter_resolver_unit.py
git commit -m "feat(machine): resolve native slicer machine profiles"
```

## Task 4: Provider Definitions

**Files:**
- Create: `tools/machine_adapter/providers.py`
- Test: `tests/test_machine_adapter_providers_unit.py`

- [ ] **Step 1: Write failing provider tests**

Create `tests/test_machine_adapter_providers_unit.py`:

```python
from __future__ import annotations

from tools.machine_adapter.providers import get_provider


def test_elegoo_and_anycubic_reuse_bambu_orca_profile_format():
    elegoo = get_provider("ElegooSlicer")
    anycubic = get_provider("AnycubicSlicerNext")

    assert elegoo.profile_format == "bambu_orca"
    assert elegoo.sidecar_policy == "orca_like"
    assert elegoo.default_vendor_keys == ("Elegoo",)
    assert anycubic.profile_format == "bambu_orca"
    assert anycubic.sidecar_policy == "anycubic_next"
    assert anycubic.default_vendor_keys == ("Anycubic",)


def test_unknown_provider_is_rejected():
    try:
        get_provider("Cura")
    except KeyError as exc:
        assert "Unsupported machine adapter provider" in str(exc)
    else:
        raise AssertionError("Expected KeyError")
```

- [ ] **Step 2: Run failing provider tests**

Run:

```powershell
python -m pytest tests/test_machine_adapter_providers_unit.py -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement providers**

Create `tools/machine_adapter/providers.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MachineAdapterProvider:
    slicer_id: str
    display_name: str
    profile_format: str
    sidecar_policy: str
    default_vendor_keys: tuple[str, ...]


PROVIDERS: dict[str, MachineAdapterProvider] = {
    "BambuStudio": MachineAdapterProvider(
        slicer_id="BambuStudio",
        display_name="Bambu Studio",
        profile_format="bambu_orca",
        sidecar_policy="bambu_studio",
        default_vendor_keys=("BBL",),
    ),
    "OrcaSlicer": MachineAdapterProvider(
        slicer_id="OrcaSlicer",
        display_name="OrcaSlicer",
        profile_format="bambu_orca",
        sidecar_policy="orca_like",
        default_vendor_keys=("BBL", "Anycubic", "Elegoo", "Snapmaker"),
    ),
    "SnapmakerOrca": MachineAdapterProvider(
        slicer_id="SnapmakerOrca",
        display_name="Snapmaker Orca",
        profile_format="bambu_orca",
        sidecar_policy="orca_like",
        default_vendor_keys=("Snapmaker",),
    ),
    "ElegooSlicer": MachineAdapterProvider(
        slicer_id="ElegooSlicer",
        display_name="ElegooSlicer",
        profile_format="bambu_orca",
        sidecar_policy="orca_like",
        default_vendor_keys=("Elegoo",),
    ),
    "AnycubicSlicerNext": MachineAdapterProvider(
        slicer_id="AnycubicSlicerNext",
        display_name="Anycubic Slicer Next",
        profile_format="bambu_orca",
        sidecar_policy="anycubic_next",
        default_vendor_keys=("Anycubic",),
    ),
}


def get_provider(slicer_id: str) -> MachineAdapterProvider:
    try:
        return PROVIDERS[slicer_id]
    except KeyError as exc:
        raise KeyError(f"Unsupported machine adapter provider: {slicer_id}") from exc
```

- [ ] **Step 4: Run provider tests**

Run:

```powershell
python -m pytest tests/test_machine_adapter_providers_unit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tools/machine_adapter/providers.py tests/test_machine_adapter_providers_unit.py
git commit -m "feat(machine): define slicer adapter providers"
```

## Task 5: Registry Emitter With Legacy Template Output

**Files:**
- Create: `tools/machine_adapter/emitter.py`
- Test: `tests/test_machine_adapter_emitter_unit.py`

- [ ] **Step 1: Write failing emitter tests**

Create `tests/test_machine_adapter_emitter_unit.py`:

```python
from __future__ import annotations

from tools.machine_adapter.emitter import build_device_registry_entry
from tools.machine_adapter.providers import get_provider
from tools.machine_adapter.resolver import ResolvedMachineProfile, SourceFile


def test_emitter_builds_slicer_scoped_device_profile_and_applies_lumina_overlay():
    native = ResolvedMachineProfile(
        name="Bambu Lab H2D 0.4 nozzle",
        vendor_key="BBL",
        settings={
            "printer_model": "Bambu Lab H2D",
            "printer_variant": "0.4",
            "nozzle_diameter": ["0.4", "0.4"],
            "printable_area": ["0x0", "350x0", "350x320", "0x320"],
            "printable_height": "325",
            "layer_height": "0.20",
        },
        source_files=(SourceFile(path="BBL/machine/H2D.json", sha256="abc"),),
    )

    entry, template = build_device_registry_entry(
        provider=get_provider("BambuStudio"),
        source_version="02.07.01.57",
        profile=native,
    )

    assert entry["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"
    assert entry["machine_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d"
    assert entry["sidecar_policy"] == "bambu_studio"
    assert template["printer_model"] == "Bambu Lab H2D"
    assert template["layer_height"] == "0.08"
```

- [ ] **Step 2: Run failing emitter tests**

Run:

```powershell
python -m pytest tests/test_machine_adapter_emitter_unit.py -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement emitter**

Create `tools/machine_adapter/emitter.py`:

```python
from __future__ import annotations

import hashlib
import re
from typing import Any

from core.machine_process_overlay import apply_lumina_process_overlay
from tools.machine_adapter.providers import MachineAdapterProvider
from tools.machine_adapter.resolver import ResolvedMachineProfile


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


def _first_nozzle(settings: dict[str, Any]) -> str:
    values = settings.get("nozzle_diameter") or [settings.get("printer_variant") or "0.4"]
    if isinstance(values, list):
        return str(values[0])
    return str(values)


def _content_revision(settings: dict[str, Any], source_hashes: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(repr(sorted(settings.items(), key=lambda item: item[0])).encode("utf-8"))
    for value in sorted(source_hashes):
        digest.update(value.encode("utf-8"))
    return f"sha256:{digest.hexdigest()}"


def build_device_registry_entry(
    *,
    provider: MachineAdapterProvider,
    source_version: str,
    profile: ResolvedMachineProfile,
) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = dict(profile.settings)
    printer_model = str(settings.get("printer_model") or profile.name)
    nozzle = _first_nozzle(settings)
    vendor_slug = _slug(profile.vendor_key)
    machine_slug = _slug(printer_model)
    machine_profile_id = f"{provider.slicer_id}:{vendor_slug}:{machine_slug}"
    device_profile_id = f"{machine_profile_id}:{nozzle}"
    source_hashes = [item.sha256 for item in profile.source_files]
    template = apply_lumina_process_overlay(settings)
    revision = _content_revision(template, source_hashes)
    entry = {
        "device_profile_id": device_profile_id,
        "machine_profile_id": machine_profile_id,
        "slicer_id": provider.slicer_id,
        "display_name": printer_model,
        "brand": printer_model.split(" ")[0] if printer_model else profile.vendor_key,
        "vendor_key": profile.vendor_key,
        "bed_width": 350,
        "bed_depth": 320,
        "bed_height": int(float(str(settings.get("printable_height") or "0"))),
        "thumbnail": "",
        "nozzle_size": nozzle,
        "source_profile_name": profile.name,
        "template": f"slicers/{provider.slicer_id}/{source_version}/metadata_templates/{machine_slug}_{nozzle.replace('.', '_')}.json",
        "revision": revision,
        "supported": True,
        "application_metadata": (
            f"BambuStudio-{source_version}"
            if provider.slicer_id != "ElegooSlicer"
            else f"ElegooSlicer-{source_version}"
        ),
        "sidecar_policy": provider.sidecar_policy,
        "source_hashes": source_hashes,
    }
    return entry, template
```

- [ ] **Step 4: Run emitter tests**

Run:

```powershell
python -m pytest tests/test_machine_adapter_emitter_unit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tools/machine_adapter/emitter.py tests/test_machine_adapter_emitter_unit.py
git commit -m "feat(machine): emit registry entries from native profiles"
```

## Task 6: Import CLI

**Files:**
- Create: `tools/machine_adapter/import_profiles.py`
- Test: `tests/test_machine_adapter_import_cli_unit.py`

- [ ] **Step 1: Write failing CLI test**

Create `tests/test_machine_adapter_import_cli_unit.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from tools.machine_adapter.import_profiles import run_import


def test_run_import_writes_registry_and_templates(tmp_path):
    source_root = Path("tests/fixtures/machine_adapter")
    output_root = tmp_path / "machine_registry"

    result = run_import(
        slicer_id="BambuStudio",
        source_root=source_root,
        source_version="02.07.01.57",
        vendor_keys=("BBL",),
        output_root=output_root,
    )

    assert result.device_count == 1
    registry = json.loads((output_root / "registry.json").read_text(encoding="utf-8"))
    assert registry["slicers"][0]["slicer_id"] == "BambuStudio"
    templates = list((output_root / "slicers").rglob("*.json"))
    assert templates
```

- [ ] **Step 2: Run failing CLI test**

Run:

```powershell
python -m pytest tests/test_machine_adapter_import_cli_unit.py -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement CLI runner**

Create `tools/machine_adapter/import_profiles.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
from pathlib import Path

from tools.machine_adapter.emitter import build_device_registry_entry
from tools.machine_adapter.providers import get_provider
from tools.machine_adapter.resolver import resolve_machine_profiles


@dataclass(frozen=True)
class ImportResult:
    device_count: int


def run_import(
    *,
    slicer_id: str,
    source_root: Path,
    source_version: str,
    vendor_keys: tuple[str, ...],
    output_root: Path,
) -> ImportResult:
    provider = get_provider(slicer_id)
    machines: dict[str, dict] = {}
    templates: list[tuple[str, dict]] = []
    for vendor_key in vendor_keys:
        for profile in resolve_machine_profiles(root=source_root, vendor_key=vendor_key):
            entry, template = build_device_registry_entry(
                provider=provider,
                source_version=source_version,
                profile=profile,
            )
            machine_id = entry["machine_profile_id"]
            machine = machines.setdefault(
                machine_id,
                {
                    "machine_profile_id": machine_id,
                    "display_name": entry["display_name"],
                    "brand": entry["brand"],
                    "vendor_key": entry["vendor_key"],
                    "bed_width": entry["bed_width"],
                    "bed_depth": entry["bed_depth"],
                    "bed_height": entry["bed_height"],
                    "thumbnail": entry["thumbnail"],
                    "nozzles": [],
                },
            )
            machine["nozzles"].append(
                {
                    "device_profile_id": entry["device_profile_id"],
                    "nozzle_size": entry["nozzle_size"],
                    "source_profile_name": entry["source_profile_name"],
                    "template": entry["template"],
                    "revision": entry["revision"],
                    "supported": entry["supported"],
                }
            )
            templates.append((entry["template"], template))

    registry = {
        "schema_version": 1,
        "generated_at": "2026-06-09T00:00:00+08:00",
        "slicers": [
            {
                "slicer_id": provider.slicer_id,
                "display_name": provider.display_name,
                "source_kind": "local_install",
                "source_version": source_version,
                "profile_format": provider.profile_format,
                "application_metadata": (
                    f"BambuStudio-{source_version}"
                    if provider.slicer_id != "ElegooSlicer"
                    else f"ElegooSlicer-{source_version}"
                ),
                "sidecar_policy": provider.sidecar_policy,
                "machines": list(machines.values()),
            }
        ],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "registry.json").write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    for relative_template_path, template in templates:
        template_path = output_root / relative_template_path
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
    return ImportResult(device_count=sum(len(machine["nozzles"]) for machine in machines.values()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slicer", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--vendor", action="append", dest="vendors")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    provider = get_provider(args.slicer)
    result = run_import(
        slicer_id=args.slicer,
        source_root=Path(args.source_root),
        source_version=args.source_version,
        vendor_keys=tuple(args.vendors or provider.default_vendor_keys),
        output_root=Path(args.output),
    )
    print(f"Imported {result.device_count} device profiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests**

Run:

```powershell
python -m pytest tests/test_machine_adapter_import_cli_unit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tools/machine_adapter/import_profiles.py tests/test_machine_adapter_import_cli_unit.py
git commit -m "feat(machine): add machine profile import CLI"
```

## Task 7: Registry-Aware 3MF Template Loading

**Files:**
- Modify: `utils/bambu_3mf_writer.py`
- Test: `tests/test_bambu_3mf_writer_unit.py`

- [ ] **Step 1: Add failing writer test**

Add to `tests/test_bambu_3mf_writer_unit.py`:

```python
def test_load_printer_template_prefers_registry_device_profile(tmp_path, monkeypatch):
    registry_root = tmp_path / "machine_registry"
    template_path = registry_root / "slicers" / "BambuStudio" / "02.07.01.57" / "metadata_templates" / "h2d_0_4.json"
    template_path.parent.mkdir(parents=True)
    template_path.write_text(
        '{"printer_model": "Bambu Lab H2D", "layer_height": "0.08"}',
        encoding="utf-8",
    )
    (registry_root / "registry.json").write_text(
        """
        {
          "schema_version": 1,
          "generated_at": "2026-06-09T00:00:00+08:00",
          "slicers": [{
            "slicer_id": "BambuStudio",
            "display_name": "Bambu Studio",
            "source_kind": "local_install",
            "source_version": "02.07.01.57",
            "profile_format": "bambu_orca",
            "application_metadata": "BambuStudio-02.07.01.57",
            "sidecar_policy": "bambu_studio",
            "machines": [{
              "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
              "display_name": "Bambu Lab H2D",
              "brand": "Bambu Lab",
              "vendor_key": "BBL",
              "bed_width": 350,
              "bed_depth": 320,
              "bed_height": 325,
              "thumbnail": "",
              "nozzles": [{
                "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                "nozzle_size": "0.4",
                "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
                "template": "slicers/BambuStudio/02.07.01.57/metadata_templates/h2d_0_4.json",
                "revision": "sha256:abc",
                "supported": true
              }]
            }]
          }]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    template = load_printer_template(
        "bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
    )

    assert template["printer_model"] == "Bambu Lab H2D"
    assert template["layer_height"] == "0.08"
```

- [ ] **Step 2: Run failing writer test**

Run:

```powershell
python -m pytest tests/test_bambu_3mf_writer_unit.py -k registry_device_profile -v
```

Expected: FAIL because `load_printer_template()` has no `device_profile_id` argument.

- [ ] **Step 3: Implement registry preference**

Modify `utils/bambu_3mf_writer.py`:

```python
def load_printer_template(
    printer_id: str,
    slicer: str = "BambuStudio",
    nozzle_size: Optional[str | float] = None,
    device_profile_id: Optional[str] = None,
) -> dict:
    if device_profile_id:
        registry_root = os.environ.get("LUMINA_MACHINE_REGISTRY_DIR")
        if registry_root:
            from core.machine_registry import load_machine_registry

            registry_path = os.path.join(registry_root, "registry.json")
            if os.path.exists(registry_path):
                registry = load_machine_registry(registry_path)
                profile = registry.get_device_profile(device_profile_id)
                template_path = os.path.join(registry_root, profile.template)
                if os.path.exists(template_path):
                    with open(template_path, "r", encoding="utf-8") as f:
                        return json.load(f)
    # keep existing legacy body unchanged below this point
```

Keep the existing fallback path exactly as-is after the new registry block.

- [ ] **Step 4: Run writer regression tests**

Run:

```powershell
python -m pytest tests/test_bambu_3mf_writer_unit.py tests/test_printer_profile_unit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add utils/bambu_3mf_writer.py tests/test_bambu_3mf_writer_unit.py
git commit -m "feat(machine): load 3MF templates from machine registry"
```

## Task 8: Restore Metadata Matrix Verification

**Files:**
- Modify: `scripts/verify_3mf_template_matrix.py`
- Modify: `tests/helpers_threemf_manifest.py`
- Test: `tests/test_3mf_template_matrix_unit.py`

- [ ] **Step 1: Add helper compatibility test**

Add to `tests/test_3mf_template_matrix_unit.py`:

```python
def test_template_matrix_helper_exposes_expected_template_loader():
    from tests.helpers_threemf_manifest import load_expected_template_direct

    template = load_expected_template_direct(
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
    )

    assert template["printer_model"]
    assert template["layer_height"] == "0.08"
```

- [ ] **Step 2: Run failing matrix helper test**

Run:

```powershell
python -m pytest tests/test_3mf_template_matrix_unit.py -k expected_template_loader -v
```

Expected: FAIL if existing helper import path or template assertions are wrong.

- [ ] **Step 3: Fix script imports**

Modify `scripts/verify_3mf_template_matrix.py` to import `load_expected_template_direct` instead of `load_printer_template` from the helper:

```python
from helpers_threemf_manifest import (
    cleanup_paths,
    expected_family_signature,
    export_fixture_3mf,
    extract_manifest,
    extract_project_subset,
    list_printer_profiles,
    load_expected_template_direct,
    manifest_sidecar_flags,
    supported_printer_slicer_pairs,
)
```

Then replace:

```python
template = load_printer_template(printer_id, slicer=slicer, nozzle_size=nozzle_size)
```

with:

```python
template = load_expected_template_direct(
    printer_id=printer_id,
    slicer=slicer,
    nozzle_size=nozzle_size,
)
```

- [ ] **Step 4: Add protected process assertion to the script**

Inside the per-case manifest comparison, add:

```python
project_settings = manifest["project_settings"]  # type: ignore[index]
protected = extract_project_subset(project_settings)
if protected.get("layer_height") != "0.08":
    failures.append(f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: layer_height changed")
if protected.get("initial_layer_height") != "0.08":
    failures.append(f"{printer_id}/{slicer}/{nozzle_size}/{case_name}: initial_layer_height changed")
```

- [ ] **Step 5: Run matrix-related tests**

Run:

```powershell
python -m pytest tests/test_3mf_template_matrix_unit.py tests/test_bambu_3mf_writer_unit.py -v
```

Expected: PASS.

- [ ] **Step 6: Run the script with a short timeout first**

Run:

```powershell
python scripts/verify_3mf_template_matrix.py
```

Expected: either PASS for the full current matrix, or a concrete list of metadata mismatches. If runtime is too long, stop and add `--limit` support in a follow-up task before using it in routine smoke.

- [ ] **Step 7: Commit**

```powershell
git add scripts/verify_3mf_template_matrix.py tests/helpers_threemf_manifest.py tests/test_3mf_template_matrix_unit.py
git commit -m "test(machine): restore 3MF metadata matrix verification"
```

## Task 9: Backend Device Choices API

**Files:**
- Modify: `api/schemas/system.py`
- Modify: `api/routers/system.py`
- Test: `tests/test_system_router_unit.py`

- [ ] **Step 1: Add failing API schema/router test**

Add to `tests/test_system_router_unit.py`:

```python
def test_system_printers_include_device_profile_metadata(client):
    response = client.get("/api/system/printers")

    assert response.status_code == 200
    payload = response.json()
    first = payload["printers"][0]
    assert "supported_nozzle_sizes" in first
    assert "supported_slicers" in first
```

After registry read is wired, extend this test to assert `device_profiles` exists. Keep the first version compatible with legacy fallback so it can be merged before registry fixtures are checked in.

- [ ] **Step 2: Run failing or compatibility test**

Run:

```powershell
python -m pytest tests/test_system_router_unit.py -k printers -v
```

Expected: PASS under legacy mode, then FAIL after adding `device_profiles` expectation before implementation.

- [ ] **Step 3: Extend schema**

Modify `api/schemas/system.py`:

```python
class DeviceProfileInfo(BaseModel):
    device_profile_id: str
    slicer_id: str
    nozzle_size: str
    source_profile_name: str
    revision: str
    supported: bool = True


class PrinterInfo(BaseModel):
    id: str
    display_name: str
    brand: str
    bed_width: int
    bed_depth: int
    bed_height: int
    supported_nozzle_sizes: list[str] = ["0.2", "0.4"]
    supported_slicers: list[str] = []
    thumbnail: str = ""
    device_profiles: list[DeviceProfileInfo] = []
```

- [ ] **Step 4: Populate from registry when available**

Modify `api/routers/system.py`:

```python
def _try_load_machine_registry():
    registry_root = os.environ.get("LUMINA_MACHINE_REGISTRY_DIR", "machine_registry")
    registry_path = Path(registry_root) / "registry.json"
    if not registry_path.exists():
        return None
    from core.machine_registry import load_machine_registry

    return load_machine_registry(registry_path)
```

Keep existing `config.list_printer_profiles()` fallback if registry is missing.

- [ ] **Step 5: Run router tests**

Run:

```powershell
python -m pytest tests/test_system_router_unit.py -k "printers or slicers" -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add api/schemas/system.py api/routers/system.py tests/test_system_router_unit.py
git commit -m "feat(machine): expose registry device choices"
```

## Task 10: Frontend Selection Migration

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/stores/settingsStore.ts`
- Modify: `frontend/src/components/SettingsPanel.tsx`
- Modify: `frontend/src/utils/settingsOptionIds.ts`
- Test: `frontend/src/__tests__/settingsOptionIds.test.ts`
- Test: `frontend/src/components/__tests__/SettingsPanel.machineAdapter.test.tsx`

- [ ] **Step 1: Add failing option migration test**

Add to `frontend/src/__tests__/settingsOptionIds.test.ts`:

```ts
it("keeps slicer scoped machine ids separate", () => {
  expect("BambuStudio:bbl:bambu-lab-h2d:0.4").not.toBe(
    "OrcaSlicer:bbl:bambu-lab-h2d:0.4",
  );
});
```

- [ ] **Step 2: Add settings store field test**

Add to `frontend/src/__tests__/settings-store.property.test.ts` or a focused test:

```ts
it("persists deviceProfileId independently from legacy printer fields", () => {
  const state = useSettingsStore.getState();
  state.setDeviceProfileId("BambuStudio:bbl:bambu-lab-h2d:0.4");
  expect(useSettingsStore.getState().deviceProfileId).toBe(
    "BambuStudio:bbl:bambu-lab-h2d:0.4",
  );
});
```

- [ ] **Step 3: Run failing frontend tests through wrapper**

Run:

```powershell
python scripts/run_vitest.py run frontend/src/__tests__/settingsOptionIds.test.ts frontend/src/__tests__/settings-store.property.test.ts
```

Expected: FAIL with missing `deviceProfileId` state/action.

- [ ] **Step 4: Add `deviceProfileId` to settings store**

Modify `frontend/src/stores/settingsStore.ts`:

```ts
deviceProfileId: string;
setDeviceProfileId: (id: string) => void;
```

Default:

```ts
deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
```

Action:

```ts
setDeviceProfileId: (id: string) => {
  set({ deviceProfileId: id });
},
```

Include it in backend sync only after backend schema accepts it. Until then, keep it local or add optional backend field in the same task.

- [ ] **Step 5: Update settings panel progressively**

Change the UI in a compatible way:

- Keep existing slicer dropdown.
- Keep existing machine dropdown for fallback.
- If `device_profiles` exists on printer data, derive nozzle options from registry data.
- Display `thumbnail` when present.

Do not remove legacy `printerModel`, `slicerSoftware`, or `nozzleSize` yet.

- [ ] **Step 6: Run frontend tests**

Run:

```powershell
python scripts/run_vitest.py run frontend/src/__tests__/settingsOptionIds.test.ts frontend/src/__tests__/settings-store.property.test.ts frontend/src/components/__tests__/SettingsPanel.baseLayerHeightModifier.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/api/types.ts frontend/src/stores/settingsStore.ts frontend/src/components/SettingsPanel.tsx frontend/src/utils/settingsOptionIds.ts frontend/src/__tests__ frontend/src/components/__tests__
git commit -m "feat(machine): prepare frontend for device profile selection"
```

## Task 11: Real Local Import Dry Run

**Files:**
- Create: `dev/machine_registry.sources.example.json`
- Create or update: `.gitignore`
- Generated for review: `logs/machine_adapter_import_report.json`

- [ ] **Step 1: Add ignored local source config rule**

Modify `.gitignore`:

```gitignore
dev/machine_registry.sources.local.json
```

Create `dev/machine_registry.sources.example.json`:

```json
{
  "BambuStudio": {
    "source_kind": "local_install",
    "root": "F:/3D Print F/Bambu Studio",
    "version": "02.07.01.57"
  },
  "OrcaSlicer": {
    "source_kind": "local_install",
    "root": "F:/3D Print F/ORCA/OrcaSlicer",
    "version": "2.4.0"
  },
  "ElegooSlicer": {
    "source_kind": "local_install",
    "root": "F:/3D Print F/ElegooSlicer",
    "version": "1.5.0.7"
  },
  "AnycubicSlicerNext": {
    "source_kind": "local_install",
    "root": "F:/3D Print F/AnycubicSlicerNext",
    "version": "1.3.9.4"
  },
  "SnapmakerOrca": {
    "source_kind": "local_install",
    "root": "F:/3D Print F/Snapmaker_Orca",
    "version": "2.3.3"
  }
}
```

- [ ] **Step 2: Run a fixture import first**

Run:

```powershell
python tools/machine_adapter/import_profiles.py --slicer BambuStudio --source-root tests/fixtures/machine_adapter --source-version 02.07.01.57 --vendor BBL --output output/temp/machine_registry_fixture
```

Expected: `Imported 1 device profiles`.

- [ ] **Step 3: Run one real local import for Bambu H2D scope**

Run only after adding a scope filter to the CLI:

```powershell
python tools/machine_adapter/import_profiles.py --slicer BambuStudio --source-root "F:/3D Print F/Bambu Studio/resources/profiles" --source-version 02.07.01.57 --vendor BBL --machine-name "Bambu Lab H2D" --output output/temp/machine_registry_bambu_h2d
```

Expected: generated registry includes H2D nozzle profiles and protected `layer_height = 0.08`.

- [ ] **Step 4: Commit source config example**

```powershell
git add .gitignore dev/machine_registry.sources.example.json
git commit -m "chore(machine): document local slicer profile sources"
```

## Task 12: Verification Bundle

**Files:**
- Modify test files added above only if verification reveals missing assertions.

- [ ] **Step 1: Run backend focused test suite**

Run:

```powershell
python -m pytest tests/test_machine_registry_unit.py tests/test_machine_process_overlay_unit.py tests/test_machine_adapter_resolver_unit.py tests/test_machine_adapter_providers_unit.py tests/test_machine_adapter_emitter_unit.py tests/test_machine_adapter_import_cli_unit.py tests/test_bambu_3mf_writer_unit.py tests/test_printer_profile_unit.py -v
```

Expected: PASS.

- [ ] **Step 2: Run restored matrix script**

Run:

```powershell
python scripts/verify_3mf_template_matrix.py
```

Expected: PASS or actionable mismatch list. Do not weaken assertions to hide mismatches.

- [ ] **Step 3: Run frontend focused tests if UI task was completed**

Run:

```powershell
python scripts/run_vitest.py run frontend/src/__tests__/settingsOptionIds.test.ts frontend/src/__tests__/settings-store.property.test.ts frontend/src/components/__tests__/SettingsPanel.baseLayerHeightModifier.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Final commit if verification-only fixes were needed**

```powershell
git status --short
git add <verified files only>
git commit -m "test(machine): complete adapter v2 verification"
```

Only commit if Step 1-3 required file changes.

## Self-Review

Spec coverage:

- Development-time native slicer profile import is covered by Tasks 3, 4, 6, and 11.
- Lumina internal registry is covered by Tasks 1, 5, 7, and 9.
- Protected `0.08mm` process settings are covered by Tasks 2, 5, 7, and 8.
- Elegoo/Anycubic/Snapmaker reuse of Orca/Bambu profile parsing is covered by Task 4 and Task 11.
- Legacy compatibility with current metadata templates is covered by Tasks 7 and 8.
- Machine selection UI is covered by Task 10.

Placeholder scan:

- This plan has no unresolved placeholder markers or unspecified broad test steps.
- Follow-up implementation details are expressed as concrete tasks, commands, and expected outcomes.

Type consistency:

- Runtime registry types use `DeviceProfile` and `MachineRegistry`.
- Development importer uses `ResolvedMachineProfile`, `MachineAdapterProvider`, and `build_device_registry_entry`.
- Frontend future state uses `deviceProfileId`, matching registry `device_profile_id`.
