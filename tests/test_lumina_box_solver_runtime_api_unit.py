"""Focused API contracts for Lumina Box solver runtime management."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from core.backed_gradient_material import (
    BACKED_GRADIENT_PROTOCOL_ID,
    component_from_parameters,
    reference_from_parameters,
)
from core.backed_gradient_smooth import (
    BackedGradientSmoothTransport,
    SPECTRAL_SMOOTH_MODEL_ID,
)
from core.km_xyz import (
    KM_XYZ_COLOR_BRIDGE_ID,
    KM_XYZ_MEASUREMENT_PROTOCOL_ID,
    KM_XYZ_MODEL_ID,
)
from core.material_candidate_cache import (
    MaterialCandidateCacheConfig,
    PREVIEW_SAFE_CANDIDATE_BUDGET,
    build_material_candidate_runtime,
)
from core.material_color_solver import ColorSuggestion, MaterialParams
from core.material_optical_runtime import MaterialMeasurementProtocolMismatchError
from core.pipeline._input_validation_common import MaterialArchiveProfileError


def _client() -> TestClient:
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app, base_url="http://localhost:8000")


def _km_material(name: str, revision: str) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.casefold(),
        E=np.zeros(3, dtype=np.float64),
        k=np.zeros(3, dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=np.asarray([128, 128, 128], dtype=np.uint8),
        optical_model_id=KM_XYZ_MODEL_ID,
        km_K=np.asarray([0.4, 0.6, 0.8], dtype=np.float64),
        km_S=np.asarray([1.2, 1.0, 0.7], dtype=np.float64),
        coefficient_unit="mm^-1",
        measurement_protocol_id=KM_XYZ_MEASUREMENT_PROTOCOL_ID,
        color_bridge_id=KM_XYZ_COLOR_BRIDGE_ID,
        archive_revision_id=revision,
    )


@pytest.fixture()
def km_materials() -> list[MaterialParams]:
    return [_km_material("A", "revision-a"), _km_material("B", "revision-b")]


@pytest.fixture()
def km_runtime(km_materials: list[MaterialParams]):
    return build_material_candidate_runtime(
        materials=km_materials,
        layer_count=5,
        layer_height_mm=0.08,
        config=MaterialCandidateCacheConfig(
            candidate_budget=8,
            candidate_pool_multiplier=1,
            build_worker_count=1,
        ),
    )


def _form(*, profile_kind: str = "lumina_box") -> dict[str, str]:
    return {
        "material_directory_names": json.dumps(["a", "b"]),
        "layer_count": "5",
        "layer_height_mm": "0.08",
        "substrate": "white",
        "candidate_budget": "8",
        "material_profile_kind": profile_kind,
    }


def _patch_profile_loader(
    monkeypatch: pytest.MonkeyPatch,
    materials: list[MaterialParams],
    *,
    seen: list[str] | None = None,
) -> None:
    def _load(_directory_names, *, profile_kind):
        if seen is not None:
            seen.append(str(profile_kind))
        return "lumina_box", materials

    monkeypatch.setattr(
        "api.routers.single_stage.load_and_validate_material_archive_profile",
        _load,
    )


def _assert_km_identity(payload: dict[str, object]) -> None:
    assert payload["profile_kind"] == "lumina_box"
    assert payload["optical_model"] == KM_XYZ_MODEL_ID
    assert payload["protocol_id"] == KM_XYZ_MEASUREMENT_PROTOCOL_ID
    assert payload["color_bridge_id"] == KM_XYZ_COLOR_BRIDGE_ID
    assert payload["archive_revision_ids"] == ["revision-a", "revision-b"]


def _one_suggestion() -> list[ColorSuggestion]:
    return [
        ColorSuggestion(
            matched_rgb=np.asarray([128, 128, 128], dtype=np.uint8),
            recipe=np.zeros(5, dtype=np.int32),
            delta_e=0.0,
        )
    ]


def _suggest_form(*, profile_kind: str = "lumina_box") -> dict[str, str]:
    return {
        **_form(profile_kind=profile_kind),
        "target_hex": "#808080",
        "top_k": "1",
        "min_spacing": "0",
        "max_combinations": "8",
    }


def test_lumina_profile_form_is_consumed_and_affine_build_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    km_materials: list[MaterialParams],
) -> None:
    seen: list[str] = []
    _patch_profile_loader(monkeypatch, km_materials, seen=seen)
    monkeypatch.setattr(
        "api.routers.single_stage.build_material_solver_cache",
        lambda *_args, **_kwargs: pytest.fail("affine build must not start"),
    )

    response = _client().post(
        "/api/extractor/material-solver-cache/build",
        data={**_form(), "grid_resolution": "64"},
    )

    assert seen == ["lumina_box"]
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == (
        "material_solver_cache_not_applicable"
    )
    assert "KM candidate runtime" in response.json()["detail"]["message"]


def test_runtime_profile_mismatch_is_422_before_metadata_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "api.routers.single_stage.load_and_validate_material_archive_profile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MaterialArchiveProfileError(
                "Selected material is 'stage_a', but material_profile_kind is "
                "'lumina_box'."
            )
        ),
    )
    monkeypatch.setattr(
        "api.routers.single_stage.load_material_candidate_runtime_metadata",
        lambda *_args, **_kwargs: pytest.fail("metadata lookup must not start"),
    )

    response = _client().post(
        "/api/extractor/material-solver-runtime/status",
        data=_form(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "material_profile_kind_mismatch"


def test_unknown_lumina_optical_contract_is_422_before_runtime_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "api.routers.single_stage.load_and_validate_material_archive_profile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MaterialMeasurementProtocolMismatchError(
                "Unsupported KM measurement protocol 'unknown/v1'"
            )
        ),
    )
    monkeypatch.setattr(
        "api.routers.single_stage.load_material_candidate_runtime_metadata",
        lambda *_args, **_kwargs: pytest.fail("runtime lookup must not start"),
    )

    response = _client().post(
        "/api/extractor/material-solver-runtime/status",
        data=_form(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == (
        "material_measurement_protocol_mismatch"
    )


def test_lumina_runtime_build_status_and_details_expose_contract_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    km_materials: list[MaterialParams],
    km_runtime,
) -> None:
    _patch_profile_loader(monkeypatch, km_materials)
    runtime_path = tmp_path / "km-runtime.npz"
    runtime_path.write_bytes(b"runtime")
    metadata_record = SimpleNamespace(
        metadata=km_runtime.metadata,
        cache_file_path=runtime_path,
        cache_file_size_bytes=runtime_path.stat().st_size,
    )

    monkeypatch.setattr(
        "api.routers.single_stage.load_material_candidate_runtime_metadata",
        lambda *_args, **_kwargs: metadata_record,
    )
    status = _client().post(
        "/api/extractor/material-solver-runtime/status",
        data=_form(),
    )
    assert status.status_code == 200, status.text
    _assert_km_identity(status.json())
    _assert_km_identity(status.json()["entry"])
    assert status.json()["entry"]["palette_hash"] == km_runtime.cache_id

    build = _client().post(
        "/api/extractor/material-solver-runtime/build",
        data=_form(),
    )
    assert build.status_code == 200, build.text
    _assert_km_identity(build.json()["entry"])
    assert build.json()["entry"]["palette_hash"] == km_runtime.cache_id

    monkeypatch.setattr(
        "api.routers.single_stage.load_material_candidate_runtime",
        lambda *_args, **_kwargs: km_runtime,
    )
    details = _client().post(
        "/api/extractor/material-solver-runtime/details",
        data={**_form(), "max_points": "128"},
    )
    assert details.status_code == 200, details.text
    _assert_km_identity(details.json())
    assert details.json()["palette_hash"] == km_runtime.cache_id


def test_lumina_suggestion_prefers_runtime_and_live_fallback_is_not_mitm(
    monkeypatch: pytest.MonkeyPatch,
    km_materials: list[MaterialParams],
    km_runtime,
) -> None:
    _patch_profile_loader(monkeypatch, km_materials)
    monkeypatch.setattr(
        "api.routers.single_stage.load_material_solver_cache",
        lambda *_args, **_kwargs: pytest.fail(
            "Lumina Box must not probe the affine solver cache"
        ),
    )
    monkeypatch.setattr(
        "api.routers.single_stage.load_persisted_candidate_runtime_with_fallback",
        lambda *_args, **_kwargs: km_runtime,
    )
    request = {
        **_form(),
        "target_hex": "#808080",
        "top_k": "3",
        "min_spacing": "0",
    }
    runtime_response = _client().post(
        "/api/extractor/material-solver-cache/suggest-colors",
        data=request,
    )
    assert runtime_response.status_code == 200, runtime_response.text
    assert runtime_response.json()["source"] == "runtime"
    assert runtime_response.json()["profile_kind"] == "lumina_box"
    assert runtime_response.json()["suggestions"]
    assert np.isfinite(runtime_response.json()["suggestions"][0]["delta_e"])

    monkeypatch.setattr(
        "api.routers.single_stage.load_persisted_candidate_runtime_with_fallback",
        lambda *_args, **_kwargs: None,
    )
    live_response = _client().post(
        "/api/extractor/material-solver-cache/suggest-colors",
        data=request,
    )
    assert live_response.status_code == 200, live_response.text
    assert live_response.json()["source"] == "km_live"
    assert "MITM" not in live_response.json()["message"]


def test_v3_live_suggestion_uses_the_real_builder_with_the_preview_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = BackedGradientSmoothTransport(
        {
            "R": (0., 0., -2., -3., 0., 1., .7),
            "W": (-6., 0., 0., 0., .7),
            "K": (2., -4., 0., .5),
        },
        {"W": (96., 96., 96.), "K": (.1, .1, .1)},
        fitted_materials=("R", "W", "K"),
    )
    parameters = model.to_parameters()
    reference = reference_from_parameters(parameters)
    materials = [
        MaterialParams(
            name=symbol, directory_name=f"test/{symbol}",
            E=np.ones(3), k=np.zeros(3), C0_white=np.ones(3),
            estimated_rgb=np.asarray([128, 128, 128], dtype=np.uint8),
            optical_model_id=SPECTRAL_SMOOTH_MODEL_ID,
            measurement_protocol_id=BACKED_GRADIENT_PROTOCOL_ID,
            color_bridge_id=KM_XYZ_COLOR_BRIDGE_ID,
            backed_gradient_component=component_from_parameters(parameters, symbol),
            backed_gradient_reference=reference,
        )
        for symbol in ("R", "W")
    ]
    _patch_profile_loader(monkeypatch, materials)
    monkeypatch.setattr(
        "api.routers.single_stage.load_persisted_candidate_runtime_with_fallback",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "core.material_color_solver._compute_material_affines",
        lambda *_args, **_kwargs: pytest.fail("v3 must not enter MITM"),
    )
    built_runtimes = []

    def _record_real_build(**kwargs):
        config = kwargs["config"]
        assert config.candidate_budget == PREVIEW_SAFE_CANDIDATE_BUDGET
        assert config.candidate_pool_multiplier == 1
        assert config.enable_inverse_refinement is False
        runtime = build_material_candidate_runtime(**kwargs)
        built_runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(
        "core.material_candidate_cache.build_material_candidate_runtime",
        _record_real_build,
    )
    response = _client().post(
        "/api/extractor/material-solver-cache/suggest-colors",
        data={**_suggest_form(), "material_directory_names": json.dumps(["test/R", "test/W"])},
    )

    assert response.status_code == 200, response.text
    assert response.json()["source"] == "km_live"
    assert response.json()["suggestions"]
    assert len(built_runtimes) == 1
    runtime = built_runtimes[0]
    assert runtime.optical_model_id == SPECTRAL_SMOOTH_MODEL_ID
    assert 0 < runtime.valid_cell_count <= PREVIEW_SAFE_CANDIDATE_BUDGET
    assert runtime.achieved_xyz is not None
    assert np.all(np.isfinite(runtime.achieved_xyz))
    assert np.isfinite(response.json()["suggestions"][0]["delta_e"])


def test_lumina_live_suggest_rejects_concurrent_builder_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
    km_materials: list[MaterialParams],
) -> None:
    _patch_profile_loader(monkeypatch, km_materials)
    monkeypatch.setattr(
        "api.routers.single_stage.load_persisted_candidate_runtime_with_fallback",
        lambda *_args, **_kwargs: None,
    )
    entered = threading.Barrier(2)
    release = threading.Barrier(2)
    call_guard = threading.Lock()
    builder_calls = 0

    def _blocking_builder(*_args, **_kwargs):
        nonlocal builder_calls
        with call_guard:
            builder_calls += 1
            call_number = builder_calls
        if call_number == 1:
            entered.wait(timeout=5)
            release.wait(timeout=5)
        return _one_suggestion()

    monkeypatch.setattr(
        "api.routers.single_stage.suggest_colors_for_target",
        _blocking_builder,
    )
    first_client = _client()
    second_client = _client()
    with first_client, second_client, ThreadPoolExecutor(max_workers=1) as pool:
        first_future = pool.submit(
            first_client.post,
            "/api/extractor/material-solver-cache/suggest-colors",
            data=_suggest_form(),
        )
        entered.wait(timeout=5)
        try:
            second_response = second_client.post(
                "/api/extractor/material-solver-cache/suggest-colors",
                data=_suggest_form(),
            )
        finally:
            release.wait(timeout=5)
        first_response = first_future.result(timeout=5)

    assert first_response.status_code == 200, first_response.text
    assert second_response.status_code == 409, second_response.text
    assert "already running" in second_response.json()["detail"]
    assert "retry" in second_response.json()["detail"].lower()
    assert builder_calls == 1


def test_lumina_live_suggest_releases_build_gate_after_exception(
    monkeypatch: pytest.MonkeyPatch,
    km_materials: list[MaterialParams],
) -> None:
    _patch_profile_loader(monkeypatch, km_materials)
    monkeypatch.setattr(
        "api.routers.single_stage.load_persisted_candidate_runtime_with_fallback",
        lambda *_args, **_kwargs: None,
    )
    builder_calls = 0

    def _flaky_builder(*_args, **_kwargs):
        nonlocal builder_calls
        builder_calls += 1
        if builder_calls == 1:
            raise ValueError("controlled KM build failure")
        return _one_suggestion()

    monkeypatch.setattr(
        "api.routers.single_stage.suggest_colors_for_target",
        _flaky_builder,
    )
    client = _client()
    first_response = client.post(
        "/api/extractor/material-solver-cache/suggest-colors",
        data=_suggest_form(),
    )
    second_response = client.post(
        "/api/extractor/material-solver-cache/suggest-colors",
        data=_suggest_form(),
    )

    assert first_response.status_code == 422
    assert second_response.status_code == 200, second_response.text
    assert second_response.json()["source"] == "km_live"
    assert builder_calls == 2


def test_stage_a_and_persisted_runtime_suggestions_bypass_live_build_gate(
    monkeypatch: pytest.MonkeyPatch,
    km_materials: list[MaterialParams],
    km_runtime,
) -> None:
    from api.routers import single_stage

    _patch_profile_loader(monkeypatch, km_materials)
    monkeypatch.setattr(
        single_stage,
        "load_persisted_candidate_runtime_with_fallback",
        lambda *_args, **_kwargs: km_runtime,
    )
    monkeypatch.setattr(
        single_stage,
        "suggest_colors_for_target",
        lambda *_args, **_kwargs: pytest.fail(
            "persisted runtime hit must not start a live builder"
        ),
    )
    assert single_stage._RUNTIME_BUILD_GLOBAL_SEMAPHORE.acquire(blocking=False)
    try:
        runtime_response = _client().post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data=_suggest_form(),
        )
        assert runtime_response.status_code == 200, runtime_response.text
        assert runtime_response.json()["source"] == "runtime"

        stage_a_materials = [
            MaterialParams(
                name=name,
                directory_name=name.casefold(),
                E=np.zeros(3, dtype=np.float64),
                k=np.zeros(3, dtype=np.float64),
                C0_white=np.ones(3, dtype=np.float64),
                estimated_rgb=np.asarray([128, 128, 128], dtype=np.uint8),
            )
            for name in ("StageA-A", "StageA-B")
        ]
        monkeypatch.setattr(
            single_stage,
            "load_and_validate_material_archive_profile",
            lambda _names, *, profile_kind: ("stage_a", stage_a_materials),
        )
        monkeypatch.setattr(
            single_stage,
            "load_material_solver_cache",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            single_stage,
            "load_material_candidate_runtime",
            lambda *_args, **_kwargs: None,
        )
        stage_a_builder_calls = 0

        def _stage_a_builder(*_args, **_kwargs):
            nonlocal stage_a_builder_calls
            stage_a_builder_calls += 1
            return _one_suggestion()

        monkeypatch.setattr(
            single_stage,
            "suggest_colors_for_target",
            _stage_a_builder,
        )
        stage_a_response = _client().post(
            "/api/extractor/material-solver-cache/suggest-colors",
            data=_suggest_form(profile_kind="stage_a"),
        )
        assert stage_a_response.status_code == 200, stage_a_response.text
        assert stage_a_response.json()["source"] == "mitm"
        assert stage_a_builder_calls == 1
    finally:
        single_stage._RUNTIME_BUILD_GLOBAL_SEMAPHORE.release()
