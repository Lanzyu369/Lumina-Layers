"""Worker material output is read only when complete, and fails closed.

子进程材质输出只在写完后被读取，且损坏时按失败处理而非当作空结果。

A half-written ``npz`` must never be mistaken for "this material has no mesh":
the latter silently drops geometry, the former must abort the task.
半写入的 ``npz`` 绝不能被当成「该材质没有网格」——后者会静默丢失几何，前者必须让任务失败。
"""

from __future__ import annotations

from pathlib import Path
import zipfile

import numpy as np
import pytest

from core.vector_material_meshing import _read_material_result


def _write_complete_output(path: Path, *, present: bool = True) -> None:
    if not present:
        np.savez(path, present=np.array(False))
        return
    np.savez(
        path,
        present=np.array(True),
        vertices=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        faces=np.asarray([[0, 1, 2]], dtype=np.int64),
        metadata=np.array("{}"),
    )


def test_complete_output_is_read_as_a_mesh(tmp_path: Path) -> None:
    """A complete worker file round-trips into one mesh."""

    target = tmp_path / "complete.npz"
    _write_complete_output(target)

    mesh = _read_material_result(str(target))

    assert mesh is not None
    assert len(mesh.faces) == 1


def test_explicitly_empty_output_reports_no_mesh(tmp_path: Path) -> None:
    """The documented "no mesh" case stays distinguishable from corruption."""

    target = tmp_path / "empty-material.npz"
    _write_complete_output(target, present=False)

    assert _read_material_result(str(target)) is None


def test_truncated_output_raises_instead_of_dropping_geometry(
    tmp_path: Path,
) -> None:
    """A partially written worker file aborts the task, it is never read."""

    complete = tmp_path / "complete.npz"
    _write_complete_output(complete)
    raw = complete.read_bytes()
    truncated = tmp_path / "truncated.npz"
    truncated.write_bytes(raw[: len(raw) // 2])

    with pytest.raises((zipfile.BadZipFile, EOFError, ValueError, OSError)):
        _read_material_result(str(truncated))


def test_missing_output_raises_instead_of_dropping_geometry(
    tmp_path: Path,
) -> None:
    """A worker that never produced its file must not look like an empty mesh."""

    with pytest.raises((FileNotFoundError, OSError, ValueError)):
        _read_material_result(str(tmp_path / "absent.npz"))
