# Lossless Dense SVG First-Run Results

> Deployment update (2026-10-06): Docker support and the public-test bypass
> are retired. This historical record preserves earlier implementation and
> validation evidence; use [Runtime support](../../runtime-support.md) for current behavior.
> 部署更新：Docker 支持及公网测试访问旁路已移除；本文保留历史实现与验证记录，当前运行方式以上述说明为准。

**Date:** 2026-08-10

**Decision:** **SHIP the proven exact paths; reject geometry-changing shortcuts.**

## Acceptance boundary

The optimization may change internal scheduling and intermediate storage only.
For every material slot it must preserve the existing production mesh vertex
and face stream, which is stricter than the product requirement of preserving
material regions, layer order, final solid surfaces, holes, and dimensions.

The two user-supplied SVGs were measured at a target width of 300 mm with the
same verified GEOS runtime and native surface-validation settings used by the
server Docker image.

## End-to-end cold results

| Sample | Analyze | Build | Analyze + build |
| --- | ---: | ---: | ---: |
| `IMG_7254.svg` | 23.919 s | 34.042 s | **57.961 s** |
| `person_bd9869970839c02b0d0ac82e3756ccf1_20260725_074417_vector.svg` | 18.358 s | 23.171 s | **41.529 s** |

The `IMG_7254.svg` cold run spent 7.770 s parsing, 14.438 s in clipping plus
post-clip normalization/splitting, 0.831 s matching colors, 30.869 s building
the color meshes, and 3.157 s assembling the scene. The historical incident
log recorded 41 minutes 48 seconds for the pathological request, so the real
sample is now bounded in roughly one minute on this machine rather than tens
of minutes.

The aggressive 30-second end-to-end target was not reached. Exact global
Clipper unions still dominate mesh construction. Spatial partitioning could
make that stage much faster, but differential tests changed hundreds of
polygon fingerprints by approximately one coordinate-grid unit, so it was
rejected.

## Proven improvements

### Dense contour normalization

The existing product close operation (`+0.03 mm`, then `-0.03 mm`) fell from
176.221 s to a three-run median of 4.813 s. All runs retained 72,045
components, zero holes, identical bounds, an empty symmetric difference, and
normalized-WKB SHA-256
`0eeaa95c1511f39b474a953284098a60b541c11f99835febc948ef461989df33`.

### Occlusion and silhouette scheduling

On `IMG_7254.svg`, running the independent silhouette union within the same
four-thread budget as exact occlusion clipping reduced the combined operation
from 10.926 s to 8.307 s. The clipped-shape stream remained
`ad4b01bbab7f4b2532b6d42c2b175e21a6c332981724ad7ff2c7a0cd6746d59b`,
and the silhouette remained
`9c564fe555ed002e2cc8210d17cf769b1371ae8061036268a53928c79c424f14`.

### Native rejected-mesh retry and validation

The largest native groups previously performed the same exact union twice:
the primary extrusion rejected a huge combined mesh, then Python requested the
already-computed merged polygons again before retrying 151,985 independent
polygons. The extension now returns and retries that first exact result in the
same call, and performs the unchanged surface-area acceptance gate in C++.

For `IMG_7254.svg`, production-mode build time fell from 53.735 s to a best
observed 32.238 s (40.0% lower). Python surface validation fell from 36.089 s
to zero while still checking 152,027 meshes, with zero surface rejects. A
later cold end-to-end run built in 34.042 s under normal timing variation.

## Strict output identity

The optimized and pre-change production-native builds produced identical
SHA-256 values for all five final material meshes.

### `IMG_7254.svg`

| Material | Mesh stream SHA-256 |
| --- | --- |
| Blue | `760f7b590c09b79037b3f2a397855119d10457c031f75e80b399aab542d6df4a` |
| Board | `81769ad483359da9618b2f34a64125d2f549480696ac3d04dfb2889862b3ad83` |
| Red | `15db21675c4bcde0c2f384e5c4bd73ed83548126f6117c14af396eb42ea4b2e6` |
| White | `f47e900453db24a77e57daa978711074bcdd7a104bc1731eab35e888c103e8d3` |
| Yellow | `eb0beadd9d956eb1d50164901b260b2b073a4577e223414d61efc2a2c6bc2f7a` |

### `person...svg`

| Material | Mesh stream SHA-256 |
| --- | --- |
| Blue | `44bf1febecf29fe9df46ff3050978876eba250846fa98440880282902bcd0611` |
| Board | `cb68c34f8b0203bd263ca454f5ced068608d9ee708a6fd3fc27aecae78966f0f` |
| Red | `f952bb23e8be10d768dd4db9469c55767d3721c49c20ee40cd2be128d144b449` |
| White | `a7b41000194b33b61ac25169a3360f1d660d24f362fd446aefefafa1a74e149d` |
| Yellow | `b57d2af58a399533a2cb78c5a8330bf3576abea4ecd7ddd26640259ee48da2de` |

These hashes cover final vertices and faces after scene assembly. They confirm
that the optimization does not change color-material geometry, holes,
dimensions, layer placement, triangulation, or even internal array order for
the supplied samples.

## Rejected experiments

- Spatial/component partitioning was faster but changed exact polygon bytes
  and was rejected.
- Splitting all native groups into independent tasks increased memory-bandwidth
  contention and slowed the build to 44.080 s.
- Segment-coalescing 151,985 retry outputs preserved hashes but slowed the
  build to 34.309-42.820 s, so the simpler direct records were retained.

The fallback path remains active for missing capabilities, malformed native
records, empty meshes, surface mismatches, and native exceptions.
