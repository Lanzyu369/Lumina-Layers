from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np


# ---------------------------------------------------------------------------
# Reference file parsing
# ---------------------------------------------------------------------------

def parse_colorchecker_desc(path: Union[str, Path]) -> Dict[str, Dict[str, List[float]]]:
    text = Path(path).read_text(encoding="utf-8").strip().splitlines()
    result: Dict[str, Dict[str, List[float]]] = {}
    current_label: Optional[str] = None

    for line in text:
        line = line.strip()
        if not line:
            current_label = None
            continue
        if line[0].isdigit() and ". " in line:
            current_label = line.split(". ", 1)[1].rstrip(":")
            result[current_label] = {}
            continue
        if current_label and ":" in line:
            key, values = line.split(":", 1)
            nums = [float(v.strip()) for v in values.strip().strip("[]").split(",") if v.strip()]
            result[current_label][key] = nums

    return result


# ---------------------------------------------------------------------------
# sRGB <-> linear RGB
# ---------------------------------------------------------------------------

def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.float32)
    return np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((np.maximum(rgb, 0.0) + 0.055) / 1.055) ** 2.4,
    )


def linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.float32)
    return np.where(
        rgb <= 0.0031308,
        rgb * 12.92,
        1.055 * np.power(np.maximum(rgb, 0.0), 1.0 / 2.4) - 0.055,
    )


EXPOSURE_ANCHOR_PATCH_INDEX = 22
EXPOSURE_ANCHOR_TARGET_SRGB = 118


# ---------------------------------------------------------------------------
# RGB -> Lab (D65)
# ---------------------------------------------------------------------------

_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float32,
)

_WHITE_D65 = np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
_LAB_DELTA = 6.0 / 29.0
_LAB_DELTA_CUBED = _LAB_DELTA ** 3
_LAB_SCALE = 1.0 / (3.0 * _LAB_DELTA * _LAB_DELTA)


def linear_rgb_to_xyz(linear_rgb: np.ndarray) -> np.ndarray:
    return _RGB_TO_XYZ @ linear_rgb


def xyz_to_lab(xyz: np.ndarray, white: np.ndarray) -> np.ndarray:
    xyz_n = xyz / white
    f = np.where(
        xyz_n > _LAB_DELTA_CUBED,
        np.cbrt(np.maximum(xyz_n, 0.0)),
        xyz_n * _LAB_SCALE + 4.0 / 29.0,
    )
    l = 116.0 * f[1] - 16.0
    a = 500.0 * (f[0] - f[1])
    b = 200.0 * (f[1] - f[2])
    return np.array([l, a, b], dtype=np.float32)


def linear_rgb_to_lab_d65(linear_rgb: np.ndarray) -> List[float]:
    linear = np.clip(np.asarray(linear_rgb, dtype=np.float32), 0.0, 1.0)
    xyz_d65 = linear_rgb_to_xyz(linear)
    lab = xyz_to_lab(xyz_d65, _WHITE_D65)
    return [round(float(v), 2) for v in lab]


def linear_rgb_to_lab_d65_vec(linear_rgb: np.ndarray) -> np.ndarray:
    """Vectorized: input (..., 3) → output (..., 3)."""
    linear = np.clip(np.asarray(linear_rgb, dtype=np.float32), 0.0, 1.0)
    xyz = linear @ _RGB_TO_XYZ.T
    xyz_n = xyz / _WHITE_D65
    f = np.where(
        xyz_n > _LAB_DELTA_CUBED,
        np.cbrt(np.maximum(xyz_n, 0.0)),
        xyz_n * _LAB_SCALE + 4.0 / 29.0,
    )
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1).astype(np.float32)


# ---------------------------------------------------------------------------
# ΔE 2000 (scalar + vectorized)
# ---------------------------------------------------------------------------

def delta_e_2000(
    lab1: np.ndarray,
    lab2: np.ndarray,
    kL: float = 1.0,
    kC: float = 1.0,
    kH: float = 1.0,
) -> float:
    L1, a1, b1 = float(lab1[0]), float(lab1[1]), float(lab1[2])
    L2, a2, b2 = float(lab2[0]), float(lab2[1]), float(lab2[2])

    C1 = math.sqrt(a1 ** 2 + b1 ** 2)
    C2 = math.sqrt(a2 ** 2 + b2 ** 2)
    C_bar = (C1 + C2) / 2.0
    C_bar_7 = C_bar ** 7
    G = 0.5 * (1.0 - math.sqrt(C_bar_7 / (C_bar_7 + 25.0 ** 7)))

    a1p = a1 * (1.0 + G)
    a2p = a2 * (1.0 + G)
    C1p = math.sqrt(a1p ** 2 + b1 ** 2)
    C2p = math.sqrt(a2p ** 2 + b2 ** 2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360.0

    dLp = L2 - L1
    dCp = C2p - C1p

    if C1p * C2p == 0.0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        dhp = h2p - h1p
    elif h2p - h1p > 180.0:
        dhp = h2p - h1p - 360.0
    else:
        dhp = h2p - h1p + 360.0
    dHp = 2.0 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2.0))

    Lbp = (L1 + L2) / 2.0
    Cbp = (C1p + C2p) / 2.0
    if C1p * C2p == 0.0:
        Hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        Hbp = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        Hbp = (h1p + h2p + 360.0) / 2.0
    else:
        Hbp = (h1p + h2p - 360.0) / 2.0

    T = (1.0
         - 0.17 * math.cos(math.radians(Hbp - 30.0))
         + 0.24 * math.cos(math.radians(2.0 * Hbp))
         + 0.32 * math.cos(math.radians(3.0 * Hbp + 6.0))
         - 0.20 * math.cos(math.radians(4.0 * Hbp - 63.0)))

    SL = 1.0 + 0.015 * (Lbp - 50.0) ** 2 / math.sqrt(20.0 + (Lbp - 50.0) ** 2)
    SC = 1.0 + 0.045 * Cbp
    SH = 1.0 + 0.015 * Cbp * T

    Cbp_7 = Cbp ** 7
    RC = 2.0 * math.sqrt(Cbp_7 / (Cbp_7 + 25.0 ** 7))
    d_theta = 30.0 * math.exp(-((Hbp - 275.0) / 25.0) ** 2)
    RT = -math.sin(math.radians(2.0 * d_theta)) * RC

    return math.sqrt(
        (dLp / (kL * SL)) ** 2
        + (dCp / (kC * SC)) ** 2
        + (dHp / (kH * SH)) ** 2
        + RT * (dCp / (kC * SC)) * (dHp / (kH * SH))
    )


