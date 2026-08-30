# lumina-svg-core

`lumina-svg-core` is an Apache-2.0, print-oriented native SVG geometry engine.
It uses a fixed LunaSVG/PlutoVG layout front end and Clipper2 integer polygon
kernel, then exposes immutable NumPy-compatible buffers through pybind11.

The package is developed temporarily inside the Lumina Studio workspace. Its
directory is deliberately self-contained so it can become an independent repository
without importing application, printer, mesh, or UI code.

Version 0.1 supports static solid fills, solid strokes, affine transforms,
fill rules, vector clips, and source-order occlusion. Ambiguous document
semantics return a stable whole-document unsupported result; no element is
silently dropped. SVG arc path commands, circles, ellipses, and rounded
rectangles also return `unsupported_arc` in 0.1 because LunaSVG's resolved
path currently exposes only a fixed cubic approximation rather than the
original arc parameters needed to honor Lumina's physical error budget.

## Build

```bash
python -m build --wheel
python -m pytest tests -q
```

The first release targets CPython 3.12 wheels for Windows amd64, macOS arm64
and x86_64, and manylinux x86_64.
