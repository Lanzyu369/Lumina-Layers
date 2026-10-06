# GEOS Dense-Buffer Local Runtime

This directory records the source patch, notice, and reproduction instructions
for Lumina's lossless dense-`MultiPolygon` buffer acceleration. [GEOS identifies
itself as LGPL software](https://libgeos.org/); the pinned 3.13.1 source and this
modification are distributed under LGPL-2.1-or-later.

The build tool clones official GEOS tag `3.13.1`, requires upstream commit
`431568d6e311e0bbfb057b4ec3d44d0d3ba3335f`, verifies the tracked patch digest,
and writes every generated file beneath `.scratch/geos_buffer_fast_proof`.
Generated libraries are not tracked by Git.

The library uses an isolated re-entrant GEOS C context and must not replace Shapely's
bundled GEOS or receive Shapely-owned geometry pointers. Lumina exchanges WKB
bytes only, enables the path only for proven dense inputs, and falls back to the
stock Shapely buffer whenever verification, loading, invocation, or output
validation fails. That fallback preserves the existing product result.

Build the runtime locally with:

```bash
python scripts/build_geos_buffer_fast_proof.py --rebuild
```

Activate the local runtime by setting `LUMINA_GEOS_BUFFER_FAST_MANIFEST` to
the absolute path of `.scratch/geos_buffer_fast_proof/build_manifest.json`.
The build directory retains the complete cloned source and upstream `COPYING`;
keep them together with this patch and the build script when distributing the
modified library. Activation remains optional and is not part of default
installation or CI.

Desktop/PyInstaller packaging deliberately does not enable or bundle this
modified library yet. Desktop continues to use stock Shapely until shared-library
replacement, notice, license, and corresponding-source distribution are handled
and verified for that package.