def delta_e_2000_vec(
    lab1: np.ndarray,
    lab2: np.ndarray,
    kL: float = 1.0,
    kC: float = 1.0,
    kH: float = 1.0,
) -> np.ndarray:
    """Vectorized ΔE₀₀ for arrays of shape (..., 3) → (...)."""
    lab1 = np.asarray(lab1, dtype=np.float32)
    lab2 = np.asarray(lab2, dtype=np.float32)
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

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


# ---------------------------------------------------------------------------
# Root-polynomial features (Finlayson 2015)
# ---------------------------------------------------------------------------
# Degree-3 root polynomial: 13 terms that are jointly scale-invariant.
#   phi(R,G,B) = [R, G, B,
#                sqrt(R*G), sqrt(G*B), sqrt(R*B),
#                cbrt(R*R*G), cbrt(R*G*G),
#                cbrt(R*R*B), cbrt(R*B*B),
#                cbrt(G*G*B), cbrt(G*B*B),
#                cbrt(R*G*B)]
# Property: phi(k*x) = k*phi(x), so exposure scaling commutes with the model.

ROOT_POLY_TERM_COUNT = 13


def root_poly_features(linear_rgb: np.ndarray) -> np.ndarray:
    rgb = np.maximum(np.asarray(linear_rgb, dtype=np.float32), 0.0)
    R = rgb[..., 0]
    G = rgb[..., 1]
    B = rgb[..., 2]
    features = np.stack(
        [
            R,
            G,
            B,
            np.sqrt(R * G),
            np.sqrt(G * B),
            np.sqrt(R * B),
            np.cbrt(R * R * G),
            np.cbrt(R * G * G),
            np.cbrt(R * R * B),
            np.cbrt(R * B * B),
            np.cbrt(G * G * B),
            np.cbrt(G * B * B),
            np.cbrt(R * G * B),
        ],
        axis=-1,
    )
    return features.astype(np.float32)


# ---------------------------------------------------------------------------
# Gray-axis preprocessing (per-channel affine: alpha*m + beta = r)
# ---------------------------------------------------------------------------

def _is_near_neutral(lab: Optional[List[float]], threshold: float = 5.0) -> bool:
    if lab is None or len(lab) < 3:
        return False
    return abs(float(lab[1])) < threshold and abs(float(lab[2])) < threshold


