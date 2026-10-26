"""Persisted legacy sampling results must be rebuilt without touching user data."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from core import material_candidate_cache as candidate_cache
from core import material_lut_provider as provider
from core.material_color_solver import MaterialParams


def _palette() -> list[MaterialParams]:
    return [
        MaterialParams(
            name=name, directory_name=name.lower(),
            E=np.asarray(rgb, dtype=np.float64),
            k=np.full(3, 4.0), C0_white=np.ones(3),
            estimated_rgb=np.asarray(np.asarray(rgb) * 255, dtype=np.uint8),
        )
        for name, rgb in (
            ("Red", (0.8, 0.05, 0.05)), ("Blue", (0.05, 0.1, 0.8)),
            ("White", (0.95, 0.95, 0.95)), ("Black", (0.02, 0.02, 0.02)),
        )
    ]


@pytest.mark.parametrize("provider_name", [
    "load_solver_runtime", "load_dynamic_candidate_runtime",
])
def test_legacy_hybrid_v2_is_rebuilt_and_reusable_after_process_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_name: str,
) -> None:
    palette = _palette()
    cache_root = tmp_path / "calculated-data"
    config = candidate_cache.MaterialCandidateCacheConfig.persisted_for_budget(4096)
    healthy = candidate_cache.build_material_candidate_runtime(
        materials=palette, layer_count=10, layer_height_mm=0.08, config=config,
    )
    # Persist the actual old on-disk pair, with a depleted candidate payload.
    legacy = replace(
        healthy,
        candidate_recipes=healthy.candidate_recipes[:1],
        achieved_srgb=healthy.achieved_srgb[:1],
        achieved_lab=healthy.achieved_lab[:1],
        pinned_mask=healthy.pinned_mask[:1],
        metadata={**healthy.metadata, "cache_id": "legacy-hybrid-v2"},
    )
    with monkeypatch.context() as legacy_version:
        legacy_version.setattr(
            candidate_cache, "HYBRID_CANDIDATE_ALGORITHM_VERSION", "hybrid-v2",
        )
        legacy_path = candidate_cache.save_material_candidate_runtime(
            legacy, cache_root=cache_root,
        )
    legacy_meta = legacy_path.with_suffix(".meta.json")
    original_files = {
        legacy_path: legacy_path.read_bytes(), legacy_meta: legacy_meta.read_bytes(),
    }
    for relative in ("projects/user-project.json", "materials/user-material.json", "user-notes.txt"):
        sentinel = tmp_path / relative
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_bytes(b"must remain byte-identical\n")
        original_files[sentinel] = sentinel.read_bytes()

    assert candidate_cache.load_material_candidate_runtime_metadata(
        palette, 10, 0.08, candidate_budget=4096, cache_root=cache_root,
    ) is None
    assert candidate_cache.load_material_candidate_runtime(
        palette, 10, 0.08, candidate_budget=4096, cache_root=cache_root,
    ) is None

    rebuilt, grid = getattr(provider, provider_name)(
        palette, 10, 0.08, candidate_budget=4096, cache_root=cache_root,
    )
    assert grid == rebuilt.grid_resolution
    assert rebuilt.candidate_recipes.shape == (4096, 10)
    assert np.unique(rebuilt.candidate_recipes, axis=0).shape[0] > 4000
    assert np.all((rebuilt.candidate_recipes >= 0) & (rebuilt.candidate_recipes < 4))
    rebuilt_path = candidate_cache.save_material_candidate_runtime(
        rebuilt, cache_root=cache_root,
    )
    assert rebuilt_path != legacy_path
    reopened = candidate_cache.load_material_candidate_runtime(
        palette, 10, 0.08, candidate_budget=4096, cache_root=cache_root,
    )
    assert reopened is not None and reopened.cache_id == rebuilt.cache_id
    np.testing.assert_array_equal(reopened.candidate_recipes, rebuilt.candidate_recipes)

    palette_json = json.dumps([
        {
            "name": material.name, "directory_name": material.directory_name,
            "E": material.E.tolist(), "k": material.k.tolist(),
            "C0_white": material.C0_white.tolist(),
            "estimated_rgb": material.estimated_rgb.tolist(),
        }
        for material in palette
    ])
    completed = subprocess.run(
        [sys.executable, "-c", """
import json
import sys
import numpy as np
from core import material_lut_provider as provider
from core.material_color_solver import MaterialParams

materials = [MaterialParams(**{
    key: np.asarray(value) if isinstance(value, list) else value
    for key, value in record.items()
}) for record in json.loads(sys.argv[1])]
def forbidden_build(**_kwargs):
    raise AssertionError("fresh process must reuse the rebuilt cache")
provider.build_material_candidate_runtime = forbidden_build
runtime, _grid = getattr(provider, sys.argv[3])(
    materials, 10, 0.08, candidate_budget=4096, cache_root=sys.argv[2],
)
print(json.dumps({"cache_id": runtime.cache_id, "count": runtime.valid_cell_count}))
""", palette_json, str(cache_root), provider_name],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {
        "cache_id": rebuilt.cache_id, "count": 4096,
    }
    for path, original in original_files.items():
        assert path.read_bytes() == original, path
