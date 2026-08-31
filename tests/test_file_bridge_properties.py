"""Property-based tests for File Bridge image roundtrip consistency (Property 3).

Uses Hypothesis to generate random RGB ndarrays and verify PNG encode/decode
roundtrip preserves pixel values exactly (PNG is lossless).

**Validates: Requirements 2.1, 2.3**
"""

import asyncio
import io

import numpy as np
import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays
from PIL import Image

from api.file_bridge import (
    ensure_png_tempfile,
    ndarray_to_png_bytes,
    pil_to_png_bytes,
)
from core.native_svg_limits import NATIVE_SVG_MAX_BYTES

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Random RGB ndarrays with small dimensions to keep tests fast
rgb_arrays = arrays(
    dtype=np.uint8,
    shape=st.tuples(
        st.integers(min_value=1, max_value=50),
        st.integers(min_value=1, max_value=50),
        st.just(3),
    ),
)


# ---------------------------------------------------------------------------
# Property 3: File Bridge Image Roundtrip Consistency
# ---------------------------------------------------------------------------


# **Validates: Requirements 2.1, 2.3**
@given(arr=rgb_arrays)
@settings(max_examples=200)
def test_ndarray_png_roundtrip(arr: np.ndarray) -> None:
    """ndarray -> PNG bytes -> PIL Image -> ndarray roundtrip preserves pixels.

    For any valid RGB ndarray (H, W, 3, uint8), encoding to PNG via
    ndarray_to_png_bytes() and decoding back must yield identical pixel values.
    The result dtype must be uint8 and shape must be (H, W, 3).
    """
    png_bytes = ndarray_to_png_bytes(arr)

    # Decode back
    decoded_img = Image.open(io.BytesIO(png_bytes))
    decoded_arr = np.array(decoded_img, dtype=np.uint8)

    assert decoded_arr.dtype == np.uint8
    assert decoded_arr.shape == arr.shape
    np.testing.assert_array_equal(decoded_arr, arr)


# **Validates: Requirements 2.1, 2.3**
@given(arr=rgb_arrays)
@settings(max_examples=200)
def test_pil_png_roundtrip(arr: np.ndarray) -> None:
    """PIL Image -> PNG bytes -> PIL Image roundtrip preserves pixels.

    For any valid RGB PIL Image, encoding to PNG via pil_to_png_bytes()
    and decoding back must yield identical pixel values.
    """
    original_img = Image.fromarray(arr, mode="RGB")

    png_bytes = pil_to_png_bytes(original_img)

    # Decode back
    decoded_img = Image.open(io.BytesIO(png_bytes))
    decoded_arr = np.array(decoded_img, dtype=np.uint8)
    original_arr = np.array(original_img, dtype=np.uint8)

    assert decoded_arr.dtype == np.uint8
    assert decoded_arr.shape == original_arr.shape
    np.testing.assert_array_equal(decoded_arr, original_arr)


def test_svg_upload_limit_is_streamed_and_returns_413() -> None:
    class OversizedSvgUpload:
        filename = "oversized.svg"
        content_type = "image/svg+xml"

        def __init__(self) -> None:
            self.remaining = NATIVE_SVG_MAX_BYTES + 1
            self.maximum_requested = 0

        async def read(self, size: int = -1) -> bytes:
            self.maximum_requested = max(self.maximum_requested, size)
            if self.remaining == 0:
                return b""
            count = min(size, self.remaining)
            self.remaining -= count
            return b"x" * count

    upload = OversizedSvgUpload()

    with pytest.raises(HTTPException) as error:
        asyncio.run(ensure_png_tempfile(upload))  # type: ignore[arg-type]

    assert error.value.status_code == 413
    assert error.value.detail["code"] == "native_svg_upload_too_large"
    assert upload.maximum_requested <= 1024 * 1024
