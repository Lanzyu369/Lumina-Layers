# Base-Layer Modifier Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Bambu base-layer modifiers from truncating backing or upper color layers while preserving safe coarse-layer speedups.

**Architecture:** Keep the decision in `utils/bambu_3mf_writer.py`. Resolve a compatible coarse height on a 0.02 mm integer grid, omit unsafe metadata, and feed the resolver with limits from the selected printer template. Update the existing documentation and user-facing description to match the corrected behavior.

**Tech Stack:** Python 3, XML metadata, pytest, Hypothesis, Bambu Studio CLI, React i18n data.

---

### Task 1: Lock the regression with failing tests

**Files:**
- Modify: `tests/test_bambu_layer_config_ranges_unit.py`

- [ ] **Step 1: Change the double-sided expectation to a skip**

```python
def test_face_double_skips_layer_config() -> None:
    assert build_layer_config_ranges_xml(
        base_height_mm=0.24,
        color_height_mm=0.4,
        nozzle_mm=0.4,
        face="double",
    ) is None
```

- [ ] **Step 2: Add the 0.24 mm compatible-height expectation**

```python
@pytest.mark.parametrize("nozzle_mm", [0.2, 0.4])
def test_non_divisible_nominal_height_resolves_to_012(nozzle_mm: float) -> None:
    xml_bytes = build_layer_config_ranges_xml(
        base_height_mm=0.24,
        color_height_mm=0.4,
        nozzle_mm=nozzle_mm,
        face="down",
    )
    assert xml_bytes is not None
    assert _parse_range(xml_bytes)[2] == pytest.approx(0.12)
```

- [ ] **Step 3: Run the two tests and verify RED**

Run: `python -m pytest tests/test_bambu_layer_config_ranges_unit.py -k 'double or non_divisible' -v`

Expected: the double case emits XML and the 0.24 mm cases return 0.1/0.2 instead of 0.12.

### Task 2: Implement compatible coarse-height selection

**Files:**
- Modify: `utils/bambu_3mf_writer.py`
- Modify: `tests/test_bambu_layer_config_ranges_unit.py`

- [ ] **Step 1: Add an integer-grid resolver**

```python
def _resolve_compatible_base_layer_height_mm(
    *,
    base_height_mm: float,
    nozzle_mm: float,
    fine_layer_height_mm: float,
    min_layer_height_mm: float | None = None,
    max_layer_height_mm: float | None = None,
) -> float | None:
    # Convert to 0.02 mm ticks, filter exact divisors and select the candidate
    # nearest nozzle_mm * 0.5. Require at least two backing layers.
```

- [ ] **Step 2: Make `build_layer_config_ranges_xml` skip double-sided faces and call the resolver**

The builder must return `None` when the resolver returns no candidate. Add
optional keyword-only `min_layer_height_mm` and `max_layer_height_mm` inputs.

- [ ] **Step 3: Run the regression tests and verify GREEN**

Run: `python -m pytest tests/test_bambu_layer_config_ranges_unit.py -k 'double or non_divisible' -v`

Expected: all selected tests pass.

- [ ] **Step 4: Add property coverage for divisibility and bounds**

For every emitted XML payload assert:

```python
layer_count = base_height_mm / layer_height_mm
assert layer_count == pytest.approx(round(layer_count))
assert layer_count >= 2
assert layer_height_mm > fine_layer_height_mm
assert layer_height_mm <= max_layer_height_mm
```

- [ ] **Step 5: Run the complete writer test module**

Run: `python -m pytest tests/test_bambu_layer_config_ranges_unit.py -v`

Expected: PASS with no failures.

### Task 3: Feed printer limits into the resolver

**Files:**
- Modify: `utils/bambu_3mf_writer.py`
- Modify: `tests/test_bambu_layer_config_ranges_unit.py`

- [ ] **Step 1: Add failing writer-level forwarding coverage**

Patch `_get_base_config_template` to return `min_layer_height=["0.04"]` and
`max_layer_height=["0.14"]`; patch `build_layer_config_ranges_xml`; assert the
writer forwards `0.04`, `0.14`, and its configured fine layer height.

- [ ] **Step 2: Verify RED**

Run the new test alone. Expected: missing keyword arguments in the captured
builder call.

- [ ] **Step 3: Parse strict shared limits and forward them**

Use the largest valid minimum and smallest valid maximum from scalar or list
template settings. Pass them together with the actual `self.settings` layer
height when building metadata.

- [ ] **Step 4: Verify GREEN and run writer integrations**

Run:

```bash
python -m pytest tests/test_bambu_layer_config_ranges_unit.py tests/test_bambu_3mf_writer_unit.py tests/test_merged_3mf_writer_integration.py -v
```

Expected: PASS.

### Task 4: Align documentation and user-facing guidance

**Files:**
- Modify: `docs/3mf-metadata-export.md`
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `frontend/src/data/announcements.ts`
- Test: `frontend/src/components/__tests__/SettingsPanel.baseLayerHeightModifier.test.tsx`

- [ ] **Step 1: Update the formula documentation**

Document the half-nozzle target, 0.02 mm candidate grid, exact divisibility,
printer limits, two-layer minimum, and safe skip behavior.

- [ ] **Step 2: Update the settings description**

Explain that the app automatically chooses a compatible coarse height and
skips double-sided or non-divisible cases.

- [ ] **Step 3: Add a bilingual announcement entry**

State the user-visible outcome: double-sided upper color layers no longer lose
height, and non-default backing thicknesses are aligned or safely skipped.

- [ ] **Step 4: Run the focused frontend test**

Run: `python scripts/run_vitest.py run frontend/src/components/__tests__/SettingsPanel.baseLayerHeightModifier.test.tsx`

Expected: PASS.

### Task 5: Verify the original symptom and adjacent contracts

**Files:**
- No production file changes.

- [ ] **Step 1: Run backend regression tests**

```bash
python -m pytest tests/test_bambu_layer_config_ranges_unit.py tests/test_pipeline_bambu_base_layer_ctx_unit.py tests/test_s09_export_3mf_unit.py tests/test_puzzle_3mf_unit.py tests/test_merged_3mf_writer_integration.py -v
```

- [ ] **Step 2: Run a real Bambu Studio CLI slice**

Slice a 1.04 mm box representing `0.4 + 0.24 + 0.4` mm. Verify the corrected
double-sided export has no `Metadata/layer_config_ranges.xml`, 13 layers, and a
final `Z_HEIGHT` of 1.04 mm.

- [ ] **Step 3: Run hygiene checks**

Run `git diff --check`, scan touched UTF-8 files for common mojibake markers,
and confirm no Bambu Studio, backend, Vite, or test helper process remains.

- [ ] **Step 4: Review the final diff against every design requirement**

Confirm there are no API state changes, no geometry rounding, no unrelated
refactor, and no generated artifacts in the worktree.
