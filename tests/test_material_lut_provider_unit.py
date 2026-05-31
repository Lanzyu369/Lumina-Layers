"""Unit tests for the hot-path material/LUT data provider.
热路径耗材/LUT 数据提供者的单元测试。

Pins the Route B seam contract:

1. ``load_materials`` memoizes within a process so repeated loads of the same
   palette hit memory (one underlying loader call).
2. The memo is **self-invalidating** via the on-disk archive mtime: touching
   ``material.json`` shifts the fingerprint and forces a reload, which is how
   the main app stays fresh when MLS (a separate process) mutates the data.
3. ``load_solver_cache`` is a faithful pass-through to the wrapped fallback
   loader and remains monkeypatchable at the source module.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.material_lut_provider as provider


@pytest.fixture(autouse=True)
def _clear_memo():
    """Ensure each test starts and ends with an empty memo. (每个测试前后清空 memo)"""
    provider.clear_memo_caches()
    yield
    provider.clear_memo_caches()


def _write_material(root: Path, directory_name: str) -> None:
    """Create a minimal material archive directory on disk. (写入最小耗材档案目录)"""
    material_dir = root / directory_name
    material_dir.mkdir(parents=True, exist_ok=True)
    (material_dir / "material.json").write_text(
        json.dumps({"material_name": directory_name}), encoding="utf-8"
    )
    (material_dir / "stage_A_parameters.json").write_text("{}", encoding="utf-8")


class TestLoadMaterialsMemo:
    """``load_materials`` memoization + self-invalidation. (memo 与自失效)"""

    def test_repeated_load_hits_memo(self, tmp_path, monkeypatch):
        """Second load of the same palette reuses the memo (loader called once).
        相同调色板的第二次加载命中 memo（底层加载器只调用一次）。
        """
        _write_material(tmp_path, "red")
        calls: list[list[str]] = []

        def _fake_loader(names, *, materials_dir=None):
            calls.append(list(names))
            return [object() for _ in names]

        monkeypatch.setattr(
            provider._material_lut_synthesis, "load_multiple_materials", _fake_loader
        )

        first = provider.load_materials(["red"], materials_dir=str(tmp_path))
        second = provider.load_materials(["red"], materials_dir=str(tmp_path))

        assert first is second
        assert len(calls) == 1

    def test_use_cache_false_bypasses_memo(self, tmp_path, monkeypatch):
        """``use_cache=False`` forces a reload. (use_cache=False 强制重载)"""
        _write_material(tmp_path, "red")
        calls: list[list[str]] = []

        def _fake_loader(names, *, materials_dir=None):
            calls.append(list(names))
            return [object() for _ in names]

        monkeypatch.setattr(
            provider._material_lut_synthesis, "load_multiple_materials", _fake_loader
        )

        provider.load_materials(["red"], materials_dir=str(tmp_path))
        provider.load_materials(["red"], materials_dir=str(tmp_path), use_cache=False)
        assert len(calls) == 2

    def test_mtime_change_invalidates_memo(self, tmp_path, monkeypatch):
        """Touching material.json shifts the key and triggers a reload.
        改动 material.json 使键变化并触发重载（跨进程自失效）。
        """
        _write_material(tmp_path, "red")
        calls: list[list[str]] = []

        def _fake_loader(names, *, materials_dir=None):
            calls.append(list(names))
            return [object() for _ in names]

        monkeypatch.setattr(
            provider._material_lut_synthesis, "load_multiple_materials", _fake_loader
        )

        provider.load_materials(["red"], materials_dir=str(tmp_path))
        # Simulate an out-of-process edit by bumping the archive mtime forward.
        archive = tmp_path / "red" / "material.json"
        import os

        future = archive.stat().st_mtime + 100
        os.utime(archive, (future, future))

        provider.load_materials(["red"], materials_dir=str(tmp_path))
        assert len(calls) == 2

    def test_clear_memo_forces_reload(self, tmp_path, monkeypatch):
        """``clear_memo_caches`` drops the memo so the next load re-reads.
        ``clear_memo_caches`` 清空 memo，下次加载重新读取。
        """
        _write_material(tmp_path, "red")
        calls: list[list[str]] = []

        def _fake_loader(names, *, materials_dir=None):
            calls.append(list(names))
            return [object() for _ in names]

        monkeypatch.setattr(
            provider._material_lut_synthesis, "load_multiple_materials", _fake_loader
        )

        provider.load_materials(["red"], materials_dir=str(tmp_path))
        provider.clear_memo_caches()
        provider.load_materials(["red"], materials_dir=str(tmp_path))
        assert len(calls) == 2


class TestLoadSolverCachePassthrough:
    """``load_solver_cache`` faithfully delegates to the fallback loader.
    ``load_solver_cache`` 忠实委托给回退加载器。
    """

    def test_delegates_and_returns_tuple(self, monkeypatch):
        """Args are forwarded and the ``(cache, grid)`` tuple is returned as-is.
        参数透传，``(cache, grid)`` 元组原样返回。
        """
        captured: dict = {}

        def _fake_fallback(materials, layer_count, layer_height_mm, substrate, *, grid_resolution, cache_root=None):
            captured.update(
                materials=materials,
                layer_count=layer_count,
                layer_height_mm=layer_height_mm,
                substrate=substrate,
                grid_resolution=grid_resolution,
            )
            return ("CACHE", 256)

        monkeypatch.setattr(
            provider._material_cache,
            "load_material_solver_cache_with_fallback",
            _fake_fallback,
        )

        result = provider.load_solver_cache(
            ["m"], 5, 0.08, "white", grid_resolution=256
        )
        assert result == ("CACHE", 256)
        assert captured["layer_count"] == 5
        assert captured["substrate"] == "white"
        assert captured["grid_resolution"] == 256


class TestRemoteModeBypassesMemo:
    """In MLS remote mode ``load_materials`` must always fetch fresh.
    远程（MLS）模式下 ``load_materials`` 必须始终取新，不命中本地 memo。

    Regression for the stale-params bug: the local-mtime memo key is a
    constant in remote mode (the material files are absent locally → mtime
    0.0), so a memo would pin the first-fetched params forever and serve
    stale Beer-Lambert values after MLS edits the same directories. The
    provider therefore bypasses the memo entirely when MLS is enabled.
    陈旧参数回归：远程模式下本地 mtime memo 键恒定（本地无文件 → mtime 0.0），
    memo 会永久固定首次取到的参数。提供者在启用 MLS 时完全绕过 memo。
    """

    def test_remote_mode_fetches_every_call(self, monkeypatch):
        """Each load in remote mode triggers a fresh ``fetch_materials`` call.
        远程模式下每次加载都触发一次新的 ``fetch_materials``。
        """
        monkeypatch.setattr(provider, "_mls_enabled", lambda: True)

        calls: list[list[str]] = []

        def _fake_fetch(names):
            calls.append(list(names))
            # Mimic ``core.material_lut_remote.fetch_materials`` returning the
            # rebuilt materials list. (返回重建后的材料列表)
            return [object() for _ in names]

        import core.material_lut_remote as remote

        monkeypatch.setattr(remote, "fetch_materials", _fake_fetch)

        provider.load_materials(["red", "blue"])
        provider.load_materials(["red", "blue"])

        # Two calls → two fetches (no memo dedupe in remote mode).
        # 两次调用 → 两次取数（远程模式不去重）。
        assert len(calls) == 2

    def test_remote_mode_returns_only_materials_list(self, monkeypatch):
        """``load_materials`` returns the fetched materials list unchanged.
        ``load_materials`` 原样返回取到的材料列表。
        """
        monkeypatch.setattr(provider, "_mls_enabled", lambda: True)
        sentinel = [object(), object()]

        import core.material_lut_remote as remote

        monkeypatch.setattr(
            remote, "fetch_materials", lambda names: sentinel
        )

        result = provider.load_materials(["x", "y"])
        assert result is sentinel
