# Modified GEOS notice

Lumina Studio's optional local dense-buffer runtime dynamically loads a
modified build of GEOS 3.13.1.

- Upstream project: https://libgeos.org/
- Upstream source: https://github.com/libgeos/geos.git
- Pinned commit: `431568d6e311e0bbfb057b4ec3d44d0d3ba3335f`
- License: LGPL-2.1-or-later; see the upstream `COPYING` file and
  https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- Lumina modification:
  `patches/geos-3.13.1-buffer-subgraph-index.patch`

The local build retains the complete pinned GEOS source tree and upstream
license under `.scratch/geos_buffer_fast_proof`. Keep that source, the Lumina
patch and the reproducible build script with any redistributed library. The
modification indexes buffer-subgraph candidate lookup while retaining the existing depth
locator, ordering, noding, coordinate construction, and public C API behavior.

This notice describes the engineering distribution boundary and is not legal
advice.