def solve_gray_axis(
    gray_measured_linear: np.ndarray,
    gray_reference_linear: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Per-channel affine fit on the neutral patches.

    We model ``adjusted = wb_gain * (measured - black_level)``. For each
    channel this is equivalent to ``alpha * m + beta = r`` with
    ``alpha = wb_gain`` and ``beta = -wb_gain * black_level``. Solving via
    weighted least squares on the N neutral patches recovers both exposure
    gain and flare/black-level in one step.
    """
    wb_gain = np.ones(3, dtype=np.float32)
    black_level = np.zeros(3, dtype=np.float32)
    n = gray_measured_linear.shape[0]
    if n < 2:
        return wb_gain, black_level
    for c in range(3):
        m = gray_measured_linear[:, c].astype(np.float64)
        r = gray_reference_linear[:, c].astype(np.float64)
        A = np.column_stack([m, np.ones_like(m)])
        coef, *_ = np.linalg.lstsq(A, r, rcond=None)
        alpha, beta = float(coef[0]), float(coef[1])
        if alpha <= 1e-6:
            continue
        wb_gain[c] = alpha
        black_level[c] = max(0.0, -beta / alpha)
    return wb_gain, black_level


# ---------------------------------------------------------------------------
# Per-patch weighting
# ---------------------------------------------------------------------------

def _perceptual_weights(reference_linear: np.ndarray) -> np.ndarray:
    """Emphasize darker patches so that linear-RGB residuals track perceptual
    ΔE more closely. The L* curve is ~cbrt(Y), so 1/cbrt(Y) is the natural
    inverse weighting, clipped at a floor to keep near-black patches from
    dominating the fit."""
    lum = (
        0.2126 * reference_linear[:, 0]
        + 0.7152 * reference_linear[:, 1]
        + 0.0722 * reference_linear[:, 2]
    )
    lum_safe = np.maximum(lum, 0.05).astype(np.float32)
    w = 1.0 / np.cbrt(lum_safe)
    return (w / w.mean()).astype(np.float32)


# ---------------------------------------------------------------------------
# Calibration profile fitting
# ---------------------------------------------------------------------------

def _patch_measured_linear(measured: Dict[str, Any]) -> Optional[np.ndarray]:
    lin = measured.get("linear_rgb") if isinstance(measured, dict) else None
    if lin is not None and len(lin) >= 3:
        return np.asarray(lin, dtype=np.float32)[:3]
    srgb = measured.get("sRGB") if isinstance(measured, dict) else None
    if srgb is not None and len(srgb) >= 3:
        return srgb_to_linear(np.asarray(srgb, dtype=np.float32)[:3] / 255.0).astype(np.float32)
    return None


def _patch_index(measured: Dict[str, Any]) -> Optional[int]:
    raw = measured.get("index") if isinstance(measured, dict) else None
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _linear_luminance(rgb: np.ndarray) -> float:
    arr = np.asarray(rgb, dtype=np.float32)
    return float(0.2126 * arr[0] + 0.7152 * arr[1] + 0.0722 * arr[2])


def _compute_output_gain(
    pairs: List[Tuple[str, int, np.ndarray, np.ndarray, Optional[np.ndarray]]],
    corrected_linear: np.ndarray,
    *,
    preserve_exposure: bool,
    exposure_anchor_patch_index: int,
    exposure_anchor_target_srgb: int,
) -> float:
    if preserve_exposure:
        return 1.0
    target_linear = float(
        srgb_to_linear(np.asarray([exposure_anchor_target_srgb / 255.0], dtype=np.float32))[0]
    )
    for row_index, (_label, patch_index, _measured, _reference, _lab) in enumerate(pairs):
        if patch_index != exposure_anchor_patch_index:
            continue
        current_linear = _linear_luminance(corrected_linear[row_index])
        if current_linear <= 1e-6:
            return 1.0
        return float(np.clip(target_linear / current_linear, 0.25, 4.0))
    return 1.0


def compute_calibration_profile(
    patch_colors: Dict[str, Dict[str, Any]],
    reference_colors: Dict[str, Dict[str, List[float]]],
    *,
    model: str = "root_poly",
    optimize_delta_e: bool = False,
    weights: str = "perceptual",
    prewhite_balance: bool = True,
    regularization: float = 1e-3,
    preserve_exposure: bool = False,
    exposure_anchor_patch_index: int = EXPOSURE_ANCHOR_PATCH_INDEX,
    exposure_anchor_target_srgb: int = EXPOSURE_ANCHOR_TARGET_SRGB,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Fit a calibration profile.

    Returns ``(profile, stats)``. Profile is a JSON-serializable dict with
    keys: ``model``, ``wb_gain`` (3,), ``black_level`` (3,), ``matrix``
    ((3,3) or (13,3)), ``offset`` (3,).

    ``regularization`` is a Tikhonov (ridge) L2 penalty applied to the
    matrix coefficients during LS (and during the optional ΔE₀₀ refine).
    This is critical for the root-polynomial model, which otherwise
    overfits 24 patches with 39 parameters and produces coefficients
    ±O(30) that blow up image noise. Default 1e-3 is a mild safety net
    that shrinks pathological coefficients without visibly hurting
    ColorChecker ΔE₀₀.

    ``preserve_exposure``: when ``True``, the user is asserting that the
    input image is already correctly exposed (e.g. exposure was matched
    in Camera Raw before upload). The gray-axis solver still produces
    ``wb_gain`` and ``black_level``, but we then split ``wb_gain`` into
    a scalar exposure component ``K = geomean(wb_gain)`` and a unit
    channel-balance component ``wb_gain / K``. We keep only the
    channel-balance and scale the regression target reference colors by
    ``1/K``. The fitted matrix therefore performs *only* hue/saturation
    rotation, not brightness compensation, and the corrected output
    inherits the input's brightness. This is the equivalent of skipping
    the post-profile Photoshop Levels stretch from the standard
    Calibrite/X-Rite workflow ("apply profile only, don't re-pull white
    point"). When the input really is correctly exposed, ``K ≈ 1`` and
    behavior matches the default. When the input is under/overexposed,
    the output stays under/overexposed but with correct hue.
    """
    if model not in ("linear", "root_poly"):
        raise ValueError(f"Unsupported model: {model}")
    if weights not in ("uniform", "perceptual"):
        raise ValueError(f"Unsupported weights mode: {weights}")
    if regularization < 0.0:
        raise ValueError("regularization must be non-negative")

    pairs: List[Tuple[str, int, np.ndarray, np.ndarray, Optional[np.ndarray]]] = []
    gray_measured: List[np.ndarray] = []
    gray_reference: List[np.ndarray] = []
    for label, measured in patch_colors.items():
        ref = reference_colors.get(label)
        if not ref:
            continue
        ref_srgb = ref.get("sRGB")
        if not ref_srgb or len(ref_srgb) < 3:
            continue
        meas_linear = _patch_measured_linear(measured)
        if meas_linear is None:
            continue
        ref_linear = srgb_to_linear(
            np.asarray(ref_srgb, dtype=np.float32)[:3] / 255.0
        ).astype(np.float32)
        ref_lab_raw = ref.get("Lab_d65")
        ref_lab_arr = (
            np.asarray(ref_lab_raw, dtype=np.float32)[:3]
            if ref_lab_raw is not None and len(ref_lab_raw) >= 3
            else None
        )
        pairs.append((label, int(_patch_index(measured) or 0), meas_linear, ref_linear, ref_lab_arr))
        if _is_near_neutral(ref_lab_raw):
            gray_measured.append(meas_linear)
            gray_reference.append(ref_linear)

    if len(pairs) < 4:
        raise ValueError("Not enough ColorChecker patches for calibration.")

    if prewhite_balance and len(gray_measured) >= 2:
        wb_gain, black_level = solve_gray_axis(
            np.stack(gray_measured, axis=0),
            np.stack(gray_reference, axis=0),
        )
    else:
        wb_gain = np.ones(3, dtype=np.float32)
        black_level = np.zeros(3, dtype=np.float32)

    # Split wb_gain into "scalar exposure" (K) × "channel balance ratio".
    # When preserve_exposure=True we drop K from wb_gain and scale the
    # regression target reference colors by 1/K so that the fitted matrix
    # only performs color rotation, not exposure compensation. K=1 (i.e.
    # input was correctly exposed) means this is a no-op.
    exposure_scalar = 1.0
    if preserve_exposure and prewhite_balance and len(gray_measured) >= 2:
        prod = float(np.prod(np.maximum(wb_gain, 1e-9)))
        exposure_scalar = float(prod ** (1.0 / 3.0))
        if exposure_scalar > 1e-6:
            wb_gain = (wb_gain / exposure_scalar).astype(np.float32)
        else:
            exposure_scalar = 1.0

    measured_arr = np.stack([p[2] for p in pairs], axis=0).astype(np.float32)
    reference_arr_orig = np.stack([p[3] for p in pairs], axis=0).astype(np.float32)
    if exposure_scalar != 1.0:
        reference_arr = (reference_arr_orig / exposure_scalar).astype(np.float32)
    else:
        reference_arr = reference_arr_orig
    adjusted = np.maximum(measured_arr - black_level, 0.0) * wb_gain

    if weights == "perceptual":
        w_vec = _perceptual_weights(reference_arr)
    else:
        w_vec = np.ones(len(pairs), dtype=np.float32)
    w_sqrt = np.sqrt(w_vec)[:, None]

    lam_sqrt = float(np.sqrt(max(regularization, 0.0)))

    if model == "linear":
        ones = np.ones((adjusted.shape[0], 1), dtype=np.float32)
        design_w = np.hstack([adjusted, ones]) * w_sqrt
        target_w = reference_arr * w_sqrt
        if lam_sqrt > 0.0:
            # Regularize the 3x3 color-mixing block but leave the bias
            # (offset) column unpenalized.
            reg_rows = np.zeros((3, 4), dtype=np.float32)
            reg_rows[:3, :3] = lam_sqrt * np.eye(3, dtype=np.float32)
            reg_target = np.zeros((3, 3), dtype=np.float32)
            design_w = np.vstack([design_w, reg_rows])
            target_w = np.vstack([target_w, reg_target])
        coef, *_ = np.linalg.lstsq(design_w, target_w, rcond=None)
        matrix = coef[:3].astype(np.float32)
        offset = coef[3].astype(np.float32)
    else:
        features = root_poly_features(adjusted)
        design_w = features * w_sqrt
        target_w = reference_arr * w_sqrt
        if lam_sqrt > 0.0:
            # Ridge on all 13 root-polynomial rows. This is what tames the
            # ±O(30) coefficients seen on real underexposed ColorChecker
            # shots where the 13 features are near-collinear.
            reg_rows = lam_sqrt * np.eye(ROOT_POLY_TERM_COUNT, dtype=np.float32)
            reg_target = np.zeros((ROOT_POLY_TERM_COUNT, 3), dtype=np.float32)
            design_w = np.vstack([design_w, reg_rows])
            target_w = np.vstack([target_w, reg_target])
        coef, *_ = np.linalg.lstsq(design_w, target_w, rcond=None)
        matrix = coef.astype(np.float32)
        offset = np.zeros(3, dtype=np.float32)

    refine_info: Optional[Dict[str, Any]] = None
    # Targets (in linear-RGB and Lab) for fitting and evaluation.
    # In preserve_exposure mode these are the *scaled* references, so the
    # ΔE we report is the residual color error at the user's exposure
    # level — apples to apples vs. the matrix's actual fit objective.
    target_linear_clipped = np.clip(reference_arr, 0.0, 1.0)
    target_lab_arr = linear_rgb_to_lab_d65_vec(target_linear_clipped)

    if optimize_delta_e:
        matrix, offset, refine_info = _refine_with_delta_e(
            matrix,
            offset,
            adjusted=adjusted,
            ref_lab_list=[target_lab_arr[i] for i in range(len(pairs))],
            weights=w_vec,
            model=model,
            regularization=regularization,
        )

    profile: Dict[str, Any] = {
        "model": model,
        "wb_gain": [float(v) for v in wb_gain.tolist()],
        "black_level": [float(v) for v in black_level.tolist()],
        "matrix": [[float(v) for v in row] for row in matrix.tolist()],
        "offset": [float(v) for v in offset.tolist()],
    }

    corrected_linear = _apply_matrix(adjusted, matrix, offset, model)
    output_gain = _compute_output_gain(
        pairs,
        corrected_linear,
        preserve_exposure=preserve_exposure,
        exposure_anchor_patch_index=exposure_anchor_patch_index,
        exposure_anchor_target_srgb=exposure_anchor_target_srgb,
    )
    corrected_linear = corrected_linear * output_gain
    corrected_linear_clipped = np.clip(corrected_linear, 0.0, 1.0)
    corrected_lab = linear_rgb_to_lab_d65_vec(corrected_linear_clipped)
    errors: List[float] = []
    gray_chroma_vals: List[float] = []
    for i, (_label, _pidx, _m, _r, ref_lab_orig) in enumerate(pairs):
        if ref_lab_orig is None:
            continue
        target_lab = target_lab_arr[i]
        errors.append(float(delta_e_2000(corrected_lab[i], target_lab)))
        if abs(float(ref_lab_orig[1])) < 5.0 and abs(float(ref_lab_orig[2])) < 5.0:
            a_corr = float(corrected_lab[i, 1])
            b_corr = float(corrected_lab[i, 2])
            gray_chroma_vals.append(float(np.hypot(a_corr, b_corr)))

    profile["output_gain"] = float(output_gain)

    stats: Dict[str, Any] = {
        "patch_count": int(len(pairs)),
        "model": model,
        "weights": weights,
        "optimize_delta_e": bool(optimize_delta_e),
        "gray_patch_count": int(len(gray_measured)),
        "prewhite_balance": bool(prewhite_balance and len(gray_measured) >= 2),
        "preserve_exposure": bool(preserve_exposure),
        "exposure_scalar": round(float(exposure_scalar), 4),
        "output_gain": round(float(output_gain), 4),
        "exposure_anchor_patch_index": int(exposure_anchor_patch_index),
        "exposure_anchor_target_srgb": int(exposure_anchor_target_srgb),
        "regularization": float(regularization),
        "matrix_max_abs": round(float(np.max(np.abs(matrix))), 4),
        "matrix_rms": round(float(np.sqrt(np.mean(matrix ** 2))), 4),
    }
    if errors:
        stats["mean_delta_e"] = round(float(np.mean(errors)), 4)
        stats["max_delta_e"] = round(float(np.max(errors)), 4)
        stats["median_delta_e"] = round(float(np.median(errors)), 4)
    if gray_chroma_vals:
        stats["gray_neutral_chroma_mean"] = round(float(np.mean(gray_chroma_vals)), 4)
        stats["gray_neutral_chroma_max"] = round(float(np.max(gray_chroma_vals)), 4)
    if refine_info is not None:
        stats["delta_e_refine"] = refine_info
    return profile, stats


def _apply_matrix(
    adjusted: np.ndarray,
    matrix: np.ndarray,
    offset: np.ndarray,
    model: str,
) -> np.ndarray:
    if model == "linear":
        return adjusted @ matrix + offset
    return root_poly_features(adjusted) @ matrix


GRID_SEARCH_MODELS = ("linear", "root_poly")
GRID_SEARCH_WEIGHTS = ("uniform", "perceptual")
# Always use the gray-axis pre-white-balance step when neutral patches are
# available. Letting the matrix absorb exposure / WB compensation can score
# slightly better on the 24 calibration patches but produces a profile that
# couples color rotation with exposure scaling — pushing bright in-image
# pixels past 1.0 (the overexposure complaint), and silently making the
# matrix non-portable to other shots of the same scene.
GRID_SEARCH_PREWHITE = (True,)
GRID_SEARCH_REGULARIZATIONS = (0.0, 1e-4, 1e-3, 1e-2, 1e-1)


def _grid_score(stats: Dict[str, Any]) -> float:
    """Composite lower-is-better score balancing accuracy + WB + stability.

    - Accuracy: mean ΔE₀₀ across all 24 patches.
    - **White-balance correctness**: mean Lab chroma √(a²+b²) on the 6
      neutral patches after correction. This is the direct measure of
      "is the grey card actually grey?" and answers the user's question
      "now is the highest-ranked profile the one with the correct white
      balance?" Without this term, mean ΔE alone gives the 6 grays only
      6/24 = 25% influence; a profile with great colored-patch fit but a
      mild gray cast can still win on ΔE alone.
    - Outliers: max ΔE₀₀ above 6.0 is penalized (one badly-rendered
      color in the image).
    - Worst-gray: max gray chroma above 3.0 (= "obvious cast on at
      least one shade of grey") is penalized.
    - Stability: matrix rms above 0.5 is penalized (high-magnitude
      coefficients amplify sensor noise in the output).
    - Hard gate: a root-polynomial fit whose max |coef| exceeds 15 is
      rejected outright (pathological overfits).
    """
    mean_de = stats.get("mean_delta_e")
    if mean_de is None:
        return float("inf")
    max_de = stats.get("max_delta_e", mean_de)
    rms = stats.get("matrix_rms", 0.0)
    max_abs = stats.get("matrix_max_abs", 0.0)
    model = stats.get("model", "linear")
    if model == "root_poly" and max_abs > 15.0:
        return float("inf")
    gray_chroma_mean = float(stats.get("gray_neutral_chroma_mean", 0.0) or 0.0)
    gray_chroma_max = float(stats.get("gray_neutral_chroma_max", 0.0) or 0.0)
    wb_penalty = 1.0 * gray_chroma_mean
    worst_gray_penalty = 0.4 * max(0.0, gray_chroma_max - 3.0)
    outlier_penalty = 0.2 * max(0.0, float(max_de) - 6.0)
    stability_penalty = 0.3 * max(0.0, float(rms) - 0.5)
    return round(
        float(mean_de)
        + wb_penalty
        + worst_gray_penalty
        + outlier_penalty
        + stability_penalty,
        4,
    )


def calibrate_with_grid_search(
    patch_colors: Dict[str, Dict[str, Any]],
    reference_colors: Dict[str, Dict[str, List[float]]],
    *,
    optimize_delta_e: bool = False,
    preserve_exposure: bool = False,
    exposure_anchor_patch_index: int = EXPOSURE_ANCHOR_PATCH_INDEX,
    exposure_anchor_target_srgb: int = EXPOSURE_ANCHOR_TARGET_SRGB,
    top_k: int = 8,
) -> Dict[str, Any]:
    """Evaluate every (model × weights × prewhite × regularization) combo
    and rank by :func:`_grid_score`. ``preserve_exposure`` propagates
    into every candidate so the entire grid is fit under the same
    "rotate-only vs. rotate+rescale" assumption — the user's toggle
    selects which regime the search operates in, rather than mixing
    ranks across regimes (which would not be apples-to-apples since
    preserve_exposure mode evaluates ΔE on scaled targets).
    """
    candidates: List[Dict[str, Any]] = []
    for model in GRID_SEARCH_MODELS:
        for weights in GRID_SEARCH_WEIGHTS:
            for prewhite in GRID_SEARCH_PREWHITE:
                for lam in GRID_SEARCH_REGULARIZATIONS:
                    try:
                        profile, stats = compute_calibration_profile(
                            patch_colors,
                            reference_colors,
                            model=model,
                            weights=weights,
                            prewhite_balance=prewhite,
                            optimize_delta_e=optimize_delta_e,
                            regularization=lam,
                            preserve_exposure=preserve_exposure,
                            exposure_anchor_patch_index=exposure_anchor_patch_index,
                            exposure_anchor_target_srgb=exposure_anchor_target_srgb,
                        )
                    except (ValueError, TypeError, np.linalg.LinAlgError):
                        continue
                    config = {
                        "model": model,
                        "weights": weights,
                        "prewhite_balance": bool(prewhite),
                        "regularization": float(lam),
                        "optimize_delta_e": bool(optimize_delta_e),
                        "preserve_exposure": bool(preserve_exposure),
                    }
                    candidates.append(
                        {
                            "config": config,
                            "profile": profile,
                            "stats": stats,
                            "score": _grid_score(stats),
                        }
                    )

    if not candidates:
        raise ValueError("网格搜索没有产出任何有效解。")

    candidates.sort(key=lambda c: c["score"])
    best = candidates[0]

    def _summary(c: Dict[str, Any]) -> Dict[str, Any]:
        s = c["stats"]
        return {
            "config": c["config"],
            "score": c["score"],
            "mean_delta_e": s.get("mean_delta_e"),
            "median_delta_e": s.get("median_delta_e"),
            "max_delta_e": s.get("max_delta_e"),
            "matrix_max_abs": s.get("matrix_max_abs"),
            "matrix_rms": s.get("matrix_rms"),
            "gray_neutral_chroma_mean": s.get("gray_neutral_chroma_mean"),
            "gray_neutral_chroma_max": s.get("gray_neutral_chroma_max"),
        }

    return {
        "best": best,
        "candidates": [_summary(c) for c in candidates[:top_k]],
        "total": len(candidates),
    }


def _refine_with_delta_e(
    matrix_init: np.ndarray,
    offset_init: np.ndarray,
    *,
    adjusted: np.ndarray,
    ref_lab_list: List[Optional[np.ndarray]],
    weights: np.ndarray,
    model: str,
    regularization: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    try:
        from scipy.optimize import least_squares  # type: ignore
    except ImportError as exc:
        raise ValueError(
            "ΔE₀₀ 优化需要 scipy，请先执行 pip install scipy 或 pip install -r requirements.txt。"
        ) from exc

    mask = np.array([lab is not None for lab in ref_lab_list])
    if not mask.any():
        return matrix_init, offset_init, {"status": "no_reference_lab"}
    indices = np.where(mask)[0]
    adjusted_use = adjusted[indices]
    ref_lab_use = np.stack([ref_lab_list[i] for i in indices], axis=0).astype(np.float32)
    weights_use = weights[indices].astype(np.float32)

    features_use = root_poly_features(adjusted_use) if model == "root_poly" else None
    lam_sqrt = float(np.sqrt(max(regularization, 0.0)))

    if model == "linear":
        n_matrix = 9
        x0 = np.concatenate([matrix_init.ravel(), offset_init.ravel()]).astype(np.float64)

        def unpack(params: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
            return params[:n_matrix].reshape(3, 3).astype(np.float32), params[n_matrix:].astype(np.float32)
    else:
        x0 = matrix_init.ravel().astype(np.float64)

        def unpack(params: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
            return params.reshape(ROOT_POLY_TERM_COUNT, 3).astype(np.float32), np.zeros(3, dtype=np.float32)

    def data_residuals(params: np.ndarray) -> np.ndarray:
        matrix, offset = unpack(params)
        if model == "linear":
            pred_linear = adjusted_use @ matrix + offset
        else:
            pred_linear = features_use @ matrix
        pred_linear = np.clip(pred_linear, 0.0, 1.0)
        pred_lab = linear_rgb_to_lab_d65_vec(pred_linear)
        de = delta_e_2000_vec(pred_lab, ref_lab_use)
        return (de * weights_use).astype(np.float64)

    def residuals(params: np.ndarray) -> np.ndarray:
        data = data_residuals(params)
        if lam_sqrt <= 0.0:
            return data
        matrix, _ = unpack(params)
        reg = lam_sqrt * matrix.ravel().astype(np.float64)
        return np.concatenate([data, reg])

    de_before = data_residuals(x0) / np.maximum(weights_use, 1e-6)
    mean_before = float(np.mean(de_before))
    max_before = float(np.max(de_before))

    result = least_squares(
        residuals,
        x0,
        method="trf",
        max_nfev=600,
        xtol=1e-9,
        ftol=1e-9,
        gtol=1e-9,
    )

    de_after = data_residuals(result.x) / np.maximum(weights_use, 1e-6)
    mean_after = float(np.mean(de_after))
    max_after = float(np.max(de_after))

    matrix_new, offset_new = unpack(result.x)
    info: Dict[str, Any] = {
        "iterations": int(result.nfev),
        "status": int(result.status),
        "mean_delta_e_before": round(mean_before, 4),
        "mean_delta_e_after": round(mean_after, 4),
        "max_delta_e_before": round(max_before, 4),
        "max_delta_e_after": round(max_after, 4),
    }
    if mean_after > mean_before:
        return matrix_init, offset_init, {**info, "accepted": False}
    info["accepted"] = True
    return matrix_new, offset_new, info


# ---------------------------------------------------------------------------
# Profile application
# ---------------------------------------------------------------------------

def _profile_arrays(
    profile: Dict[str, Any],
) -> Tuple[str, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    model = str(profile.get("model") or "linear")
    wb = np.asarray(profile.get("wb_gain") or [1.0, 1.0, 1.0], dtype=np.float32)
    black = np.asarray(profile.get("black_level") or [0.0, 0.0, 0.0], dtype=np.float32)
    matrix = np.asarray(profile.get("matrix"), dtype=np.float32)
    offset = np.asarray(profile.get("offset") or [0.0, 0.0, 0.0], dtype=np.float32)
    output_gain = np.asarray([float(profile.get("output_gain") or 1.0)], dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[1] != 3:
        raise ValueError(f"Invalid profile matrix shape: {matrix.shape}")
    return model, wb, black, matrix, offset, output_gain


def apply_profile_to_linear(
    linear_rgb: np.ndarray,
    profile: Dict[str, Any],
) -> np.ndarray:
    """Apply the calibration profile to linear-RGB data of shape (..., 3)."""
    model, wb, black, matrix, offset, output_gain = _profile_arrays(profile)
    adjusted = np.maximum(linear_rgb - black, 0.0) * wb
    if model == "linear":
        return (adjusted @ matrix + offset) * output_gain
    if model == "root_poly":
        return (root_poly_features(adjusted) @ matrix) * output_gain
    raise ValueError(f"Unknown model: {model}")


DEFAULT_HIGHLIGHT_KNEE = 0.85


def soft_clip_highlights(linear: np.ndarray, knee: float) -> np.ndarray:
    """Hue-preserving smooth highlight rolloff.

    The CCM is fit on patch values roughly in ``[0, 0.86]`` linear, so any
    pixel brighter than the white patch (specular highlights, sky, etc.)
    is extrapolated and frequently overshoots 1.0. A hard ``np.clip`` to
    1.0 then renders the region as flat white. A naive per-channel rolloff
    looks slightly better but still flattens hue when *all* channels
    overshoot (e.g. a red-tinted spec going from ``[2.2, 2.0, 1.8]`` to
    ``[~1, ~1, ~1]`` — the red tint is lost).

    Instead we work on the per-pixel peak channel:

        peak  = max(R, G, B)
        peak' = knee + (1 - knee) * tanh((peak - knee) / (1 - knee))   for peak > knee
        peak' = peak                                                   otherwise
        scale = peak' / peak                                           (1.0 if peak <= knee)
        result = linear * scale

    This compresses the brightness while preserving the RGB ratio, which
    keeps the hue/saturation of in-image highlights intact. ``knee >= 1.0``
    disables the rolloff (legacy hard-clip behavior). Negative inputs are
    clamped to 0.
    """
    knee = float(np.clip(knee, 0.0, 1.0))
    out = np.maximum(linear, 0.0).astype(np.float32, copy=True)
    if knee >= 1.0:
        return np.minimum(out, 1.0)
    peak = np.max(out, axis=-1, keepdims=True)
    over = peak > knee
    if not np.any(over):
        return np.minimum(out, 1.0)
    scale_range = 1.0 - knee
    new_peak = peak.copy()
    u = (peak - knee) / scale_range
    compressed = knee + scale_range * np.tanh(u)
    new_peak = np.where(over, compressed, peak)
    safe_peak = np.where(peak > 1e-6, peak, 1.0)
    ratio = new_peak / safe_peak
    out = out * ratio
    return np.minimum(out, 1.0)


_soft_clip_highlights = soft_clip_highlights


def apply_profile_to_image_bgr(
    image_bgr: np.ndarray,
    profile: Dict[str, Any],
    *,
    chunk_rows: int = 512,
    highlight_knee: float = DEFAULT_HIGHLIGHT_KNEE,
) -> np.ndarray:
    """Apply the profile to an sRGB-encoded BGR image.

    Accepts uint8 or uint16 input; returns uint8 BGR. Processing is chunked
    along rows for the root-poly model to cap peak memory on large images.

    ``highlight_knee`` controls the per-channel highlight rolloff applied
    after the matrix. ``1.0`` disables it (legacy hard-clip behavior);
    smaller values protect highlights more aggressively. The default
    ``0.85`` keeps everything below the white-patch level untouched and
    smoothly compresses the rest into ``[0.85, 1.0]``.
    """
    if image_bgr.dtype == np.uint16:
        max_val = 65535.0
    else:
        max_val = 255.0
    rgb = image_bgr[..., ::-1].astype(np.float32) / max_val
    linear_rgb = srgb_to_linear(rgb)

    model = str(profile.get("model") or "linear")
    if model == "root_poly" and linear_rgb.ndim == 3:
        corrected = np.empty_like(linear_rgb)
        height = linear_rgb.shape[0]
        step = max(1, int(chunk_rows))
        for y0 in range(0, height, step):
            y1 = min(y0 + step, height)
            corrected[y0:y1] = apply_profile_to_linear(linear_rgb[y0:y1], profile)
    else:
        corrected = apply_profile_to_linear(linear_rgb, profile)

    corrected = soft_clip_highlights(corrected, highlight_knee)
    srgb = linear_to_srgb(corrected)
    out = np.clip(srgb * 255.0, 0, 255).astype(np.uint8)
    return out[..., ::-1]


# ---------------------------------------------------------------------------
# Backwards-compatible thin wrappers
# ---------------------------------------------------------------------------

def compute_ccm_from_colorchecker(
    patch_colors: Dict[str, Dict[str, Any]],
    reference_colors: Dict[str, Dict[str, List[float]]],
) -> Tuple[np.ndarray, Dict[str, Any]]:
    pairs: List[Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]] = []
    for label, measured in patch_colors.items():
        ref = reference_colors.get(label)
        if not ref:
            continue
        ref_srgb = ref.get("sRGB")
        meas_srgb = measured.get("sRGB")
        if not ref_srgb or not meas_srgb:
            continue
        meas_linear = srgb_to_linear(np.array(meas_srgb, dtype=np.float32) / 255.0)
        ref_linear = srgb_to_linear(np.array(ref_srgb, dtype=np.float32) / 255.0)
        ref_lab = ref.get("Lab_d65")
        ref_lab_arr = np.array(ref_lab, dtype=np.float32) if ref_lab is not None else None
        pairs.append((meas_linear, ref_linear, ref_lab_arr))

    if len(pairs) < 3:
        raise ValueError("Not enough ColorChecker patches for calibration.")

    measured_arr = np.stack([item[0] for item in pairs], axis=0)
    reference_arr = np.stack([item[1] for item in pairs], axis=0)
    ccm = np.linalg.lstsq(measured_arr, reference_arr, rcond=None)[0]

    errors: List[float] = []
    for meas_linear, _, ref_lab in pairs:
        if ref_lab is None:
            continue
        corrected = np.clip(meas_linear @ ccm, 0.0, 1.0)
        lab = np.array(linear_rgb_to_lab_d65(corrected), dtype=np.float32)
        errors.append(float(np.linalg.norm(lab - ref_lab)))

    stats: Dict[str, Any] = {"patch_count": int(len(pairs))}
    if errors:
        stats["mean_delta_e"] = round(float(np.mean(errors)), 4)
        stats["max_delta_e"] = round(float(np.max(errors)), 4)
    return ccm, stats


def apply_ccm_to_image(
    image_bgr: np.ndarray,
    ccm: np.ndarray,
    *,
    chunk_rows: int = 512,
) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    result = np.empty((h, w, 3), dtype=np.uint8)
    for y0 in range(0, h, chunk_rows):
        y1 = min(y0 + chunk_rows, h)
        chunk = image_bgr[y0:y1, :, ::-1].astype(np.float32) / 255.0
        chunk = srgb_to_linear(chunk)
        chunk = np.clip(chunk @ ccm, 0.0, 1.0)
        chunk = linear_to_srgb(chunk)
        result[y0:y1] = np.clip(chunk * 255.0, 0, 255).astype(np.uint8)[..., ::-1]
    return result

