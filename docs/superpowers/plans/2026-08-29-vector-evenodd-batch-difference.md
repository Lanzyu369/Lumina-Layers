# Vector Evenodd Batch Difference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace repeated GEOS subtraction of independent evenodd holes with one geometry-equivalent batch subtraction.

**Architecture:** Preserve the current containment and pairwise-disjoint eligibility checks. Convert the verified hole list into one polygonal collection with the existing disjoint geometry helper, subtract it once, and retain the current general fallback for every other case.

**Tech Stack:** Python, Shapely/GEOS, pytest, cProfile

---

### Task 1: Lock the hot-path contract

**Files:**
- Modify: `tests/test_vector_engine_fixes_unit.py`

- [x] **Step 1: Write the failing test**

Add a test that constructs one outer polygon and several contained,
pairwise-disjoint holes. Compute the expected geometry before instrumentation,
then monkeypatch `shapely.difference` to record calls:

```python
def test_evenodd_helper_subtracts_disjoint_holes_in_one_geos_call(monkeypatch):
    outer = box(0, 0, 100, 100)
    holes = [box(x, 10, x + 4, 14) for x in range(10, 70, 10)]
    expected = outer.difference(shapely_unary_union(holes))
    real_difference = shapely.difference
    calls = []

    def recording_difference(left, right, **kwargs):
        calls.append((left, right))
        return real_difference(left, right, **kwargs)

    monkeypatch.setattr(shapely, "difference", recording_difference)
    merged = _combine_evenodd_polygons([outer, *holes])

    assert len(calls) == 1
    assert merged is not None
    assert merged.symmetric_difference(expected).is_empty
```

- [x] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest tests/test_vector_engine_fixes_unit.py::TestFillRuleSubpathMerging::test_evenodd_helper_subtracts_disjoint_holes_in_one_geos_call -q
```

Expected: FAIL because the current implementation invokes `difference` once
per hole.

### Task 2: Batch the verified hole subtraction

**Files:**
- Modify: `core/vector_engine.py:564-592`

- [x] **Step 1: Implement the minimal change**

Replace the sequential subtraction loop with:

```python
hole_collection = _polygonal_union_for_disjoint_items(children)
if hole_collection is None or hole_collection.is_empty:
    return None
result = container.difference(hole_collection)
if result is None or result.is_empty:
    return None
return result
```

- [x] **Step 2: Verify GREEN and existing semantics**

Run:

```bash
python3 -m pytest \
  tests/test_vector_engine_fixes_unit.py::TestFillRuleSubpathMerging \
  tests/test_vector_engine_part2_5_unit.py \
  tests/test_vector_input_validation_unit.py -q
```

Expected: all selected tests pass.

### Task 3: Verify the real R4C1 result and performance

**Files:**
- No tracked files

- [x] **Step 1: Parse the exact fixture at 111 mm**

Run a process-level measurement for:

```text
/Volumes/personal_folder/person_8ba86fa3823aff049badd414e7c525f2_20260814_130551_vector.svg
```

Record total `_parse_svg` wall time, shape count, bounds, total area, and peak
RSS. Confirm the pre-normalization batch subtraction is topologically equal to
the sequential result. Because equivalent GEOS ring layouts can produce tiny
floating-point changes in the later close/open normalization, record maximum
boundary displacement and verify real slicer coverage rather than requiring
byte-identical WKB after normalization.

- [x] **Step 2: Run the focused regression suite**

Run:

```bash
python3 -m pytest \
  tests/test_vector_engine_fixes_unit.py \
  tests/test_vector_engine_part2_5_unit.py \
  tests/test_vector_input_validation_unit.py \
  tests/test_vector_engine_mesh_weld_unit.py -q
git diff --check
```

Expected: all tests pass and `git diff --check` emits no output.
