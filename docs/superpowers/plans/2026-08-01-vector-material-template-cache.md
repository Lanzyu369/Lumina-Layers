# Vector Material Template Cache Implementation Plan

**Goal:** Eliminate repeated deterministic recipe-template generation in
inverse refinement without changing any colour, recipe, material matrix,
geometry, or exported-model result.

**Architecture:** Reuse an immutable, bounded-LRU recipe-index template keyed
by material count, recipe depth, candidate budget, and seed. Prewarm distinct
keys before workspace threads start, then retain the existing per-subset
mapping and exact refinement algorithm.

## File Map

- Modify `core/material_inverse_refinement.py`.
- Modify `tests/test_material_inverse_refinement_unit.py`.
- Add a source-backed results report under `docs/superpowers/specs/`.
- Use `scripts/profile_converter_multicore.py` unchanged for semantic and
  performance comparisons.

## Tasks

- [x] Profile the supplied 9,503-colour SVG and identify repeated candidate
  generation as the dominant avoidable cost.
- [x] Reject the target-row batching experiment after its real timing and RSS
  regression despite exact output parity.
- [x] Add a failing regression test proving shape-equivalent subsets should
  share one deterministic recipe-index template.
- [x] Implement an immutable, bounded template cache.
- [x] Prewarm distinct request keys before worker fan-out.
- [x] Restore the original exact per-row search and parallelism semantics.
- [x] Run focused inverse-refinement tests.
- [x] Compare exact semantic snapshots for 8-, 12-, and 15-material archives.
- [x] Compare serial and four-worker complex-SVG timings and peak RSS.
- [x] Run the broader material/vector regression suites.
- [x] Run compile, log-quality, and diff-quality gates.
- [x] Record final commands, hashes, measurements, and retained/rejected
  decisions in the results report.
