# Modified GEOS notice

Lumina Studio's server Docker image contains a dynamically loaded modified build
of GEOS 3.13.1.

- Upstream project: https://libgeos.org/
- Upstream source: https://github.com/libgeos/geos.git
- Pinned commit: `431568d6e311e0bbfb057b4ec3d44d0d3ba3335f`
- License: LGPL-2.1-or-later; see the upstream `COPYING` file and
  https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- Lumina modification:
  `patches/geos-3.13.1-buffer-subgraph-index.patch`

The Docker image retains the complete pinned GEOS source tree, upstream license,
Lumina patch, and reproducible build script under `/app`. The modification
indexes buffer-subgraph candidate lookup while retaining the existing depth
locator, ordering, noding, coordinate construction, and public C API behavior.

This notice describes the engineering distribution boundary and is not legal
advice.
