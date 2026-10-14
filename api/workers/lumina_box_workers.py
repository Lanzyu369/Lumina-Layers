"""File-based CPU worker for the adopted Lumina Box fitter.
使用文件传参的新版 Lumina Box 拟合工作进程入口。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from core.lumina_box_fit_records import build_spectral_fit_payload
from core.lumina_box_fitting import fit_lumina_box_spectral
from core.lumina_box_spectral import BoxWhiteReference, LUMINA_BOX_DEFAULT_REFERENCE_MIN_REFLECTANCE


def fit_lumina_box_spectral_worker(input_path: str, output_path: str) -> str:
    """Fit a validated request and write the complete server-owned result.
    拟合已校验请求，并写出完整的服务器持有结果。

    Args:
        input_path: Registered private JSON request file.（已登记的私有 JSON 请求文件。）
        output_path: Registered private result file.（已登记的私有结果文件。）

    Returns:
        The output path, without transferring large arrays between processes.
        （结果文件路径，避免跨进程传递大数组。）
    """
    request = json.loads(Path(input_path).read_text(encoding="utf-8"))
    measurement = request["measurement"]
    rows = measurement["samples"]
    reference_data = request["white_reference"]
    reference = BoxWhiteReference.from_dict(reference_data) if reference_data is not None else None
    result = fit_lumina_box_spectral(
        np.array([row["thickness_mm"] for row in rows], dtype=np.float64),
        np.array([row["transmittance_percent_xyz"] for row in rows], dtype=np.float64) / 100.0,
        np.array([row["reflectance_percent_xyz"] for row in rows], dtype=np.float64) / 100.0,
        np.array(measurement["measurement_backing_percent_xyz"], dtype=np.float64) / 100.0,
        white_reference=reference, is_reference_white=request["is_reference_white"],
        reference_min_reflectance=float(request.get(
            "reference_min_reflectance_percent", 100.0 * LUMINA_BOX_DEFAULT_REFERENCE_MIN_REFLECTANCE,
        )) / 100.0,
    )
    payload = build_spectral_fit_payload(result, measurement)
    Path(output_path).write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return output_path
