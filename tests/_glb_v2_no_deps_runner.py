"""Subprocess helper: simulate missing v2 deps, then run a sub-pytest.

Used by ``tests/test_glb_v2_kernel_unit.py::test_no_deps_subprocess_*`` to
verify both groups behave correctly even when ``rasterio.features`` /
``manifold3d`` cannot be imported. We can't simply uninstall the wheels in
the live venv; instead this helper installs a `sys.meta_path` finder that
*hard-blocks* those imports (`raise ModuleNotFoundError`), then runs the
test module under that constrained environment.

Invoked as ``python tests/_glb_v2_no_deps_runner.py``.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
import sys

# Ensure the repo root is on sys.path so ``core.pipeline`` is importable
# when this script is run directly.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


_BLOCKED = {"rasterio", "manifold3d"}


class _BlockingFinder(importlib.abc.MetaPathFinder):
    """Behave like 'this module is not installed'.

    ``find_spec`` returns None (which lets `importlib.util.find_spec` report
    the module as missing without raising), and we ALSO override the actual
    `import` machinery via the ``loader`` chain — but for ``find_spec``
    based probes (used by trimesh.util.has_module), returning None is
    enough.

    For ``import rasterio`` / ``import manifold3d`` to actually fail with
    ModuleNotFoundError (and not silently succeed via the real installed
    wheel), we need to physically remove the wheels from ``sys.path``
    *before* this finder runs. Easiest: drop the venv's site-packages from
    sys.path and re-add it minus the two wheels' locations. Since both
    wheels live alongside everything else in site-packages, the cleanest
    approach is to override sys.modules with a sentinel that raises on
    attribute access. We use a separate strategy: install a finder that
    returns None for find_spec (so importlib.util.find_spec returns None,
    matching the "not installed" surface) AND, in addition, write None
    into sys.modules pre-import so any `import rasterio` raises.
    """

    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".", 1)[0]
        if top in _BLOCKED:
            # Returning None tells importlib "I have no opinion" — which is
            # what an absent module produces. The actual import block comes
            # from the sys.modules[name] = None sentinel set in main().
            return None
        return None


def main() -> int:
    # Drop any cached module so a fresh import will hit the meta_path.
    for name in list(sys.modules):
        top = name.split(".", 1)[0]
        if top in _BLOCKED:
            del sys.modules[name]
    sys.meta_path.insert(0, _BlockingFinder())
    # Sentinel: setting sys.modules[name] = None makes ``import name`` raise
    # ModuleNotFoundError immediately, mimicking the wheel being absent.
    for name in ("rasterio", "rasterio.features", "manifold3d"):
        sys.modules[name] = None  # type: ignore[assignment]

    # Sanity probe: make sure imports really fail now.
    try:
        import rasterio.features  # noqa: F401
        print("ERROR: rasterio.features still importable", file=sys.stderr)
        return 99
    except (ModuleNotFoundError, ImportError):
        pass
    try:
        import manifold3d  # noqa: F401
        print("ERROR: manifold3d still importable", file=sys.stderr)
        return 99
    except (ModuleNotFoundError, ImportError):
        pass

    # Now run pytest on the v2 unit test module.
    import pytest as _pytest
    return _pytest.main([
        "tests/test_glb_v2_kernel_unit.py",
        "--no-header",
        "-q",
        "-p", "no:cacheprovider",
        "--rootdir", _REPO_ROOT,
    ])


if __name__ == "__main__":
    sys.exit(main())
