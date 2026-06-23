"""Unit tests for ``POST /api/extractor/rotate`` direction parameter.

Validates that the endpoint:
- defaults to counter-clockwise rotation (backwards compatible);
- supports explicit ``direction=cw`` and ``direction=ccw``;
- rejects invalid direction values with HTTP 422.

验证 ``POST /api/extractor/rotate`` 的 ``direction`` 参数：
- 缺省时按逆时针处理（保持向后兼容）；
- 支持 ``direction=cw`` 与 ``direction=ccw``；
- 非法 direction 返回 422。
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore

client: TestClient = TestClient(app)
_RAW_UNSUPPORTED_DETAIL = (
    "当前环境暂不支持 RAW 图片，请先转换为 PNG/JPEG 后再上传。"
)
_OPTIONAL_DEPENDENCY_FORBIDDEN_FRAGMENTS = (
    "pip install",
    "pillow-heif",
    "rawpy",
)


@pytest.fixture(autouse=True)
def _isolate_dependency_overrides():
    """Isolate this test module from global override pollution."""
    test_store = SessionStore()
    test_registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: test_store
    app.dependency_overrides[get_file_registry] = lambda: test_registry
    try:
        yield {"store": test_store, "registry": test_registry}
    finally:
        app.dependency_overrides.pop(get_session_store, None)
        app.dependency_overrides.pop(get_file_registry, None)


def _asymmetric_png_bytes() -> tuple[bytes, np.ndarray]:
    """Create a small non-square asymmetric image whose orientation can be
    reliably inferred by inspecting opposite corner pixels.
    返回一张非对称小图（左上角与右下角颜色不同），便于通过对角像素判定方向。
    """
    arr = np.zeros((4, 6, 3), dtype=np.uint8)
    arr[0, 0] = (255, 0, 0)  # top-left red
    arr[-1, -1] = (0, 0, 255)  # bottom-right blue
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue(), arr


def _post_rotate(image_bytes: bytes, *, direction: str | None = None):
    files = {"image": ("input.png", image_bytes, "image/png")}
    params = {"direction": direction} if direction is not None else None
    return client.post("/api/extractor/rotate", files=files, params=params)


def _fetch_preview_array(preview_url: str) -> np.ndarray:
    file_id = preview_url.rsplit("/", 1)[-1]
    response = client.get(f"/api/files/{file_id}")
    assert response.status_code == 200
    return np.asarray(Image.open(io.BytesIO(response.content)).convert("RGB"))


def test_rotate_defaults_to_ccw_for_backwards_compat():
    """Calling without ``direction`` must rotate counter-clockwise.
    缺省 direction 应等价于逆时针旋转。
    """
    image_bytes, source = _asymmetric_png_bytes()
    response = _post_rotate(image_bytes)
    assert response.status_code == 200, response.text
    payload = response.json()
    # Counter-clockwise rotation swaps width/height; the source's TL pixel
    # ends up at the BL of the rotated image.
    assert payload["width"] == source.shape[0]
    assert payload["height"] == source.shape[1]
    rotated = _fetch_preview_array(payload["preview_url"])
    h, w = rotated.shape[:2]
    assert tuple(int(c) for c in rotated[h - 1, 0]) == (255, 0, 0)
    assert tuple(int(c) for c in rotated[0, w - 1]) == (0, 0, 255)


def test_rotate_explicit_ccw_matches_default():
    """``direction=ccw`` must match the default behaviour.
    显式传 ccw 应当与缺省一致。
    """
    image_bytes, _ = _asymmetric_png_bytes()
    default_response = _post_rotate(image_bytes)
    ccw_response = _post_rotate(image_bytes, direction="ccw")
    assert default_response.status_code == ccw_response.status_code == 200
    default_arr = _fetch_preview_array(default_response.json()["preview_url"])
    ccw_arr = _fetch_preview_array(ccw_response.json()["preview_url"])
    np.testing.assert_array_equal(default_arr, ccw_arr)


def test_rotate_clockwise_swaps_dimensions_and_corners():
    """``direction=cw`` rotates clockwise so source TL ends up at TR.
    顺时针旋转：原左上像素应位于结果的右上角。
    """
    image_bytes, source = _asymmetric_png_bytes()
    response = _post_rotate(image_bytes, direction="cw")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["width"] == source.shape[0]
    assert payload["height"] == source.shape[1]
    rotated = _fetch_preview_array(payload["preview_url"])
    h, w = rotated.shape[:2]
    # Source TL (red) -> rotated TR; source BR (blue) -> rotated BL.
    assert tuple(int(c) for c in rotated[0, w - 1]) == (255, 0, 0)
    assert tuple(int(c) for c in rotated[h - 1, 0]) == (0, 0, 255)


def test_rotate_cw_and_ccw_produce_different_outputs():
    """CW and CCW rotations must not be identical for asymmetric inputs.
    对非对称输入图，顺时针与逆时针结果必须不同。
    """
    image_bytes, _ = _asymmetric_png_bytes()
    cw_arr = _fetch_preview_array(
        _post_rotate(image_bytes, direction="cw").json()["preview_url"]
    )
    ccw_arr = _fetch_preview_array(
        _post_rotate(image_bytes, direction="ccw").json()["preview_url"]
    )
    assert not np.array_equal(cw_arr, ccw_arr)


@pytest.mark.parametrize("invalid", ["", "rotate", "left", "180", "clockwise"])
def test_rotate_rejects_invalid_direction(invalid: str):
    """Invalid direction strings must produce a 422 response.
    非法 direction 应返回 422，错误信息提示 cw/ccw 取值范围。
    """
    image_bytes, _ = _asymmetric_png_bytes()
    response = _post_rotate(image_bytes, direction=invalid)
    assert response.status_code == 422, response.text


def test_rotate_raw_missing_dependency_returns_safe_detail(
    monkeypatch: pytest.MonkeyPatch,
):
    """RAW optional dependency failures should not leak install guidance."""
    monkeypatch.setattr("api.file_bridge.HAS_RAW", False)

    response = client.post(
        "/api/extractor/rotate?direction=ccw",
        files={
            "image": (
                "camera.dng",
                b"not a raw image",
                "application/octet-stream",
            )
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _RAW_UNSUPPORTED_DETAIL
    assert all(
        fragment not in response.text
        for fragment in _OPTIONAL_DEPENDENCY_FORBIDDEN_FRAGMENTS
    )
