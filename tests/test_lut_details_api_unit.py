from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import app
from core.lut_details.parser import LutParser
from core.lut_details.service import get_lut_details_service


client = TestClient(app)


def _write_alias_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "manufacturers": {"Bambu Lab": ["bambulab", "拓竹", "拓"]},
                "materials": {"PLA": ["pla", "pla basic"]},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_lut_json(path: Path, *, color_mode: str = "4-Color (RYBW)") -> None:
    payload = {
        "palette": {
            "White": {"material": "PLA Basic", "hex_color": "#FFFFFF", "color_name": "White"},
            "Blue": {"material": "PLA Basic", "hex_color": "#0064F0", "color_name": "Ocean Blue"},
        },
        "entries": [
            {"rgb": [255, 255, 255], "lab": [100.0, 0.0, 0.0], "recipe": ["White", "White", "White", "White", "White"]},
            {"rgb": [0, 100, 240], "lab": [40.0, 18.0, -66.0], "recipe": ["Blue", "White", "White", "White", "White"]},
        ],
        "batch_code": "B-12",
        "manufacturer": "",
        "type": "",
        "max_color_layers": 5,
        "layer_height_mm": 0.08,
        "line_width_mm": 0.42,
        "base_layers": 10,
        "base_channel_idx": 0,
        "layer_order": "Top2Bottom",
        "color_mode": color_mode,
        "name": path.stem,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_lut_details_catalog_and_detail_endpoints(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    lut_path = preset_dir / "Bambulab" / "PLA" / "catalog_source.json"
    _write_lut_json(lut_path)

    service = get_lut_details_service(preset_dir=preset_dir, alias_config_path=alias_path)

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    original_factory = lut_router_module.get_lut_details_service
    def _service_factory():
        return get_lut_details_service(
            preset_dir=preset_dir,
            alias_config_path=alias_path,
        )

    _service_factory.cache_clear = get_lut_details_service.cache_clear  # type: ignore[attr-defined]
    lut_router_module.get_lut_details_service = _service_factory
    lut_router_module._lut_details_service = service
    try:
        catalog_response = client.get("/api/lut/details/catalog")
        assert catalog_response.status_code == 200
        catalog = catalog_response.json()
        assert len(catalog["groups"]) == 1
        assert catalog["groups"][0]["manufacturer"] == "Bambu Lab"
        assert catalog["groups"][0]["items"][0]["manufacturer_source"] == "folder"
        assert "bambulab" in catalog["groups"][0]["items"][0]["search_tokens"]
        assert catalog["groups"][0]["items"][0]["material_type"] == "PLA"

        lut_name = catalog["groups"][0]["items"][0]["name"]
        detail_response = client.get(f"/api/lut/{lut_name}/details")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["manufacturer"] == "Bambu Lab"
        assert detail["material_type"] == "PLA"
        assert detail["raw_metadata"]["batch_code"] == "B-12"
        assert detail["palette"][0]["color"] == "White"
        assert detail["capabilities"]
        assert detail["lab_hull"] == []
        assert detail["coverage_stats"]["a_range"] == {"min": 0.0, "max": 18.0}
        assert detail["supported_modes"] == []
        assert detail["raw_metadata"]["palette"]["White"]["color_name"] == "White"
        assert detail["coverage_stats"]["entry_count"] == 2
        assert len(detail["lab_points"]) == 2
        assert len(detail["lab_points_3d"]) == 2
        assert detail["lab_points_3d"][0]["rgb"] == [255, 255, 255]
        assert len(detail["rgb_points"]) == 2

        missing_response = client.get("/api/lut/does-not-exist/details")
        assert missing_response.status_code == 404
    finally:
        lut_router_module._lut_details_service = original_service
        lut_router_module.get_lut_details_service = original_factory


def test_lut_details_endpoint_canonicalizes_raw_metadata_color_mode(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    lut_path = preset_dir / "Bambulab" / "PLA" / "legacy_eight.json"
    _write_lut_json(lut_path, color_mode="8-Color")

    service = get_lut_details_service(preset_dir=preset_dir, alias_config_path=alias_path)

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    original_factory = lut_router_module.get_lut_details_service

    def _service_factory():
        return get_lut_details_service(
            preset_dir=preset_dir,
            alias_config_path=alias_path,
        )

    _service_factory.cache_clear = get_lut_details_service.cache_clear  # type: ignore[attr-defined]
    lut_router_module.get_lut_details_service = _service_factory
    lut_router_module._lut_details_service = service
    try:
        detail_response = client.get("/api/lut/Bambulab - PLA - legacy_eight/details")
        assert detail_response.status_code == 200

        detail = detail_response.json()
        assert detail["color_mode"] == "8-Color Max"
        assert detail["raw_metadata"]["color_mode"] == "8-Color Max"
    finally:
        lut_router_module._lut_details_service = original_service
        lut_router_module.get_lut_details_service = original_factory


def test_lut_details_catalog_endpoint_returns_500_when_all_catalog_entries_fail_to_parse(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    broken_path = preset_dir / "Bambulab" / "PLA" / "broken.json"
    broken_path.parent.mkdir(parents=True, exist_ok=True)
    broken_path.write_text("{invalid", encoding="utf-8")

    service = get_lut_details_service(preset_dir=preset_dir, alias_config_path=alias_path)

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    original_factory = lut_router_module.get_lut_details_service

    def _service_factory():
        return get_lut_details_service(
            preset_dir=preset_dir,
            alias_config_path=alias_path,
        )

    _service_factory.cache_clear = get_lut_details_service.cache_clear  # type: ignore[attr-defined]
    lut_router_module.get_lut_details_service = _service_factory
    lut_router_module._lut_details_service = service
    try:
        response = client.get("/api/lut/details/catalog")
        assert response.status_code == 500
        assert "LUT details catalog unavailable" in response.json()["detail"]
    finally:
        lut_router_module._lut_details_service = original_service
        lut_router_module.get_lut_details_service = original_factory


def test_lut_details_detail_endpoint_returns_500_when_named_file_exists_but_cannot_parse(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    broken_path = preset_dir / "Bambulab" / "PLA" / "broken_detail.json"
    broken_path.parent.mkdir(parents=True, exist_ok=True)
    broken_path.write_text("{invalid", encoding="utf-8")

    service = get_lut_details_service(preset_dir=preset_dir, alias_config_path=alias_path)

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    lut_router_module._lut_details_service = service
    try:
        response = client.get("/api/lut/Bambulab - PLA - broken_detail/details")
        assert response.status_code == 500
        assert "LUT details unavailable" in response.json()["detail"]
    finally:
        lut_router_module._lut_details_service = original_service


def test_lut_details_router_cache_invalidation_picks_up_new_catalog_file(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    first_path = preset_dir / "Bambulab" / "PLA" / "first.json"
    _write_lut_json(first_path)

    service = get_lut_details_service(preset_dir=preset_dir, alias_config_path=alias_path)

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    original_factory = lut_router_module.get_lut_details_service

    def _service_factory():
        return get_lut_details_service(
            preset_dir=preset_dir,
            alias_config_path=alias_path,
        )

    _service_factory.cache_clear = get_lut_details_service.cache_clear  # type: ignore[attr-defined]
    lut_router_module.get_lut_details_service = _service_factory
    lut_router_module._lut_details_service = service
    try:
        first_response = client.get("/api/lut/details/catalog")
        assert first_response.status_code == 200
        first_items = first_response.json()["groups"][0]["items"]
        assert [item["name"] for item in first_items] == ["Bambulab - PLA - first"]

        second_path = preset_dir / "Bambulab" / "PLA" / "second.json"
        _write_lut_json(second_path)
        lut_router_module._invalidate_lut_details_service_cache()

        second_response = client.get("/api/lut/details/catalog")
        assert second_response.status_code == 200
        second_items = second_response.json()["groups"][0]["items"]
        assert {item["name"] for item in second_items} == {
            "Bambulab - PLA - first",
            "Bambulab - PLA - second",
        }
    finally:
        lut_router_module._lut_details_service = original_service
        lut_router_module.get_lut_details_service = original_factory


def test_lut_details_detail_endpoint_sanitizes_bytes_in_raw_metadata(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    msgpack_path = preset_dir / "Bambulab" / "PLA" / "bytes_meta.msgpack"
    msgpack_path.parent.mkdir(parents=True, exist_ok=True)
    import msgpack

    msgpack_path.write_bytes(
        msgpack.packb(
            {
                "palette": {"White": {"material": "PLA Basic"}},
                "entries": [{"rgb": [255, 255, 255], "recipe": ["White"]}],
                "custom_blob": b"\x00\x01\x02",
            },
            use_bin_type=True,
        )
    )

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    original_factory = lut_router_module.get_lut_details_service

    def _service_factory():
        return get_lut_details_service(
            preset_dir=preset_dir,
            alias_config_path=alias_path,
        )

    _service_factory.cache_clear = get_lut_details_service.cache_clear  # type: ignore[attr-defined]
    lut_router_module.get_lut_details_service = _service_factory
    lut_router_module._lut_details_service = None
    try:
        response = client.get("/api/lut/Bambulab - PLA - bytes_meta/details")
        assert response.status_code == 200
    finally:
        lut_router_module._lut_details_service = original_service
        lut_router_module.get_lut_details_service = original_factory


def test_lut_details_detail_endpoint_sanitizes_model_package_binary_metadata(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    import msgpack
    import numpy as np
    from core.native_reference import build_channel_key

    msgpack_path = preset_dir / "Bambulab" / "PLA" / "package.msgpack"
    msgpack_path.parent.mkdir(parents=True, exist_ok=True)
    msgpack_path.write_bytes(
        msgpack.packb(
            {
                "scope": {"vendor": "Bambulab", "material_type": "PLA Basic"},
                "channel_keys": [build_channel_key("White", "PLA Basic")],
                "modes": [
                    {
                        "color_layers": 8,
                        "layer_height_mm": 0.08,
                        "layer_order": "Top2Bottom",
                        "num_candidates": 1,
                        "candidate_recipes": np.array([[0, 0, 0, 0, 0, 0, 0, 0]], dtype=np.uint8).tobytes(),
                        "pred_lab": np.array([[50.0, 0.0, 0.0]], dtype="<f4").tobytes(),
                    },
                ],
            },
            use_bin_type=True,
        )
    )

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    original_factory = lut_router_module.get_lut_details_service

    def _service_factory():
        return get_lut_details_service(
            preset_dir=preset_dir,
            alias_config_path=alias_path,
        )

    _service_factory.cache_clear = get_lut_details_service.cache_clear  # type: ignore[attr-defined]
    lut_router_module.get_lut_details_service = _service_factory
    lut_router_module._lut_details_service = None
    try:
        response = client.get("/api/lut/Bambulab - PLA - package/details")
        assert response.status_code == 200
    finally:
        lut_router_module._lut_details_service = original_service
        lut_router_module.get_lut_details_service = original_factory


def test_lut_details_detail_endpoint_uses_later_valid_model_package_mode_when_first_mode_is_broken(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    import msgpack
    import numpy as np
    from core.native_reference import build_channel_key

    msgpack_path = preset_dir / "Bambulab" / "PLA" / "package_fallback.msgpack"
    msgpack_path.parent.mkdir(parents=True, exist_ok=True)
    msgpack_path.write_bytes(
        msgpack.packb(
            {
                "scope": {"vendor": "Bambulab", "material_type": "PLA Basic"},
                "channel_keys": [build_channel_key("White", "PLA Basic")],
                "modes": [
                    {
                        "color_layers": 5,
                        "layer_height_mm": 0.08,
                        "layer_order": "Top2Bottom",
                        "num_candidates": 1,
                        "candidate_recipes": b"",
                        "pred_lab": b"",
                    },
                    {
                        "color_layers": 8,
                        "layer_height_mm": 0.08,
                        "layer_order": "Top2Bottom",
                        "num_candidates": 1,
                        "candidate_recipes": np.array([[0, 0, 0, 0, 0, 0, 0, 0]], dtype=np.uint8).tobytes(),
                        "pred_lab": np.array([[50.0, 0.0, 0.0]], dtype="<f4").tobytes(),
                    },
                ],
            },
            use_bin_type=True,
        )
    )

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    original_factory = lut_router_module.get_lut_details_service

    def _service_factory():
        return get_lut_details_service(
            preset_dir=preset_dir,
            alias_config_path=alias_path,
        )

    _service_factory.cache_clear = get_lut_details_service.cache_clear  # type: ignore[attr-defined]
    lut_router_module.get_lut_details_service = _service_factory
    lut_router_module._lut_details_service = None
    try:
        response = client.get("/api/lut/Bambulab - PLA - package_fallback/details")
        assert response.status_code == 200
        payload = response.json()
        assert payload["color_count"] == 1
        assert payload["max_color_layers"] == 8
        assert len(payload["lab_points"]) == 1
        assert len(payload["rgb_points"]) == 1
    finally:
        lut_router_module._lut_details_service = original_service
        lut_router_module.get_lut_details_service = original_factory


def test_lut_details_detail_endpoint_uses_later_valid_model_package_mode_when_first_mode_header_is_malformed(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    import msgpack
    import numpy as np
    from core.native_reference import build_channel_key

    msgpack_path = preset_dir / "Bambulab" / "PLA" / "package_header_fallback.msgpack"
    msgpack_path.parent.mkdir(parents=True, exist_ok=True)
    msgpack_path.write_bytes(
        msgpack.packb(
            {
                "scope": {"vendor": "Bambulab", "material_type": "PLA Basic"},
                "channel_keys": [build_channel_key("White", "PLA Basic")],
                "modes": [
                    {
                        "color_layers": "oops",
                        "layer_height_mm": 0.08,
                        "layer_order": "Top2Bottom",
                        "num_candidates": 1,
                        "candidate_recipes": b"",
                        "pred_lab": b"",
                    },
                    {
                        "color_layers": 8,
                        "layer_height_mm": 0.08,
                        "layer_order": "Top2Bottom",
                        "num_candidates": 1,
                        "candidate_recipes": np.array([[0, 0, 0, 0, 0, 0, 0, 0]], dtype=np.uint8).tobytes(),
                        "pred_lab": np.array([[50.0, 0.0, 0.0]], dtype="<f4").tobytes(),
                    },
                ],
            },
            use_bin_type=True,
        )
    )

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    original_factory = lut_router_module.get_lut_details_service

    def _service_factory():
        return get_lut_details_service(
            preset_dir=preset_dir,
            alias_config_path=alias_path,
        )

    _service_factory.cache_clear = get_lut_details_service.cache_clear  # type: ignore[attr-defined]
    lut_router_module.get_lut_details_service = _service_factory
    lut_router_module._lut_details_service = None
    try:
        response = client.get("/api/lut/Bambulab - PLA - package_header_fallback/details")
        assert response.status_code == 200
        payload = response.json()
        assert payload["max_color_layers"] == 8
        assert payload["color_count"] == 1
    finally:
        lut_router_module._lut_details_service = original_service
        lut_router_module.get_lut_details_service = original_factory


def test_lut_details_detail_endpoint_skips_model_package_mode_with_malformed_num_candidates(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    import msgpack
    import numpy as np
    from core.native_reference import build_channel_key

    msgpack_path = preset_dir / "Bambulab" / "PLA" / "package_bad_num_candidates.msgpack"
    msgpack_path.parent.mkdir(parents=True, exist_ok=True)
    msgpack_path.write_bytes(
        msgpack.packb(
            {
                "scope": {"vendor": "Bambulab", "material_type": "PLA Basic"},
                "channel_keys": [build_channel_key("White", "PLA Basic")],
                "modes": [
                    {
                        "color_layers": 5,
                        "layer_height_mm": 0.08,
                        "layer_order": "Top2Bottom",
                        "num_candidates": "oops",
                        "candidate_recipes": b"",
                        "pred_lab": b"",
                    },
                    {
                        "color_layers": 8,
                        "layer_height_mm": 0.08,
                        "layer_order": "Top2Bottom",
                        "num_candidates": 1,
                        "candidate_recipes": np.array([[0, 0, 0, 0, 0, 0, 0, 0]], dtype=np.uint8).tobytes(),
                        "pred_lab": np.array([[50.0, 0.0, 0.0]], dtype="<f4").tobytes(),
                    },
                ],
            },
            use_bin_type=True,
        )
    )

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    original_factory = lut_router_module.get_lut_details_service

    def _service_factory():
        return get_lut_details_service(
            preset_dir=preset_dir,
            alias_config_path=alias_path,
        )

    _service_factory.cache_clear = get_lut_details_service.cache_clear  # type: ignore[attr-defined]
    lut_router_module.get_lut_details_service = _service_factory
    lut_router_module._lut_details_service = None
    try:
        response = client.get("/api/lut/Bambulab - PLA - package_bad_num_candidates/details")
        assert response.status_code == 200
        payload = response.json()
        assert payload["max_color_layers"] == 8
        assert payload["color_count"] == 1
    finally:
        lut_router_module._lut_details_service = original_service
        lut_router_module.get_lut_details_service = original_factory


def test_lut_details_detail_endpoint_ignores_malformed_model_package_threshold_margin(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    import msgpack
    import numpy as np
    from core.native_reference import build_channel_key

    msgpack_path = preset_dir / "Bambulab" / "PLA" / "package_bad_threshold.msgpack"
    msgpack_path.parent.mkdir(parents=True, exist_ok=True)
    msgpack_path.write_bytes(
        msgpack.packb(
            {
                "scope": {"vendor": "Bambulab", "material_type": "PLA Basic"},
                "channel_keys": [build_channel_key("White", "PLA Basic")],
                "modes": [
                    {
                        "color_layers": 5,
                        "layer_height_mm": 0.08,
                        "layer_order": "Top2Bottom",
                        "num_candidates": 1,
                        "candidate_recipes": np.array([[0, 0, 0, 0, 0]], dtype=np.uint8).tobytes(),
                        "pred_lab": np.array([[50.0, 0.0, 0.0]], dtype="<f4").tobytes(),
                        "threshold": "oops",
                        "margin": "oops",
                    },
                ],
            },
            use_bin_type=True,
        )
    )

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    original_factory = lut_router_module.get_lut_details_service

    def _service_factory():
        return get_lut_details_service(
            preset_dir=preset_dir,
            alias_config_path=alias_path,
        )

    _service_factory.cache_clear = get_lut_details_service.cache_clear  # type: ignore[attr-defined]
    lut_router_module.get_lut_details_service = _service_factory
    lut_router_module._lut_details_service = None
    try:
        response = client.get("/api/lut/Bambulab - PLA - package_bad_threshold/details")
        assert response.status_code == 200
        payload = response.json()
        assert payload["color_count"] == 1
        assert len(payload["lab_points"]) == 1
    finally:
        lut_router_module._lut_details_service = original_service
        lut_router_module.get_lut_details_service = original_factory


def test_parser_treats_msgpack_with_unusable_modes_as_keyed_payload(tmp_path: Path) -> None:
    import msgpack

    msgpack_path = tmp_path / "keyed_with_modes.msgpack"
    msgpack_path.write_bytes(
        msgpack.packb(
            {
                "palette": {"White": {"material": "PLA Basic"}},
                "entries": [{"rgb": [255, 255, 255], "recipe": ["White"]}],
                "modes": [{"note": "not-a-model-package-mode"}],
            },
            use_bin_type=True,
        )
    )

    parsed = LutParser().parse(name="keyed_with_modes", path=msgpack_path)

    assert parsed.rgb.shape == (1, 3)
    assert parsed.lab.shape == (1, 3)


def test_parser_falls_back_to_keyed_msgpack_entries_when_model_like_modes_are_unusable(tmp_path: Path) -> None:
    import msgpack

    msgpack_path = tmp_path / "keyed_with_broken_model_like_modes.msgpack"
    msgpack_path.write_bytes(
        msgpack.packb(
            {
                "palette": {"White": {"material": "PLA Basic"}},
                "entries": [{"rgb": [255, 255, 255], "recipe": ["White"]}],
                "modes": [
                    {
                        "color_layers": 5,
                        "layer_height_mm": 0.08,
                        "layer_order": "Top2Bottom",
                        "num_candidates": 1,
                        "candidate_recipes": b"",
                        "pred_lab": b"",
                    },
                ],
            },
            use_bin_type=True,
        )
    )

    parsed = LutParser().parse(name="keyed_with_broken_model_like_modes", path=msgpack_path)

    assert parsed.rgb.shape == (1, 3)
    assert parsed.lab.shape == (1, 3)


def test_lut_details_detail_endpoint_returns_404_when_cached_file_was_deleted(tmp_path: Path) -> None:
    alias_path = tmp_path / "assets" / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    _write_alias_config(alias_path)

    lut_path = preset_dir / "Bambulab" / "PLA" / "deleted_after_catalog.json"
    _write_lut_json(lut_path)

    service = get_lut_details_service(preset_dir=preset_dir, alias_config_path=alias_path)

    from api.routers import lut as lut_router_module

    original_service = lut_router_module._lut_details_service
    original_factory = lut_router_module.get_lut_details_service

    def _service_factory():
        return get_lut_details_service(
            preset_dir=preset_dir,
            alias_config_path=alias_path,
        )

    _service_factory.cache_clear = get_lut_details_service.cache_clear  # type: ignore[attr-defined]
    lut_router_module.get_lut_details_service = _service_factory
    lut_router_module._lut_details_service = service
    try:
        catalog_response = client.get("/api/lut/details/catalog")
        assert catalog_response.status_code == 200

        lut_path.unlink()
        response = client.get("/api/lut/Bambulab - PLA - deleted_after_catalog/details")
        assert response.status_code == 404
    finally:
        lut_router_module._lut_details_service = original_service
        lut_router_module.get_lut_details_service = original_factory
