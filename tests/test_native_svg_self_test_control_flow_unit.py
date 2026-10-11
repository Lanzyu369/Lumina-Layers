"""Behavioral checks for the packaged native SVG self-test gate."""

from types import SimpleNamespace
import json
import sys

import pytest
from shapely.geometry import GeometryCollection, Polygon, box


def _result(*, silhouette=None):
    geometry = box(0, 0, 10, 5)
    return SimpleNamespace(
        geometry_backend="native",
        shape_data=[{"poly": geometry, "color": (18, 52, 86), "draw_order": 0}],
        clipped_shapes=[{
            "geometry": geometry,
            "color": (18, 52, 86),
            "draw_order": 0,
        }],
        silhouette=geometry if silhouette is None else silhouette,
        scale_factor=2.0,
        bbox=(0.0, 0.0, 10.0, 5.0),
        svg_coordinate_domain=SimpleNamespace(version=1),
        native_version="0.3.0",
        native_schema_version=4,
    )


def _install_self_test_inputs(
    monkeypatch,
    *,
    result=None,
    include_canonicalizer=True,
    include_projection=True,
    canonical_area=500.0,
    projected=None,
):
    calls = {"canonical": 0, "project": 0}

    def canonicalize(_regions):
        calls["canonical"] += 1
        if canonical_area == 0.0:
            return [[]]
        return [[([(0, 0), (1, 0), (0, 1000), (0, 0)], [])]]

    def project(*_args, **_kwargs):
        calls["project"] += 1
        return [box(0, 0, 1, 1) if projected is None else projected]

    package = SimpleNamespace()
    if include_canonicalizer:
        package.canonicalize_grid_regions = canonicalize
    if include_projection:
        package.project_regions_to_grid = lambda *_args, **_kwargs: []
    monkeypatch.setitem(sys.modules, "lumina_svg_core", package)
    monkeypatch.setattr(
        "core.native_svg_adapter.analyze_native_svg",
        lambda *_args, **_kwargs: _result() if result is None else result,
    )
    monkeypatch.setattr(
        "core.native_svg_adapter.native_build_identity",
        lambda: "test-native-build-sha",
    )
    monkeypatch.setattr("core.svg_coordinate_domain.project_print_regions", project)
    return calls


def test_native_self_test_rejects_missing_canonicalizer(monkeypatch):
    import api_server

    calls = _install_self_test_inputs(monkeypatch, include_canonicalizer=False)
    with pytest.raises(api_server.NativeSvgSelfTestError) as error:
        api_server._native_svg_self_test_payload("fixture.svg")
    assert error.value.reason_code == "native_grid_canonicalization_unavailable"
    assert calls == {"canonical": 0, "project": 0}


def test_native_self_test_rejects_missing_projection_api(monkeypatch):
    import api_server

    calls = _install_self_test_inputs(monkeypatch, include_projection=False)
    with pytest.raises(api_server.NativeSvgSelfTestError) as error:
        api_server._native_svg_self_test_payload("fixture.svg")
    assert error.value.reason_code == "native_coordinate_projection_unavailable"
    assert calls == {"canonical": 0, "project": 0}


def test_native_self_test_rejects_empty_canonical_probe(monkeypatch):
    import api_server

    calls = _install_self_test_inputs(monkeypatch, canonical_area=0.0)
    with pytest.raises(api_server.NativeSvgSelfTestError) as error:
        api_server._native_svg_self_test_payload("fixture.svg")
    assert error.value.reason_code == "native_grid_canonicalization_lost_positive_area"
    assert calls == {"canonical": 1, "project": 0}


def test_native_self_test_rejects_invalid_projected_regions(monkeypatch):
    import api_server

    invalid = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    assert not invalid.is_valid
    calls = _install_self_test_inputs(monkeypatch, projected=invalid)
    with pytest.raises(api_server.NativeSvgSelfTestError) as error:
        api_server._native_svg_self_test_payload("fixture.svg")
    assert error.value.reason_code == "invalid_print_domain_geometry"
    assert calls == {"canonical": 1, "project": 1}


def test_native_self_test_success_executes_both_new_checks_once(monkeypatch):
    import api_server

    calls = _install_self_test_inputs(monkeypatch)
    payload = api_server._native_svg_self_test_payload("fixture.svg")
    assert payload["status"] == "ok"
    assert payload["native_build_sha256"] == "test-native-build-sha"
    assert calls == {"canonical": 1, "project": 1}


def test_empty_silhouette_keeps_existing_failure_without_running_domain_checks(
    monkeypatch,
):
    import api_server

    calls = _install_self_test_inputs(
        monkeypatch,
        result=_result(silhouette=GeometryCollection()),
    )
    with pytest.raises(api_server.NativeSvgSelfTestError) as error:
        api_server._native_svg_self_test_payload("fixture.svg")
    assert error.value.reason_code == "empty_silhouette"
    assert calls == {"canonical": 0, "project": 0}


def test_cli_reports_domain_self_test_failure_as_nonzero_json(
    monkeypatch,
    capsys,
):
    import api_server

    monkeypatch.setattr(
        "api.structured_logging.configure_structured_logging", lambda: None,
    )
    calls = _install_self_test_inputs(monkeypatch, include_canonicalizer=False)
    exit_code = api_server.main(["--native-svg-self-test", "fixture.svg"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload == {
        "error_type": "NativeSvgSelfTestError",
        "reason_code": "native_grid_canonicalization_unavailable",
        "status": "error",
    }
    assert calls == {"canonical": 0, "project": 0}


def test_cli_reports_success_only_after_both_domain_checks_run(
    monkeypatch,
    capsys,
):
    import api_server

    monkeypatch.setattr(
        "api.structured_logging.configure_structured_logging", lambda: None,
    )
    calls = _install_self_test_inputs(monkeypatch)
    exit_code = api_server.main(["--native-svg-self-test", "fixture.svg"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert calls == {"canonical": 1, "project": 1}
