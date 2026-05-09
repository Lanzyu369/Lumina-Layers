"""
Native ColorChecker calibration API integrated into Lumina.

Serves the CC tool's frontend at ``/api/colorchecker-ui`` (static files
from disk) and provides the calibration backend API at ``/api/cc/``.
All heavy computation runs in ``asyncio.to_thread`` to avoid blocking.

No subprocess, no proxy — the CC Python logic is imported directly.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from api.structured_logging import get_logger

log = get_logger(__name__)

# --------------- Bootstrap CC imports ---------------

_CC_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "ColorChecker"
if not (_CC_ROOT / "app.py").is_file():
    _env = os.environ.get("COLORCHECKER_ROOT", "")
    if _env and (Path(_env) / "app.py").is_file():
        _CC_ROOT = Path(_env)

_cc = None  # will be set if CC is available

if (_CC_ROOT / "app.py").is_file():
    if str(_CC_ROOT) not in sys.path:
        sys.path.insert(0, str(_CC_ROOT))
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("_colorchecker_app", str(_CC_ROOT / "app.py"))
    if _spec and _spec.loader:
        _candidate = _ilu.module_from_spec(_spec)
        sys.modules["_colorchecker_app"] = _candidate
        try:
            _spec.loader.exec_module(_candidate)  # type: ignore[union-attr]
        except Exception as exc:
            sys.modules.pop("_colorchecker_app", None)
            log.warning(
                "ColorChecker module import failed",
                extra={
                    "event": "colorchecker_dependency_import_failed",
                    "dependency": "ColorChecker",
                    "path": str(_CC_ROOT),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
        else:
            _cc = _candidate
            log.info(
                "ColorChecker module loaded",
                extra={
                    "event": "colorchecker_dependency_loaded",
                    "dependency": "ColorChecker",
                    "path": str(_CC_ROOT),
                },
            )
    else:
        log.warning(
            "ColorChecker import spec unavailable",
            extra={
                "event": "colorchecker_dependency_spec_unavailable",
                "dependency": "ColorChecker",
                "path": str(_CC_ROOT / "app.py"),
            },
        )
else:
    log.warning(
        "ColorChecker module not found",
        extra={
            "event": "colorchecker_dependency_unavailable",
            "dependency": "ColorChecker",
            "path": str(_CC_ROOT),
        },
    )


def _require_cc() -> JSONResponse | None:
    """Guard: return a 503 response if CC is not available, else None."""
    if _cc is None:
        return JSONResponse(
            content={"error": "ColorChecker module is not available."},
            status_code=503,
        )
    return None

router = APIRouter(tags=["colorchecker-ui"])

# --------------- Bridge script for iframe embedding ---------------

_BRIDGE_SCRIPT = r"""
<script>
(function() {
  var isEmbedded = (window.parent !== window);
  if (!isEmbedded) return;

  var _lastResultData = null;
  setInterval(function() {
    try {
      if (typeof state !== 'undefined' && state.resultData && state.resultData !== _lastResultData) {
        _lastResultData = state.resultData;
        window.parent.postMessage({
          type: 'colorchecker-calibrated',
          calibratedImageData: state.resultData
        }, '*');
      }
    } catch(e) {}
  }, 500);

  window.addEventListener('message', function(event) {
    if (!event.data || event.data.type !== 'colorchecker-load-image') return;
    var blob = event.data.blob;
    var fileName = event.data.fileName || 'upload.png';
    if (!blob) return;

    function inject() {
      var input = document.getElementById('imageInput');
      if (!input) { setTimeout(inject, 300); return; }
      try {
        var dt = new DataTransfer();
        dt.items.add(new File([blob], fileName, { type: blob.type || 'image/png' }));
        input.files = dt.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
      } catch(e) {
        console.warn('[bridge] inject failed:', e);
      }
    }
    setTimeout(inject, 300);
  });
})();
</script>
"""

# --------------- Cached static files ---------------

_INDEX_HTML: str | None = None
_APP_JS: str | None = None
_STYLES_CSS: str | None = None


def _get_index_html() -> str:
    global _INDEX_HTML
    if _INDEX_HTML is None:
        raw = (_CC_ROOT / "index.html").read_text(encoding="utf-8")
        raw = raw.replace('src="/app.js"', 'src="/api/colorchecker-ui/app.js"')
        raw = raw.replace('src="app.js"', 'src="/api/colorchecker-ui/app.js"')
        raw = raw.replace("src='/app.js'", "src='/api/colorchecker-ui/app.js'")
        raw = raw.replace("src='app.js'", "src='/api/colorchecker-ui/app.js'")
        raw = raw.replace('href="/styles.css"', 'href="/api/colorchecker-ui/styles.css"')
        raw = raw.replace('href="styles.css"', 'href="/api/colorchecker-ui/styles.css"')
        raw = raw.replace("href='/styles.css'", "href='/api/colorchecker-ui/styles.css'")
        raw = raw.replace("href='styles.css'", "href='/api/colorchecker-ui/styles.css'")
        raw = raw.replace("</body>", f"{_BRIDGE_SCRIPT}</body>")
        _INDEX_HTML = raw
    return _INDEX_HTML


def _get_app_js() -> str:
    global _APP_JS
    if _APP_JS is None:
        raw = (_CC_ROOT / "app.js").read_text(encoding="utf-8")
        raw = raw.replace('"/api/', '"/api/cc/')
        raw = raw.replace("'/api/", "'/api/cc/")
        raw = raw.replace("`/api/", "`/api/cc/")
        _APP_JS = raw
    return _APP_JS


# --------------- Helpers ---------------

def _json_resp(data: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status)


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse(content={"error": msg}, status_code=status)


# --------------- UI static files ---------------

@router.get("/api/colorchecker-ui")
async def serve_colorchecker_ui() -> Response:
    if (unavail := _require_cc()):
        return unavail
    return HTMLResponse(content=_get_index_html())


@router.get("/api/colorchecker-ui/{filename}")
async def serve_colorchecker_static(filename: str) -> Response:
    if (unavail := _require_cc()):
        return unavail
    if filename == "app.js":
        return Response(content=_get_app_js(), media_type="application/javascript; charset=utf-8")
    if filename == "styles.css":
        global _STYLES_CSS
        if _STYLES_CSS is None:
            _STYLES_CSS = (_CC_ROOT / "styles.css").read_text(encoding="utf-8")
        return Response(content=_STYLES_CSS, media_type="text/css; charset=utf-8")
    return Response("Not found", status_code=404)


# --------------- CC API endpoints (native) ---------------

@router.get("/api/cc/brands")
async def cc_brands() -> JSONResponse:
    if (unavail := _require_cc()):
        return unavail
    return _json_resp({
        "brands": _cc.list_brand_summaries(),
        "defaultBrandId": _cc.DEFAULT_BRAND_ID,
    })


@router.get("/api/cc/reference")
async def cc_reference(
    brand: str | None = None,
    exposureAnchorTargetSrgb: int | None = None,
) -> JSONResponse:
    if (unavail := _require_cc()):
        return unavail
    brand_id = brand or _cc.DEFAULT_BRAND_ID
    eat = _cc.sanitize_exposure_anchor_target(
        exposureAnchorTargetSrgb or _cc.EXPOSURE_ANCHOR_TARGET_SRGB
    )
    try:
        b = _cc.get_brand(brand_id, exposure_anchor_target_srgb=eat)
    except ValueError as exc:
        return _err(str(exc))
    return _json_resp({
        "brandId": b["id"],
        "brandName": b["name"],
        "exposureAnchorPatchIndex": int(b["exposure_anchor_patch_index"]),
        "exposureAnchorTargetSrgb": int(b["exposure_anchor_target_srgb"]),
        "patches": b["patches"],
    })


@router.post("/api/cc/load-image")
async def cc_load_image(request: Request) -> JSONResponse:
    if (unavail := _require_cc()):
        return unavail
    t0 = time.perf_counter()

    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            return _err("缺少上传文件。")
        raw_bytes = await upload.read()  # type: ignore[union-attr]
        file_name = getattr(upload, "filename", None) or "upload"
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    else:
        payload = await request.json()
        file_data = str(payload.get("fileData") or "")
        file_name = str(payload.get("fileName") or "")
        if not file_data:
            return _err("缺少上传文件。")
        mime_type, raw_bytes = _cc.parse_data_url(file_data)

    def _process() -> dict:
        _cc.save_upload_bytes(raw_bytes, file_name, kind="single")
        image, source_type = _cc.decode_uploaded_bytes(
            raw_bytes, file_name=file_name, mime_type=mime_type,
        )
        token = _cc.store_cached_image(image)
        h, w = image.shape[:2]
        return {
            "imageData": _cc.encode_png_data_url(image),
            "imageToken": token,
            "width": w,
            "height": h,
            "sourceType": source_type,
        }

    try:
        result = await asyncio.to_thread(_process)
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:
        log.exception(
            "ColorChecker image load failed",
            extra={
                "event": "colorchecker_load_image_failed",
                "file_name": file_name,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return _err(str(exc), 500)

    log.info(
        "ColorChecker image loaded",
        extra={
            "event": "colorchecker_load_image_done",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
            "file_name": file_name,
        },
    )
    return _json_resp(result)


@router.post("/api/cc/warp-preview")
async def cc_warp_preview(request: Request) -> JSONResponse:
    if (unavail := _require_cc()):
        return unavail
    t0 = time.perf_counter()
    payload = await request.json()

    def _process() -> dict:
        corners = payload.get("corners")
        width = int(payload.get("previewWidth") or _cc.DEFAULT_PREVIEW_WIDTH)
        height = int(payload.get("previewHeight") or _cc.DEFAULT_PREVIEW_HEIGHT)
        if not isinstance(corners, list) or len(corners) != 4:
            raise ValueError("请先点击 4 个角点。")
        image = _cc.resolve_request_image(payload)
        preview, _, ordered = _cc.warp_colorchecker_preview(image, corners, width, height)
        return {
            "previewImageData": _cc.encode_png_data_url(preview),
            "previewWidth": width,
            "previewHeight": height,
            "orderedCorners": [
                {"x": round(float(p[0]), 2), "y": round(float(p[1]), 2)}
                for p in ordered.tolist()
            ],
        }

    try:
        result = await asyncio.to_thread(_process)
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:
        log.exception(
            "ColorChecker warp preview failed",
            extra={
                "event": "colorchecker_warp_preview_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return _err(str(exc), 500)

    log.info(
        "ColorChecker warp preview generated",
        extra={
            "event": "colorchecker_warp_preview_done",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        },
    )
    return _json_resp(result)


@router.post("/api/cc/calibrate")
async def cc_calibrate(request: Request) -> JSONResponse:
    if (unavail := _require_cc()):
        return unavail
    t0 = time.perf_counter()
    payload = await request.json()

    def _process() -> dict:
        corners = payload.get("corners")
        patch_points = payload.get("patchPoints")
        width = int(payload.get("previewWidth") or _cc.DEFAULT_PREVIEW_WIDTH)
        height = int(payload.get("previewHeight") or _cc.DEFAULT_PREVIEW_HEIGHT)
        radius = int(payload.get("sampleRadius") or 12)
        method = str(payload.get("method") or "mean")
        auto_arrange = bool(payload.get("autoArrange") or False)
        patch_layout = str(payload.get("patchLayout") or "4x6")
        brand = _cc.get_brand(payload.get("brand"))
        reference_patches = brand["patches"]
        reference_color_map = brand["color_map"]

        if not isinstance(corners, list) or len(corners) != 4:
            raise ValueError("请先点击 4 个角点。")
        if not isinstance(patch_points, list) or len(patch_points) != len(reference_patches):
            raise ValueError(f"请按顺序完成 {len(reference_patches)} 个色块点击。")
        if method not in {"mean", "median"}:
            raise ValueError("不支持的采样方式。")

        image = _cc.resolve_request_image(payload)
        preview, _, ordered = _cc.warp_colorchecker_preview(image, corners, width, height)
        patch_colors, patch_details = _cc.build_patch_measurements(
            preview, patch_points, radius, method, reference_patches,
        )
        ccm, stats = _cc.compute_ccm_from_colorchecker(patch_colors, reference_color_map)
        patch_details = _cc.enrich_patch_details(patch_details, ccm)
        corrected = _cc.apply_ccm_to_image(image, ccm)
        overlay = _cc.render_preview_overlay(preview, patch_details, radius)
        report = _cc.build_report(
            patch_details, stats, ccm,
            [
                {"x": round(float(p[0]), 2), "y": round(float(p[1]), 2)}
                for p in ordered.tolist()
            ],
            radius, method,
        )
        corrected_png = _cc.encode_png_bytes(corrected)
        overlay_png = _cc.encode_png_bytes(overlay)
        return {
            "calibratedImageData": _cc.png_bytes_to_data_url(corrected_png),
            "previewOverlayImageData": _cc.png_bytes_to_data_url(overlay_png),
            "report": report,
        }

    try:
        result = await asyncio.to_thread(_process)
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:
        log.exception(
            "ColorChecker calibration failed",
            extra={
                "event": "colorchecker_calibrate_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return _err(str(exc), 500)

    log.info(
        "ColorChecker calibration completed",
        extra={
            "event": "colorchecker_calibrate_done",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        },
    )
    return _json_resp(result)
