# Native SVG fast path independent review

## Scope

The review covers the `MOVIBALE/feat/native-svg-core` topic branch based on
the exact PR #585 dependency commit
`892906a90fe4152b5af0120830254228748878d7`. The standalone package, Lumina
adapter, whole-document fallback policy, packaging, benchmark, and retained
slicer evidence are in scope. Merging is explicitly out of scope.

The independent passes returned **Approved with fixes**. All six P1 and five
P2 findings below were addressed before the exact-SHA re-review.

## Findings and dispositions

| Priority | Finding | Disposition |
|---|---|---|
| P1 | Namespace preflight copied the complete binding map at every nesting level, allowing an avoidable depth-by-binding resource amplifier. | Replaced it with an incremental XLink binding stack and exact open-element stack. XML Name/UTF-8 validation preserves deterministic invalid-versus-unsupported results. A bounded nested-binding amplifier test now enforces time and RSS ceilings. |
| P1 | The native adapter did not apply the legacy `0.01` source-unit-squared threshold to every disconnected visible component. | Moved the historical threshold to `core/vector_geometry_contract.py` and applied the same constant in both legacy and native paths. Differential tests cover separate paints and disconnected components of one paint. |
| P1 | `<symbol>` content could be omitted without requesting fallback. | The pinned LunaSVG capability recorder now returns `unsupported_symbol`; direct and `<use>` product tests prove whole-document legacy parity. |
| P1 | Explicit root `preserveAspectRatio` values could change viewport semantics. | Every valid explicit root value now returns `unsupported_preserve_aspect_ratio`; malformed values remain invalid and nested SVG keeps its existing fallback reason. Whitespace, `none`, `meet`, and `slice` cases are covered. |
| P1 | Inline CSS comments could alter property tokenization and material identity. | Inline comments, including unterminated comments, now return `unsupported_css_comment`. Recorder and product differential tests verify material and topology parity through whole-document fallback. |
| P1 | Recorder precision, native flattening/grid error, and legacy GEOS simplification could place raw or disconnected-component areas on opposite sides of the legacy thresholds. | The C++ kernel now computes conservative area intervals from all allocated error sources and requests whole-document fallback with `legacy_area_threshold_ambiguous` whenever either classification is not provable. Just-below/just-above tests cover both the dynamic raw-paint threshold and the fixed `0.01` component threshold; unsupported results remain canonically empty. |
| P2 | Slicer evidence could count pure-E priming or auxiliary extrusion as material proof. | Evidence now requires positive extrusion with real XY movement inside a model feature, tracks G90/G91 and G92, preserves absolute E across tool changes, and excludes custom, prime/purge/wipe tower, skirt/brim, and support features. Both real slicers were rerun twice. |
| P2 | The supported benchmark fixture recorded selected source indices without independently recomputing why they were safe. | `--verify` now ranks source paths by exact serialized XML byte length, checks every candidate at the worst-precision placement, incrementally verifies the growing compound panel, and rechecks the final tiled document plus all four legacy compatibility flags. It reproduces the checked-in 64-index tuple exactly. |
| P2 | Release builds used mutable Action tags and incompletely fixed build tools. | Workflow Actions are pinned to immutable commits. The sdist/wheel build inputs are exact versions of scikit-build-core, pybind11, NumPy, CMake, and Ninja; clean wheel and sdist installs passed the standalone suite. |
| P2 | The dedicated product-artifacts CI job did not execute the benchmark contract that recomputes the 3,097-source-path ranking, per-candidate gates, incremental panel, and final fixture. | Added `tests/test_native_svg_benchmark_contract_unit.py` to the job's focused pytest list, so a stale generator, selected tuple, fixture, or provenance fails the PR gate. |
| P2 | The validation narrative claimed a wider local search for the >=50 MiB regression SVG than the structured report recorded. | Narrowed the claim to the workspace root present in `searched_roots`; the missing large-file RSS/swap gate remains explicitly pending. |

## Verification evidence

- Standalone package: `393 passed`.
- Lumina native SVG adapter, differential, fallback, packaging, slicer, and
  workflow tests: `152 passed`, with four rasterio deprecation warnings.
- Other changed-path/downstream tests: `195 passed`, `1 skipped` because
  PowerShell is unavailable on the reference Mac.
- Upload and streamed SVG limit tests: `7 passed`.
- Logging governance unit tests: `21 passed`; fast governed workflow: PASS
  with 14 INFO lines, zero warning/error records, and zero catch-all events.
- Smoke gate: backend `162 passed, 6215 deselected`; frontend `161 passed`;
  lint reported zero errors and 68 pre-existing warnings.
- Complete backend run before correcting the finite-stream upload test helper:
  `6311 passed, 37 skipped, 3 deselected, 22 failed`. Exact-node comparison
  against `892906a...` reproduced 20 failures unchanged; the memory-preflight
  node passed, and the sole branch-only failure was the test helper returning
  upload bytes forever. After modelling EOF, the affected tests pass. The 20
  remaining failures are therefore baseline failures, not hidden as passes.
- Complete frontend run on the topic branch: all `2782` assertions passed and
  one test skipped, but Vitest exited non-zero for a post-test dynamic-import
  rejection in `SettingsPanel.machineAdapter.test.tsx`. The exact base has the
  same unhandled rejection plus two additional assertion failures.
- Public `VectorProcessor.analyze_svg` benchmark: 0.224664375 s warm median,
  0.227735625 s p95, 222,593,024-byte peak RSS, zero measured swap growth.
- Real Bambu Studio and OrcaSlicer runs: both passed twice with stable
  normalized toolpath fingerprints and qualifying model extrusion for tools
  0 through 4.
- Clean CPython 3.12 wheel and sdist installs each passed all 393 tests. The
  production macOS arm64 PyInstaller onefile probe executed the native backend
  and contained the extension plus all required license texts.

## Honest release boundaries

- The real R4C1 SHA is recorded, but its `non-scaling-stroke` content correctly
  requests `unsupported_vector_effect`; native-by-default R4C1 is not claimed.
- No real SVG at or above 50 MiB was available locally, so the separate 2 GiB
  RSS / 256 MiB swap gate remains pending rather than being substituted with a
  smaller file.
- Windows, macOS x86_64, Linux wheel, Docker, and Windows production onefile
  jobs are configured. They become evidence only after the pushed PR CI passes.
- Moving `lumina-svg-core` to a separate repository/package index still needs
  an owner and namespace decision. The in-tree library is publishable first;
  Lumina must then depend on its exact released version.

## Exact-SHA re-review

The runtime and geometry review examined
`07584903aad9d58b78088b8527b558d18bc64a28`. It found no P0 or P1 issue and
requested only the two evidence/CI P2 fixes recorded above. The closure review
then examined `703ff9e62138800310f40e77e1f7e4a7900c52cc`, confirmed both P2s
closed, and reported no remaining P0, P1, or P2 findings.

Final independent verdict: **Approved**.
