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
