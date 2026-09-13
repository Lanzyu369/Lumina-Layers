# Third-party notices

`lumina-svg-core` statically links the following pinned source dependencies.
Their original notices and complete license texts are retained in source and
binary distributions under `THIRD_PARTY_LICENSES/`.

## LunaSVG

- Maintained fork: https://github.com/Neroued/lunasvg
- Original upstream: https://github.com/sammycage/lunasvg
- Revision: `59690a23981489acc3f73b8db229ef57bb69c544`
- License: MIT
- Copyright: Samuel Ugochukwu and LunaSVG contributors

The Lumina fork applies only the versioned paint-command recorder patch stored
at `patches/lunasvg-paint-recorder.patch`.

## PlutoVG

- Source: the PlutoVG 1.3.2 tree bundled by the pinned LunaSVG revision
- LunaSVG tree object: `959f3ea36d77cdf981a00f169b8b545169cc2b71`
- License: MIT
- Copyright: PlutoVG contributors

## Clipper2

- Upstream: https://github.com/AngusJohnson/Clipper2
- Revision: `21ebba05db8894f0c7217ad35ea518080f324946`
- Release: Clipper2 2.0.1
- License: Boost Software License 1.0
- Copyright: Angus Johnson and Clipper2 contributors

Lumina applies a narrowly scoped, versioned patch stored at
`patches/clipper2-svg-miter-fallback.patch`. It changes the over-limit miter fallback
from square joins to bevel joins so the native kernel matches the SVG contract.
It also adds fixed execution caps around Clipper output-point and output-record
creation, intersection-node allocation, and every processed intersection;
these caps abort oversized operations without changing successful Boolean
geometry. The complete patched source diff is verified against the pinned
revision during every build.

## FreeType-derived stroker and raster files

PlutoVG contains FreeType-derived stroker and raster files with their own
file-level FreeType Project notices. The complete FreeType Project License is
distributed as `THIRD_PARTY_LICENSES/FreeType-Project.txt`.
Portions of this software are based in part on the work of the FreeType Team.

## stb single-file libraries

PlutoVG compiles the bundled stb image, image-write, and TrueType headers.
Their dual MIT/public-domain notice is distributed as
`THIRD_PARTY_LICENSES/stb.txt`.

## pybind11

- Source: https://github.com/pybind/pybind11
- Version: 3.1.0
- License: BSD-3-Clause
- Copyright: Wenzel Jakob and pybind11 contributors

The generated Python extension statically compiles pybind11 header code. Its
complete license is distributed as `THIRD_PARTY_LICENSES/pybind11.txt`.

## ChromaPrint3D hole selection

- Upstream: https://github.com/neroued/ChromaPrint3D
- Revision: `72faa6f76d2ee852299a35fb1f3d9ac2a5472039`
- Source: `core/src/vecgeo/vector_mesh_builder.cpp`
- Reused criteria: `UnionBaseContours` hole-area and `area / (0.5 * perimeter)`
  slit-width selection, plus `PathPerimeter` and the 100000 units/mm scale
- License: Apache License 2.0
- Copyright: 2025 neroued

`src/hole_compensation.cpp` prominently marks the adaptations. The optional
`_lumina_svg_compensation` extension unions all painted SVG regions once,
independently of color, into a Clipper2 PolyTree. It selects complete enclosed
voids with positive area at or below a positive area threshold, or a width
estimate at or below a positive width threshold. Zero disables each criterion.
After the union, shared segment intersections are noded and weakly simple rings
are split into simple cycles. Bounding-box indexes restore shell/hole hierarchy
without all-pairs document scans. Angular half-edge traversal and adjacent-face
winding propagation separate empty components when painted islands touch their
boundary; selection applies to each component independently. Painted islands are
subtracted from each void's area and included in its boundary perimeter. Filled
coverage is extracted from the remaining boundaries using the same face traversal,
without a per-hole document Boolean operation or a GEOS repair pass.

Unlike the upstream mesh workflow, this utility does not perform offsets,
simplification, small outer-component removal, per-color grouping, backing,
material assignment, or mesh repair. Input uses owned/copied float64 millimetre
coordinates rather than upstream float32 contour coordinates; both quantize the
input to the 100000 units/mm integer grid. New post-union intersections retain
shared fractional coordinates instead of being quantized a second time. No
positive-area component is removed by a printer-grid or dust-size filter.
This is a narrow reuse of selection criteria,
not a bit-for-bit recreation of the full upstream geometry pipeline. It links
the existing pinned Clipper2 dependency described above.

The complete upstream license is retained in
`THIRD_PARTY_LICENSES/ChromaPrint3D.txt`. No upstream `NOTICE` file was present
at the inspected revision.
