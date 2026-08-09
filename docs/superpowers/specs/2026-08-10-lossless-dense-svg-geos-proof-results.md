# Lossless Dense SVG GEOS Proof Results

**Date:** 2026-08-10

**Decision:** **GO for product-integration planning**

**Scope:** the `+0.03 mm` mitred positive-buffer half of contour normalization only.

## Decision summary

The lookup-only GEOS 3.13.1 patch reduced the real `IMG_7254.svg` positive
buffer from **71.392526 s** to **3.765247 s** on the first acceptance run
(about **18.96x faster**). The output has an empty symmetric difference from
stock GEOS, identical polygon/hole counts, identical area and bounds, and the
same normalized-WKB SHA-256.

Three additional candidate runs took **3.693289 s**, **3.703978 s**, and
**3.698161 s**. Their median was **3.698161 s**, all three fingerprints were
identical, and their normalized-WKB SHA-256 matched the stock acceptance
result.

This is a GO for a separately reviewed production-integration plan. It is not
yet a claim that the complete SVG preview is below 30 seconds: parse,
occlusion clipping, the negative buffer, color matching, and mesh construction
remain outside this proof.

## Environment

| Field | Value |
| --- | --- |
| Machine | Apple M5, arm64 |
| OS | macOS 26.5.2 (25F84) |
| Python | 3.12.13 |
| Shapely | 2.1.2 |
| Stock GEOS | 3.13.1 |
| Proof GEOS | official `3.13.1`, commit `431568d6e311e0bbfb057b4ec3d44d0d3ba3335f` |
| Patch SHA-256 | `f0f0b940a25d11df50548dad4838ad8197588304b20e983274158d23c8da96c5` |
| Proof revision | `40b00b5e766259da3475c9ea35e3787c9f9d8328` |

GEOS was built in Release mode with tests, documentation, and `geosop`
disabled for the proof library. `GEOS_BUILD_DEVELOPER=OFF` was required because
AppleClang 21 reports a deprecation in GEOS 3.13.1's bundled JSON header; this
only removes upstream `-Werror` developer flags and does not change geometry
code or optimization settings.

## Patch boundary

The proof changes only two lookup costs:

1. `PolygonBuilder` skips creation of point-in-area locators when there are no
   free holes to place.
2. `BufferBuilder` uses a Y-interval index to select processed subgraphs before
   passing them to the unchanged `SubgraphDepthLocater`, restoring original
   processing order before the exact depth calculation.

Offset construction, global noding, precision, buffer parameters, coordinate
sequences, depth predicates, and polygon output rules are unchanged.

## Upstream GEOS verification

All 13 buffer-named tests in the pinned upstream tree passed:

- `unit-capi-GEOSBuffer`
- `unit-operation-buffer-BufferBuilder`
- `unit-operation-buffer-BufferOp`
- `unit-operation-buffer-BufferParameters`
- `unit-operation-buffer-OffsetCurve`
- `xml-general-TestBuffer`
- `xml-general-TestBufferMitredJoin`
- `xml-misc-Buffer-1`
- `xml-misc-Buffer-2`
- `xml-misc-TestBufferExternal-1`
- `xml-misc-TestBufferExternal-2`
- `xml-misc-safe-TestBufferJagged`
- `xml-misc-singlesidedbuffer`

Command result: **100% passed, 0 failed, 13 total**.

## Synthetic differential verification

Every case produced valid polygonal output, an empty symmetric difference,
matching component/hole counts, equal area and bounds, and identical repeated
candidate fingerprints.

| Case | Stock | Candidate runs | Result |
| --- | ---: | ---: | --- |
| 4,096 disjoint squares | 0.187960 s | 0.101796 s, 0.096006 s | PASS |
| interacting square chain | 0.001074 s | 0.001008 s, 0.000905 s | PASS |
| holes and nested shells | 0.000071 s | 0.000504 s, 0.000029 s | PASS |
| sharp mitres | 0.000037 s | 0.000042 s, 0.000013 s | PASS |
| tiny valid components | 0.004445 s | 0.002706 s, 0.002398 s | PASS |
| positive buffer merges inputs | 0.000045 s | 0.000047 s, 0.000019 s | PASS |

## Real sample: `IMG_7254.svg`, 300 mm

| Field | Result |
| --- | --- |
| Source SHA-256 | `575dd5ff34fd64997400e858851c40b39fe8ed42a677d9df7ef650cb75e58359` |
| Parsed / clipped shapes | 4,431 / 4,430 |
| Dense input | 74,162 components, 302,787 coordinates |
| Stock positive buffer | 71.392526 s |
| Candidate positive buffer | 3.765247 s |
| Speedup | 18.96x |
| Stock / candidate peak RSS | 811,712,512 / 811,712,512 bytes |
| Peak RSS ratio | 1.00x (limit 1.20x) |
| Output | valid `MultiPolygon`, 70,588 components, 0 holes |
| Output area | `21399.1227088384` |
| Output bounds | `[0.03220875, 0.25355388, 3500.1226276, 1999.74644612]` |
| Normalized-WKB SHA-256 | `0ff5ce3db88a71b5194376854d2eec6bef7b557f7d8b7cb6f455420fa6411802` for both |
| Symmetric difference | empty, area `0.0` |
| Acceptance | PASS |

Peak RSS uses the process high-water mark after each sequential backend. This
is conservative for detecting a candidate peak above stock: the candidate
value cannot drop below the already observed stock peak, and it did not raise
that peak.

### Candidate repeat verification

| Run | Time | Fingerprint |
| --- | ---: | --- |
| 1 | 3.693289 s | identical |
| 2 | 3.703978 s | identical |
| 3 | 3.698161 s | identical |
| Median | **3.698161 s** | stock normalized hash matched |

## Second supplied sample, 300 mm

`person_bd9869970839c02b0d0ac82e3756ccf1_20260725_074417_vector.svg` does not
exercise the dense-buffer hotspot. Its densest clipped material region has
only 9 components and 58 coordinates, despite the SVG containing 10,955
parsed/clipped shapes. The proof therefore ran it in explicit non-dense
regression mode.

| Field | Result |
| --- | --- |
| Source SHA-256 | `18e1684df9f3d069ec9eaa06738906c415a4c7efcdf9f2d9de3c13db8c445e34` |
| Stock / candidate positive buffer | 0.000425 s / 0.004049 s |
| Output | valid `MultiPolygon`, 8 components, 0 holes |
| Output area | `60.75718060453462` |
| Normalized-WKB SHA-256 | `236daed59649a68a84cccd1481a93ad02bea0a7a9b355377d5d690f3bd0cdd6c` for both |
| Symmetric difference | empty, area `0.0` |
| Interpretation | the user's wait is in another stage, not this buffer kernel |

The candidate's roughly 3.6 ms absolute overhead is the isolated C-library
context/WKB boundary used by the proof and is not a material end-to-end
regression. Production integration must avoid routing tiny geometry through an
external proof boundary unless that boundary is already the normal geometry
runtime.

## Gate decision

- Exact material-region geometry: **PASS**
- Candidate first acceptance at most 4 seconds: **PASS**
- Candidate three-run median at most 4 seconds: **PASS**
- Candidate peak RSS at most 1.20x stock: **PASS**
- Upstream and synthetic differential coverage: **PASS**

**Decision: GO for product-integration planning.** Production work must retain
the existing stock path as a safe fallback until packaged-library loading,
platform coverage, licensing notices, end-to-end SVG equivalence, and full
preview timings pass.
