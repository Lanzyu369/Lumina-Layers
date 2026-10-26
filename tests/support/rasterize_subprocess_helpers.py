"""Top-level subprocess entry points for tile-cover rasterize tests.

These helpers must live in their own importable module so the spawn-based
``multiprocessing.Process`` can pickle them by qualified name. Tests pass
them in via the ``_entry`` keyword on
``_run_rasterize_canvas_in_subprocess`` to exercise the hard-kill /
crash / quick-success paths without booting resvg.
"""

from __future__ import annotations

import time

import numpy as np


def hang_forever_entry(
    _svg_path: str,
    _target_width_mm: float,
    _pixels_per_mm: float,
    _output_npy_path: str,
) -> None:
    """Block long enough that any reasonable timeout triggers.

    The parent ``terminate``/``kill``s us; we never write the output file.
    使用 ``time.sleep`` 而非 busy-loop，让 SIGTERM 能立刻抢先返回。
    """
    time.sleep(120.0)


def crash_immediately_entry(
    _svg_path: str,
    _target_width_mm: float,
    _pixels_per_mm: float,
    _output_npy_path: str,
) -> None:
    """Raise so the subprocess exits with a non-zero exitcode.

    ``_run_rasterize_canvas_in_subprocess`` must surface this as a
    ``RuntimeError`` to the caller.
    """
    raise RuntimeError("synthetic rasterize crash")


def write_solid_canvas_entry(
    _svg_path: str,
    _target_width_mm: float,
    _pixels_per_mm: float,
    output_npy_path: str,
) -> None:
    """Write a 32×32 solid-red RGBA canvas and exit cleanly.

    Used to assert the success path: parent reads the array back, caches
    it, and returns it.
    """
    arr = np.zeros((32, 32, 4), dtype=np.uint8)
    arr[..., 0] = 220
    arr[..., 3] = 255
    np.save(output_npy_path, arr)
