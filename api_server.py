"""Lumina Studio API server and frozen-runtime diagnostic entry point.

Lumina Studio API 服务与冻结运行时诊断入口。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections.abc import Sequence
from typing import Any


class NativeSvgSelfTestError(RuntimeError):
    """Stable failure raised when the required native path cannot run.

    必选原生 SVG 路径无法执行时使用的稳定失败类型。
    """

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _geometry_wkb(geometry: Any) -> bytes:
    import shapely

    return bytes(
        shapely.to_wkb(
            geometry,
            byte_order=1,
            include_srid=False,
        )
    )


def _update_record_fingerprint(
    digest: Any,
    *,
    family: bytes,
    records: Sequence[dict[str, Any]],
    geometry_key: str,
) -> None:
    digest.update(family)
    digest.update(struct.pack("<Q", len(records)))
    for record in records:
        color = tuple(int(value) for value in record.get("color", ()))
        digest.update(struct.pack("<Q", len(color)))
        digest.update(bytes(color))
        digest.update(
            str(record.get("source_kind", "")).encode("utf-8")
        )
        digest.update(
            struct.pack("<q", int(record.get("draw_order", -1)))
        )
        digest.update(_geometry_wkb(record[geometry_key]))


def _native_svg_self_test_payload(svg_path: str) -> dict[str, Any]:
    from core.native_svg_adapter import (
        NativeSvgFallback,
        analyze_native_svg,
    )

    result = analyze_native_svg(
        svg_path,
        target_width_mm=20.0,
        tolerance_mm=0.02,
        expand_stroke_to_fill=False,
    )
    if isinstance(result, NativeSvgFallback):
        raise NativeSvgSelfTestError(result.reason_code)
    if result.geometry_backend != "native":
        raise NativeSvgSelfTestError("non_native_backend")
    if not result.shape_data:
        raise NativeSvgSelfTestError("empty_raw_geometry")
    if not result.clipped_shapes:
        raise NativeSvgSelfTestError("empty_visible_geometry")
    if result.silhouette is None or result.silhouette.is_empty:
        raise NativeSvgSelfTestError("empty_silhouette")

    silhouette_components = (
        len(result.silhouette.geoms)
        if result.silhouette.geom_type == "MultiPolygon"
        else 1
    )
    digest = hashlib.sha256()
    digest.update(b"lumina-native-svg-self-test-v1\0")
    digest.update(struct.pack("<d", float(result.scale_factor)))
    digest.update(struct.pack("<4d", *result.bbox))
    _update_record_fingerprint(
        digest,
        family=b"raw\0",
        records=result.shape_data,
        geometry_key="poly",
    )
    _update_record_fingerprint(
        digest,
        family=b"visible\0",
        records=result.clipped_shapes,
        geometry_key="geometry",
    )
    digest.update(b"silhouette\0")
    digest.update(_geometry_wkb(result.silhouette))

    return {
        "status": "ok",
        "geometry_backend": "native",
        "native_version": result.native_version,
        "native_schema_version": int(result.native_schema_version),
        "raw_geometry_count": len(result.shape_data),
        "visible_geometry_count": len(result.clipped_shapes),
        "silhouette_component_count": silhouette_components,
        "fingerprint_sha256": digest.hexdigest(),
    }


def _print_json(payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run a native SVG probe or start the API server.

    执行原生 SVG 自检，或启动 API 服务。

    Args:
        argv: Optional command-line arguments without the executable name.
            可选命令行参数，不含可执行文件名。

    Returns:
        Process exit code. 进程退出码。
    """

    parser = argparse.ArgumentParser(description="Run Lumina Studio backend.")
    parser.add_argument(
        "--native-svg-self-test",
        metavar="SVG_PATH",
        help="Analyze one SVG through the required native Lumina adapter.",
    )
    args = parser.parse_args(argv)
    if args.native_svg_self_test:
        try:
            payload = _native_svg_self_test_payload(
                args.native_svg_self_test
            )
        except NativeSvgSelfTestError as exc:
            _print_json(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "reason_code": exc.reason_code,
                }
            )
            return 1
        except Exception as exc:  # Boundary guard for the frozen probe.
            _print_json(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "reason_code": str(
                        getattr(exc, "reason_code", "native_self_test_failed")
                    ),
                }
            )
            return 1
        _print_json(payload)
        return 0

    # ``api.app`` is the canonical place that calls ``load_env_local()`` at
    # module scope. Importing it here loads .env.local before uvicorn starts.
    import uvicorn
    from api.app import app

    uvicorn.run(app, host="0.0.0.0", port=8000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
