# Invalid Image and SVG 4xx Repair Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Return stable, actionable HTTP 422 responses for newly uploaded
images that cannot be decoded and SVG documents that cannot produce supported
visible vector geometry, plus HTTP 413 for decompression-bomb-sized images,
without reclassifying internal converter failures.

**Architecture:** Add a converter-preview source validator immediately after
the existing upload write and before worker submission. It uses Pillow's
`verify()` plus a complete pixel decode for ordinary rasters, offloaded with
`asyncio.to_thread()`, and XML/root validation for SVG, without changing
`ensure_png_tempfile()` for unrelated consumers. Keep SVG
geometry semantics in the mature vector parser, then allowlist only its two
stable no-shape diagnostics when the active source is a user upload. Return
structured source error codes so the frontend can translate them. Unknown
parser, worker, LUT, cache, filesystem, server-generated artwork, and geometry
failures keep their existing 5xx/409 behavior.

The supported-SVG contract also exposed real parser defects: transformed,
grouped, nested-viewport, object-bounding-box, compound, and `<use>`-referenced
`clipPath` geometry was accepted but silently ignored or miscomputed. Apply
referenced clip geometry in the vector parser while preserving viewBox,
length-percentage, overflow, fill/clip rule, and compound-path semantics.
Resolve user-space percentages against each reference viewport and avoid
reparsing the full document `<defs>` for every clip id.

**Tech Stack:** FastAPI, Pillow, React/TypeScript i18n, pytest, Vitest.

---

### Task 1: Lock the invalid-input and supported-SVG contracts

**Files:**
- Create: `tests/test_vector_input_validation_unit.py`
- Create: `tests/test_converter_source_validation_unit.py`
- Modify: `tests/test_converter_preview_unit.py`
- Modify: `tests/test_converter_generate_error_language_unit.py`

- [x] **Step 1: Add raster upload red tests**

Use supported raster and SVG filenames/MIME with invalid bytes and assert HTTP
422, fixed path-free structured details, worker non-invocation, and removal of
the temporary upload. Also prove a real image remains accepted when the MIME
is generic. Content sniffing may tolerate raster-to-raster extension mismatch
(for example PNG bytes named `.jpg`), but PNG bytes named `.svg` and SVG bytes
named `.png` must follow their declared converter path and return the
corresponding 422.

Mock a file-open failure and assert it stays an internal 500. This distinguishes
storage/filesystem failures from bytes that were opened successfully but could
not be decoded.

Mock Pillow's `Image.DecompressionBombError` without allocating a huge bitmap
and assert a fixed HTTP 413 `source_image_too_large` response. A small valid
image and a converted HEIC/RAW PNG path remain accepted.

- [x] **Step 2: Add SVG semantic classification red tests**

Cover an empty SVG, all-transparent/hidden shapes, malformed XML, a non-SVG XML
root, and a stroke-only document unsupported by the default Vector policy.
Malformed/root-invalid SVGs are rejected before the worker; valid SVGs with no
supported geometry are classified only after the mature parser. Assert the
known diagnostics map to structured HTTP 422 details and never expose parser
text or local paths.

- [x] **Step 3: Lock supported SVGs before changing classification**

Add focused parser guards for:

- a document with `viewBox` but no explicit width/height;
- nested and group transforms plus `clipPath`;
- `objectBoundingBox` under rotate/skew and a transformed clip definition;
- clip targets and clip children resolved through `href`/`xlink:href`/symbol;
- a legal compound path with a hole, including inherited `clip-rule`.

Each must still yield the expected bounds/area; the compound path must preserve
its interior hole. A merely non-empty result is insufficient because a parser
could ignore transforms/clipping or fill the hole. Existing large-SVG raster
and V1/V2 tests remain part of the focused gate.

- [x] **Step 4: Repair stale generate test doubles**

Update the affected error-language tests from `pool.submit` to the current
`pool.submit_timed` `(result, timing)` contract so their 422/500 assertions
exercise the real route rather than accidentally passing through an unused
mock.

### Task 2: Validate converter uploads before worker submission

**Files:**
- Create: `api/routers/converter/source_validation.py`
- Modify: `api/routers/converter/preview.py`
- Create: `tests/test_converter_source_validation_unit.py`
- Modify: `tests/test_converter_preview_unit.py`

- [x] **Step 1: Verify ordinary raster uploads after writing the temp file**

For PNG/JPEG/WebP/BMP/GIF/TIFF files produced by `ensure_png_tempfile`, open the
file first, then call `Image.open()` and `verify()` while that already-open
handle is in a context manager. Any `OSError` raised by the initial file-open
operation, including `FileNotFoundError` and `PermissionError`, propagates as an
internal failure. Only after that open succeeds do `UnidentifiedImageError`,
Pillow decode/verify `OSError`, or `ValueError` become the fixed
`source_image_unreadable` validation result. Do not change
`ensure_png_tempfile()` or its HEIC/HEIF/RAW consumers. Converted HEIC/RAW
`.png` outputs are safe to verify through the same content path when they enter
converter preview.

