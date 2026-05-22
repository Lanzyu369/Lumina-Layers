from __future__ import annotations

import math
from typing import Iterable

import numpy as np


WHITE_D50 = np.array([0.96422, 1.0, 0.82521], dtype=np.float64)
WHITE_D65 = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)

RGB_TO_XYZ_D65 = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)
XYZ_D65_TO_RGB = np.array(
    [
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ],
    dtype=np.float64,
)

_BRADFORD = np.array(
    [
        [0.8951, 0.2664, -0.1614],
        [-0.7502, 1.7135, 0.0367],
        [0.0389, -0.0685, 1.0296],
    ],
    dtype=np.float64,
)
_BRADFORD_INV = np.linalg.inv(_BRADFORD)
_LAB_DELTA = 6.0 / 29.0
_LAB_DELTA_CUBED = _LAB_DELTA ** 3
_LAB_SCALE = 1.0 / (3.0 * _LAB_DELTA * _LAB_DELTA)


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    arr = np.asarray(rgb, dtype=np.float64)
    return np.where(
        arr <= 0.04045,
        arr / 12.92,
        ((np.maximum(arr, 0.0) + 0.055) / 1.055) ** 2.4,
    )


def linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    arr = np.asarray(rgb, dtype=np.float64)
    return np.where(
        arr <= 0.0031308,
        arr * 12.92,
        1.055 * np.power(np.maximum(arr, 0.0), 1.0 / 2.4) - 0.055,
    )


def _white_point(name: str) -> np.ndarray:
    normalized = name.lower().replace("_", "")
    if normalized == "d50":
        return WHITE_D50
    if normalized == "d65":
        return WHITE_D65
    raise ValueError("white point must be D50 or D65")


def adapt_xyz_white(xyz: np.ndarray, source_white: str, target_white: str) -> np.ndarray:
    source = _white_point(source_white)
    target = _white_point(target_white)
    arr = np.asarray(xyz, dtype=np.float64)
    if np.allclose(source, target):
        return arr.copy()
    source_cone = _BRADFORD @ source
    target_cone = _BRADFORD @ target
    diagonal = np.diag(target_cone / source_cone)
    matrix = _BRADFORD_INV @ diagonal @ _BRADFORD
    return arr @ matrix.T


def xyz_to_lab(xyz: np.ndarray, white: str = "D65") -> np.ndarray:
    arr = np.asarray(xyz, dtype=np.float64)
    white_arr = _white_point(white)
    xyz_n = arr / white_arr
    f = np.where(
        xyz_n > _LAB_DELTA_CUBED,
        np.cbrt(np.maximum(xyz_n, 0.0)),
        xyz_n * _LAB_SCALE + 4.0 / 29.0,
    )
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def lab_to_xyz(lab: np.ndarray, white: str = "D65") -> np.ndarray:
    arr = np.asarray(lab, dtype=np.float64)
    L = arr[..., 0]
    a = arr[..., 1]
    b = arr[..., 2]
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    f = np.stack([fx, fy, fz], axis=-1)
    xyz_n = np.where(
        f > _LAB_DELTA,
        f ** 3,
        (f - 4.0 / 29.0) / _LAB_SCALE,
    )
    return xyz_n * _white_point(white)


def linear_srgb_to_xyz(rgb: np.ndarray) -> np.ndarray:
    arr = np.asarray(rgb, dtype=np.float64)
    return arr @ RGB_TO_XYZ_D65.T


def xyz_to_linear_srgb(xyz: np.ndarray) -> np.ndarray:
    arr = np.asarray(xyz, dtype=np.float64)
    return arr @ XYZ_D65_TO_RGB.T


def linear_srgb_to_lab(rgb: np.ndarray, white: str = "D65") -> np.ndarray:
    xyz_d65 = linear_srgb_to_xyz(np.clip(np.asarray(rgb, dtype=np.float64), 0.0, None))
    if white.lower() == "d50":
        xyz = adapt_xyz_white(xyz_d65, "D65", "D50")
        return xyz_to_lab(xyz, "D50")
    return xyz_to_lab(xyz_d65, "D65")


