# Native SVG benchmark inputs and evidence

`supported_scale_fixture.svg` is generated entirely by
`scripts/build_native_svg_supported_fixture.py`. Its 32-by-32 grid contains
1,024 disjoint radial polygons and 65,536 contour vertices. The colors and
contours are analytic; no paths, colors or pixels are sampled from external
artwork. `supported_scale_fixture_provenance.json` records this workload as
`owned_synthetic_scale`.

Regenerate from the Lumina repository root:

```bash
python scripts/build_native_svg_supported_fixture.py \
  --manifest native/lumina-svg-core/benchmarks/supported_scale_fixture_provenance.json
```

Measure the standalone public call with the installed CPython 3.12 wheel:

```bash
python native/lumina-svg-core/tools/benchmark.py \
  --svg native/lumina-svg-core/benchmarks/supported_scale_fixture.svg \
  --target-width-mm 111 --tolerance-mm 0.02 --warm-runs 3 \
  --classification owned_synthetic_scale \
  --output native/lumina-svg-core/benchmarks/synthetic_manifest.json
```

Measure the complete Lumina `VectorAnalysis` entry point separately:

```bash
python scripts/benchmark_native_svg_analysis.py \
  --large-search-root repository=. \
  --output progress/native-svg-synthetic-benchmark.json
```

Both runners discard a warm-up and record at least three warm runs, native
stage timings, peak RSS, swap growth and output fingerprints. The complete
Lumina runner also measures `alpha_compositing_fixture.svg`. The existing
1.0-second standalone/complete median budget and 1.25-second complete p95
budget are unchanged.

Real artwork is optional caller input through `--source-proxy` or
`--real-r4c1`. Omitted inputs are explicitly recorded as unavailable; the
synthetic fixture is never relabeled as a real or private regression file.

`proxy_manifest.json` and `progress/native-svg-fast-path-benchmark.json`
retain historical measurements of the former artwork-derived fixture. That
fixture and its source illustration are no longer shipped. The new results
use separate files and a different classification; they do not replace the
historical baseline or establish a speed comparison against it.
