# Test image sources

The former `benchmark.jpg` and `benchmark.svg` illustrations were removed
because no original artist or asset-license evidence was available. The
native benchmark fixture no longer contains paths or colors extracted from
that SVG.

Current raster benchmark defaults use the project's synthetic color-block
input `LUT_Stress_Test_HD.png`. The native SVG scale fixture is generated
from analytic radial polygons by
`scripts/build_native_svg_supported_fixture.py`; its provenance is recorded
under `native/lumina-svg-core/benchmarks/`.

Previously recorded performance reports keep their original input names and
measurements as historical evidence. Synthetic-workload results use separate
report files and are not a replacement for a historical performance baseline.
Removing these current files does not remove their copies from Git history.
