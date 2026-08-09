# GEOS Dense-Buffer Proof

This directory records the source patch and reproduction instructions for a
lossless dense-`MultiPolygon` buffer experiment. GEOS is licensed under
LGPL-2.1-or-later; the proof retains the upstream license and version identity.

The build tool clones the pinned upstream source and writes every generated
file beneath `.scratch/geos_buffer_fast_proof`. Generated libraries are not
tracked.

The proof library uses an isolated re-entrant GEOS C context and must not replace Shapely's
bundled GEOS or receive Shapely-owned geometry pointers.

Run the proof build with:

```bash
python scripts/build_geos_buffer_fast_proof.py --rebuild
```

This is not a production integration. Product packaging, capability guards,
and fallback routing are permitted only after the semantic, performance, and
memory gates in the design document pass.