def lab_to_linear_srgb(lab: np.ndarray, white: str = "D65") -> np.ndarray:
    xyz = lab_to_xyz(lab, white)
    if white.lower() == "d50":
        xyz = adapt_xyz_white(xyz, "D50", "D65")
    return xyz_to_linear_srgb(xyz)


def delta_e_76(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    return np.linalg.norm(np.asarray(lab1, dtype=np.float64) - np.asarray(lab2, dtype=np.float64), axis=-1)


def delta_e_94(lab1: np.ndarray, lab2: np.ndarray, *, graphic_arts: bool = True) -> np.ndarray:
    arr1 = np.asarray(lab1, dtype=np.float64)
    arr2 = np.asarray(lab2, dtype=np.float64)
    k_l = 1.0
    k_1 = 0.045 if graphic_arts else 0.048
    k_2 = 0.015 if graphic_arts else 0.014
    d_l = arr1[..., 0] - arr2[..., 0]
    c1 = np.sqrt(arr1[..., 1] ** 2 + arr1[..., 2] ** 2)
    c2 = np.sqrt(arr2[..., 1] ** 2 + arr2[..., 2] ** 2)
    d_c = c1 - c2
    d_a = arr1[..., 1] - arr2[..., 1]
    d_b = arr1[..., 2] - arr2[..., 2]
    d_h_sq = np.maximum(d_a ** 2 + d_b ** 2 - d_c ** 2, 0.0)
    s_l = 1.0
    s_c = 1.0 + k_1 * c1
    s_h = 1.0 + k_2 * c1
    return np.sqrt((d_l / (k_l * s_l)) ** 2 + (d_c / s_c) ** 2 + d_h_sq / (s_h ** 2))


def delta_e_2000(
    lab1: np.ndarray,
    lab2: np.ndarray,
    kL: float = 1.0,
    kC: float = 1.0,
    kH: float = 1.0,
) -> np.ndarray:
    arr1 = np.asarray(lab1, dtype=np.float64)
    arr2 = np.asarray(lab2, dtype=np.float64)
    L1, a1, b1 = arr1[..., 0], arr1[..., 1], arr1[..., 2]
    L2, a2, b2 = arr2[..., 0], arr2[..., 1], arr2[..., 2]

    C1 = np.sqrt(a1 ** 2 + b1 ** 2)
    C2 = np.sqrt(a2 ** 2 + b2 ** 2)
    C_bar = (C1 + C2) / 2.0
    C_bar_7 = C_bar ** 7
    G = 0.5 * (1.0 - np.sqrt(C_bar_7 / (C_bar_7 + 25.0 ** 7)))

    a1p = a1 * (1.0 + G)
    a2p = a2 * (1.0 + G)
    C1p = np.sqrt(a1p ** 2 + b1 ** 2)
    C2p = np.sqrt(a2p ** 2 + b2 ** 2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0

    dLp = L2 - L1
    dCp = C2p - C1p

    dh_raw = h2p - h1p
    dhp = np.where(dh_raw > 180.0, dh_raw - 360.0, dh_raw)
    dhp = np.where(dh_raw < -180.0, dh_raw + 360.0, dhp)
    zero_mask = (C1p * C2p) == 0.0
    dhp = np.where(zero_mask, 0.0, dhp)
    dHp = 2.0 * np.sqrt(np.maximum(C1p * C2p, 0.0)) * np.sin(np.radians(dhp / 2.0))

    Lbp = (L1 + L2) / 2.0
    Cbp = (C1p + C2p) / 2.0
    h_sum = h1p + h2p
    h_diff_abs = np.abs(h1p - h2p)
    Hbp = np.where(
        zero_mask,
        h_sum,
        np.where(
            h_diff_abs <= 180.0,
            h_sum / 2.0,
            np.where(h_sum < 360.0, (h_sum + 360.0) / 2.0, (h_sum - 360.0) / 2.0),
        ),
    )

    T = (
        1.0
        - 0.17 * np.cos(np.radians(Hbp - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * Hbp))
        + 0.32 * np.cos(np.radians(3.0 * Hbp + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * Hbp - 63.0))
    )

    SL = 1.0 + 0.015 * (Lbp - 50.0) ** 2 / np.sqrt(20.0 + (Lbp - 50.0) ** 2)
    SC = 1.0 + 0.045 * Cbp
    SH = 1.0 + 0.015 * Cbp * T

    Cbp_7 = Cbp ** 7
    RC = 2.0 * np.sqrt(Cbp_7 / (Cbp_7 + 25.0 ** 7))
    d_theta = 30.0 * np.exp(-((Hbp - 275.0) / 25.0) ** 2)
    RT = -np.sin(np.radians(2.0 * d_theta)) * RC

    term_L = dLp / (kL * SL)
    term_C = dCp / (kC * SC)
    term_H = dHp / (kH * SH)
    return np.sqrt(term_L ** 2 + term_C ** 2 + term_H ** 2 + RT * term_C * term_H)


def delta_lch(lab1: np.ndarray, lab2: np.ndarray) -> dict[str, np.ndarray]:
    arr1 = np.asarray(lab1, dtype=np.float64)
    arr2 = np.asarray(lab2, dtype=np.float64)
    c1 = np.sqrt(arr1[..., 1] ** 2 + arr1[..., 2] ** 2)
    c2 = np.sqrt(arr2[..., 1] ** 2 + arr2[..., 2] ** 2)
    d_l = arr2[..., 0] - arr1[..., 0]
    d_c = c2 - c1
    h1 = np.arctan2(arr1[..., 2], arr1[..., 1])
    h2 = np.arctan2(arr2[..., 2], arr2[..., 1])
    d_hue = h2 - h1
    d_hue = np.where(d_hue > np.pi, d_hue - 2.0 * np.pi, d_hue)
    d_hue = np.where(d_hue < -np.pi, d_hue + 2.0 * np.pi, d_hue)
    d_h = 2.0 * np.sqrt(np.maximum(c1 * c2, 0.0)) * np.sin(d_hue / 2.0)
    d_h = np.where((c1 * c2) == 0.0, 0.0, d_h)
    return {"delta_l": d_l, "delta_c": d_c, "delta_h": d_h}


def summarize_values(values: Iterable[float]) -> dict[str, float | None]:
    arr = np.asarray([float(v) for v in values], dtype=np.float64)
    if arr.size == 0:
        return {"mean": None, "median": None, "p95": None, "max": None}
    return {
        "mean": round(float(np.mean(arr)), 4),
        "median": round(float(np.median(arr)), 4),
        "p95": round(float(np.percentile(arr, 95)), 4),
        "max": round(float(np.max(arr)), 4),
    }


def gray_patch_metrics(lab_values: np.ndarray, patch_indices: Iterable[int]) -> dict[str, object]:
    labs = np.asarray(lab_values, dtype=np.float64)
    indices = [int(i) for i in patch_indices]
    if labs.size == 0:
        return {
            "patch_indices": indices,
            "a_abs_max": None,
            "b_abs_max": None,
            "ab_abs_mean": None,
            "l_monotonic": None,
        }
    l_values = labs[:, 0]
    return {
        "patch_indices": indices,
        "a_abs_max": round(float(np.max(np.abs(labs[:, 1]))), 4),
        "b_abs_max": round(float(np.max(np.abs(labs[:, 2]))), 4),
        "ab_abs_mean": round(float(np.mean(np.hypot(labs[:, 1], labs[:, 2]))), 4),
        "l_monotonic": bool(np.all(np.diff(l_values) <= 1e-6) or np.all(np.diff(l_values) >= -1e-6)),
        "l_values": [round(float(v), 4) for v in l_values.tolist()],
    }


def ciede2000_sample_pairs() -> list[tuple[list[float], list[float], float]]:
    return [
        ([50.0000, 2.6772, -79.7751], [50.0000, 0.0000, -82.7485], 2.0425),
        ([50.0000, 3.1571, -77.2803], [50.0000, 0.0000, -82.7485], 2.8615),
        ([50.0000, 2.8361, -74.0200], [50.0000, 0.0000, -82.7485], 3.4412),
        ([50.0000, -1.3802, -84.2814], [50.0000, 0.0000, -82.7485], 1.0000),
    ]