Within the decode/verify stage, locally promote
`Image.DecompressionBombWarning` and catch both it and
`Image.DecompressionBombError`, returning HTTP 413 with
`source_image_too_large`. Rewind and force `Image.load()` after `verify()` so a
real truncated JPEG cannot pass validation and fail later in the worker. Run
this complete decode via `asyncio.to_thread()` so the async endpoint does not
block unrelated requests. The test suite must prove an initial file-open
failure remains 500 rather than being mislabeled as bad user bytes.

- [x] **Step 2: Validate SVG document structure without duplicating geometry parsing**

Parse the uploaded SVG as XML and require an SVG root element. Return
`source_svg_invalid` for malformed XML, binary masquerades, and other XML
roots. Do not decide path visibility, transforms, clipping, or compound
geometry here; the vector engine remains authoritative for those semantics.

- [x] **Step 3: Adopt the validator only for the user upload**

Call it after upload persistence but before surface-artwork replacement and
worker submission. Existing preview cleanup must remove rejected temp files.
This prevents server-generated surface artwork from being mislabeled as a
user-input error.

### Task 3: Map only known SVG input diagnostics to actionable 422

**Files:**
- Modify: `api/routers/converter/common.py`
- Modify: `tests/test_converter_preview_unit.py`
- Modify: `tests/test_converter_generate_error_language_unit.py`

- [x] **Step 1: Define stable public codes and messages**

Add `source_image_unreadable`, `source_image_too_large`, `source_svg_invalid`,
`source_svg_no_renderable_geometry`, and `source_svg_too_complex` structured
detail contracts. The no-geometry message tells users to make geometry visible,
convert strokes and text to filled paths, or use High-Fidelity mode; the
complexity message tells users to simplify or flatten intersecting compound
paths; the SVG-invalid message tells users to re-export a valid SVG.

- [x] **Step 2: Extend the existing pipeline-validation allowlist**

Parse only the first non-empty status line and compare it exactly against the
fixed preview/generate wrappers around the vector engine's two no-shape
diagnostics. Apply the same exact-line rule to the existing Vector-requires-SVG
diagnostic. Do not use substring matching. Enable either mapping only when the
caller explicitly supplies all relevant context: user upload, active Vector
mode, matching `.svg`/non-`.svg` source, and no surface/server-generated
replacement.
Malformed documents are already rejected by the upload validator. Return fixed
structured details. Do not classify arbitrary `ValueError`, `OSError`,
`RuntimeError`, LUT errors, cached-session failures, filesystem failures, or
server-generated surface artwork.

- [x] **Step 3: Verify preview and generate boundary behavior**

Preview worker exceptions whose first line exactly matches an allowlisted
diagnostic and generate status messages for normal user sources return 422. The same diagnostic from a
surface-overlay/server-generated source stays 500. Unknown worker errors remain
fixed, path-free 500 responses. Run one real inline worker request with an
invalid SVG to prove the current string-wrapping path reaches the allowlist.

Add negative cases for a near-match diagnostic, Vector mode with a PNG source,
High-Fidelity mode with an SVG source, and surface-overlay artwork. All remain
500. Timeout remains 504.

### Task 4: Translate structured artwork guidance in the frontend

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `frontend/src/api/__tests__/client.test.ts`

- [x] **Step 1: Register all five structured error codes**

Map all five new codes to translation keys and add concise Chinese/English copy.
Keep the server message as a safe fallback for older clients.

- [x] **Step 2: Add language-specific client tests**

Assert every code renders both configured languages, uses the safe server
message as the fallback for unknown clients, and preserves the original
structured response detail for diagnostics.

### Task 5: Focused verification, clean review, and isolated commit

**Files:**
- Verify all files above

- [x] **Step 1: Run focused backend suites**

Run invalid-input, vector parser, converter preview/generate error-language,
API error, and logging governance tests. Include existing SVG rasterizer and
large-format compatibility tests rather than unrelated upload suites. The
legacy private loader in `test_vector_engine_unit.py` must not replace the
canonical `core.vector_engine` module during collection, so the vector and API
files can run together without order-dependent monkeypatch failures.

- [x] **Step 2: Run focused frontend tests through the project wrapper**

Use `python scripts/run_vitest.py run src/api/__tests__/client.test.ts` (the
wrapper already runs with `frontend/` as its working directory) and any
converter-store test affected by visible error normalization.

- [x] **Step 3: Run fast logging gate, UTF-8 scan, compile, and diff check**

Use `caplog` on rejected raster, malformed SVG, and no-geometry SVG paths.
Assert WARNING fields are actionable but contain no temporary path, upload
filename, raw parser text, or original file bytes.

- [x] **Step 4: Request independent clean review**

- [ ] **Step 5: Commit separately**

Commit message:

`fix(converter): return actionable errors for invalid artwork`
