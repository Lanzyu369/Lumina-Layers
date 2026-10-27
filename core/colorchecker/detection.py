from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

from .image_io import image_to_uint8_display
from .pipeline import order_quad

PatchLayout = Literal["4x6", "3x8"]
PatchOrientation = Literal["normal", "rotate_180", "flip_horizontal", "flip_vertical"]

ORIENTATIONS: tuple[PatchOrientation, ...] = (
    "normal",
    "rotate_180",
    "flip_horizontal",
    "flip_vertical",
)
AUTO_SCORE_THRESHOLD = 0.19
ASSIST_SCORE_THRESHOLD = 0.22
MIN_MARGIN = 0.018


@dataclass(frozen=True)
class ChartDetectionResult:
    detected: bool
    corners: list[dict[str, float]]
    patch_orientation: PatchOrientation
    confidence: float
    score: float | None
    mode: Literal["auto", "assist"]
    reason: str
    candidate_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "detected": self.detected,
            "corners": self.corners,
            "patchOrientation": self.patch_orientation,
            "confidence": round(float(self.confidence), 4),
            "score": None if self.score is None else round(float(self.score), 6),
            "mode": self.mode,
            "reason": self.reason,
            "candidateCount": int(self.candidate_count),
        }


@dataclass(frozen=True)
class _ScoredCandidate:
    corners: np.ndarray
    orientation: PatchOrientation
    score: float
    direct_lab_score: float


def detect_colorchecker_chart(
    image: np.ndarray,
    reference_patches: list[dict[str, object]],
    *,
    patch_layout: PatchLayout = "4x6",
    assist_point: dict[str, float] | None = None,
    max_dimension: int = 1200,
) -> ChartDetectionResult:
    rows, cols = _layout_spec(patch_layout)
    mode: Literal["auto", "assist"] = "assist" if assist_point else "auto"
    if len(reference_patches) < rows * cols:
        return _failure(mode, "参考色块数量不足，无法定位。", 0)

    display = image_to_uint8_display(np.asarray(image))
    if display.ndim != 3 or display.shape[2] != 3 or display.size == 0:
        return _failure(mode, "图片格式无效，无法定位。", 0)

    resized, scale = _resize_for_detection(display, max_dimension=max_dimension)
    reference_bgr = _reference_bgr(reference_patches[: rows * cols])
    reference_lab = _bgr_samples_to_lab(reference_bgr)
    mask = _reference_color_mask(resized, reference_lab)
    candidates = _candidate_quads(
        resized,
        mask,
        rows=rows,
        cols=cols,
        assist_point=assist_point,
        scale=scale,
    )
    if not candidates:
        return _failure(mode, "未找到接近色卡形状的候选区域。", 0)

    scored = [
        score
        for candidate in candidates
        if (
            score := _score_candidate(
                resized,
                candidate,
                reference_bgr,
                rows=rows,
                cols=cols,
            )
        )
        is not None
    ]
    if not scored:
        return _failure(mode, "候选区域无法完成有效采样。", len(candidates))

    scored.sort(key=lambda item: item.score)
    best = scored[0]
    second_score = scored[1].score if len(scored) > 1 else best.score + MIN_MARGIN
    margin = float(second_score - best.score)
    threshold = ASSIST_SCORE_THRESHOLD if mode == "assist" else AUTO_SCORE_THRESHOLD
    confidence = _score_to_confidence(best.score, threshold, margin)
    if best.score > threshold:
        return ChartDetectionResult(
            detected=False,
            corners=[],
            patch_orientation=best.orientation,
            confidence=confidence,
            score=best.score,
            mode=mode,
            reason="最佳候选与参考色差过大，请辅助点击色块或手动指定四角。",
            candidate_count=len(candidates),
        )
    if margin < MIN_MARGIN and confidence < 0.72 and best.score > threshold * 0.35:
        return ChartDetectionResult(
            detected=False,
            corners=[],
            patch_orientation=best.orientation,
            confidence=confidence,
            score=best.score,
            mode=mode,
            reason="候选区域置信度不足，请辅助点击色块或手动指定四角。",
            candidate_count=len(candidates),
        )

    original_corners = order_quad(best.corners / float(scale))
    return ChartDetectionResult(
        detected=True,
        corners=[
            {"x": round(float(point[0]), 2), "y": round(float(point[1]), 2)}
            for point in original_corners
        ],
        patch_orientation=best.orientation,
        confidence=confidence,
        score=best.score,
        mode=mode,
        reason="定位成功。",
        candidate_count=len(candidates),
    )


def _failure(
    mode: Literal["auto", "assist"],
    reason: str,
    candidate_count: int,
) -> ChartDetectionResult:
    return ChartDetectionResult(
        detected=False,
        corners=[],
        patch_orientation="normal",
        confidence=0.0,
        score=None,
        mode=mode,
        reason=reason,
        candidate_count=candidate_count,
    )


def _layout_spec(patch_layout: str) -> tuple[int, int]:
    if patch_layout == "3x8":
        return 3, 8
    if patch_layout == "4x6":
        return 4, 6
    raise ValueError("patchLayout must be 4x6 or 3x8.")


def _resize_for_detection(image: np.ndarray, *, max_dimension: int) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    largest = max(height, width)
    if largest <= max_dimension:
        return image, 1.0
    scale = float(max_dimension) / float(largest)
    resized = cv2.resize(
        image,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def _reference_bgr(reference_patches: list[dict[str, object]]) -> np.ndarray:
    colors: list[list[float]] = []
    for patch in reference_patches:
        srgb = patch.get("sRGB")
        if not isinstance(srgb, list) or len(srgb) < 3:
            raise ValueError("参考色块缺少 sRGB。")
        colors.append([float(srgb[2]), float(srgb[1]), float(srgb[0])])
    return np.asarray(colors, dtype=np.float32)


def _bgr_samples_to_lab(samples_bgr: np.ndarray) -> np.ndarray:
    samples = np.clip(samples_bgr, 0, 255).astype(np.uint8).reshape(-1, 1, 3)
    return cv2.cvtColor(samples, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)


def _reference_color_mask(image: np.ndarray, reference_lab: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    chromatic = np.max(np.abs(reference_lab[:, 1:] - 128.0), axis=1) > 12.0
    color_refs = reference_lab[chromatic] if np.any(chromatic) else reference_lab
    min_dist = np.full(lab.shape[:2], np.inf, dtype=np.float32)
    for ref in color_refs:
        diff = lab - ref.reshape(1, 1, 3)
        dist = np.sqrt(np.sum(diff * diff, axis=2))
        min_dist = np.minimum(min_dist, dist)
    mask = ((min_dist <= 48.0) & (value >= 18)).astype(np.uint8) * 255
    mask = cv2.bitwise_or(mask, ((saturation >= 28) & (value >= 24)).astype(np.uint8) * 255)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.dilate(mask, kernel, iterations=1)
    return mask


def _candidate_quads(
    image: np.ndarray,
    mask: np.ndarray,
    *,
    rows: int,
    cols: int,
    assist_point: dict[str, float] | None,
    scale: float,
) -> list[np.ndarray]:
    candidates: list[np.ndarray] = []
    candidates.extend(_grid_candidates_from_patch_components(image, rows=rows, cols=cols))
    candidates.extend(_contour_candidates(mask, rows=rows, cols=cols))
    candidates.extend(_edge_candidates(image, rows=rows, cols=cols))
    if assist_point:
        candidates.extend(
            _assist_candidates(
                image,
                mask,
                rows=rows,
                cols=cols,
                assist_point=assist_point,
                scale=scale,
            )
        )
    return _dedupe_candidates(candidates, image.shape[1], image.shape[0])


@dataclass(frozen=True)
class _PatchComponent:
    center: np.ndarray
    width: float
    height: float
    area: float


def _grid_candidates_from_patch_components(image: np.ndarray, *, rows: int, cols: int) -> list[np.ndarray]:
    components = _patch_components_from_edges(image)
    if len(components) < max(8, rows * 2):
        return []

    median_width = float(np.median([component.width for component in components]))
    median_height = float(np.median([component.height for component in components]))
    row_clusters = _cluster_components_by_axis(components, axis=1, tolerance=max(8.0, median_height * 0.65))
    candidates: list[np.ndarray] = []
    image_area = float(image.shape[0] * image.shape[1])

    for row_group in _cluster_windows(row_clusters, rows):
        row_components = [component for cluster in row_group for component in cluster]
        if len(row_components) < max(8, rows * 2):
            continue
        local_width = float(np.median([component.width for component in row_components]))
        col_clusters = _cluster_components_by_axis(row_components, axis=0, tolerance=max(8.0, local_width * 0.72))
        for col_group in _cluster_windows(col_clusters, cols):
            cell_points: list[tuple[int, int, np.ndarray]] = []
            for row_index, row_cluster in enumerate(row_group):
                for col_index, col_cluster in enumerate(col_group):
                    cell = _nearest_component_in_cell(row_cluster, col_cluster)
                    if cell is not None:
                        cell_points.append((row_index, col_index, cell.center))
            if len(cell_points) < max(10, int(rows * cols * 0.45)):
                continue
            fitted = _fit_grid_candidate(cell_points, rows=rows, cols=cols)
            if fitted is None:
                continue
            candidate, residual = fitted
            if residual > max(median_width, median_height) * 0.35:
                continue
            if _quad_shape_ok(candidate, rows=rows, cols=cols, image_area=image_area):
                candidates.append(order_quad(candidate))
    return candidates


def _patch_components_from_edges(image: np.ndarray) -> list[_PatchComponent]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 30, 100)
    contours, _hierarchy = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(image.shape[0] * image.shape[1])
    components: list[_PatchComponent] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < image_area * 0.00045 or area > image_area * 0.035:
            continue
        rect = cv2.minAreaRect(contour)
        width, height = (float(rect[1][0]), float(rect[1][1]))
        short = max(min(width, height), 1.0)
        long = max(width, height)
        if short < 10.0 or long / short > 1.75:
            continue
        components.append(
            _PatchComponent(
                center=np.asarray(rect[0], dtype=np.float32),
                width=long,
                height=short,
                area=area,
            )
        )

    components.sort(key=lambda item: item.area, reverse=True)
    unique: list[_PatchComponent] = []
    for component in components:
        duplicate = False
        for kept in unique:
            distance = float(np.linalg.norm(component.center - kept.center))
            if distance <= max(6.0, min(component.width, kept.width) * 0.35):
                duplicate = True
                break
        if not duplicate:
            unique.append(component)
    return unique[:160]


def _cluster_components_by_axis(
    components: list[_PatchComponent],
    *,
    axis: int,
    tolerance: float,
) -> list[list[_PatchComponent]]:
    ordered = sorted(components, key=lambda component: float(component.center[axis]))
    clusters: list[list[_PatchComponent]] = []
    for component in ordered:
        value = float(component.center[axis])
        if not clusters:
            clusters.append([component])
            continue
        current_values = [float(item.center[axis]) for item in clusters[-1]]
        if abs(value - float(np.median(current_values))) <= tolerance:
            clusters[-1].append(component)
        else:
            clusters.append([component])
    return [cluster for cluster in clusters if cluster]


def _cluster_windows(
    clusters: list[list[_PatchComponent]],
    expected_count: int,
) -> list[list[list[_PatchComponent]]]:
    if len(clusters) < expected_count:
        return []
    return [clusters[index : index + expected_count] for index in range(len(clusters) - expected_count + 1)]


def _nearest_component_in_cell(
    row_cluster: list[_PatchComponent],
    col_cluster: list[_PatchComponent],
) -> _PatchComponent | None:
    row_set = set(id(component) for component in row_cluster)
    matches = [component for component in col_cluster if id(component) in row_set]
    if not matches:
        return None
    row_y = float(np.median([component.center[1] for component in row_cluster]))
    col_x = float(np.median([component.center[0] for component in col_cluster]))
    target = np.array([col_x, row_y], dtype=np.float32)
    return min(matches, key=lambda component: float(np.linalg.norm(component.center - target)))


def _fit_grid_candidate(
    cell_points: list[tuple[int, int, np.ndarray]],
    *,
    rows: int,
    cols: int,
) -> tuple[np.ndarray, float] | None:
    design = np.asarray([[1.0, float(col), float(row)] for row, col, _point in cell_points], dtype=np.float64)
    targets = np.asarray([point for _row, _col, point in cell_points], dtype=np.float64)
    if design.shape[0] < 3:
        return None
    coefficients, *_ = np.linalg.lstsq(design, targets, rcond=None)
    origin = coefficients[0]
    u_vec = coefficients[1]
    v_vec = coefficients[2]
    if np.linalg.norm(u_vec) < 8.0 or np.linalg.norm(v_vec) < 8.0:
        return None
    predicted = design @ coefficients
    residual = float(np.median(np.linalg.norm(predicted - targets, axis=1)))
    candidate = np.asarray(
        [
            origin - 0.5 * u_vec - 0.5 * v_vec,
            origin + (cols - 0.5) * u_vec - 0.5 * v_vec,
            origin + (cols - 0.5) * u_vec + (rows - 0.5) * v_vec,
            origin - 0.5 * u_vec + (rows - 0.5) * v_vec,
        ],
        dtype=np.float32,
    )
    return candidate, residual


def _contour_candidates(mask: np.ndarray, *, rows: int, cols: int) -> list[np.ndarray]:
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(mask.shape[0] * mask.shape[1])
    candidates: list[np.ndarray] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < image_area * 0.002:
            continue
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect).astype(np.float32)
        if _quad_shape_ok(box, rows=rows, cols=cols, image_area=image_area):
            candidates.append(order_quad(box))
        approx = cv2.approxPolyDP(contour, 0.035 * cv2.arcLength(contour, True), True)
        if len(approx) == 4:
            quad = approx.reshape(4, 2).astype(np.float32)
            if _quad_shape_ok(quad, rows=rows, cols=cols, image_area=image_area):
                candidates.append(order_quad(quad))
    return candidates


def _edge_candidates(image: np.ndarray, *, rows: int, cols: int) -> list[np.ndarray]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 40, 120)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _hierarchy = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(image.shape[0] * image.shape[1])
    candidates: list[np.ndarray] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < image_area * 0.002:
            continue
        approx = cv2.approxPolyDP(contour, 0.03 * cv2.arcLength(contour, True), True)
        if len(approx) == 4:
            quad = approx.reshape(4, 2).astype(np.float32)
            if _quad_shape_ok(quad, rows=rows, cols=cols, image_area=image_area):
                candidates.append(order_quad(quad))
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect).astype(np.float32)
        if _quad_shape_ok(box, rows=rows, cols=cols, image_area=image_area):
            candidates.append(order_quad(box))
    return candidates


def _assist_candidates(
    image: np.ndarray,
    mask: np.ndarray,
    *,
    rows: int,
    cols: int,
    assist_point: dict[str, float],
    scale: float,
) -> list[np.ndarray]:
    point = np.array(
        [
            float(assist_point.get("x", 0.0)) * scale,
            float(assist_point.get("y", 0.0)) * scale,
        ],
        dtype=np.float32,
    )
    height, width = image.shape[:2]
    candidates: list[np.ndarray] = []
    if 0 <= point[0] < width and 0 <= point[1] < height:
        component = _component_at_point(mask, point)
        if component is not None:
            candidates.extend(_contour_candidates(component, rows=rows, cols=cols))

    aspect = float(cols) / float(rows)
    min_side = min(width, height)
    base_widths = [min_side * factor for factor in (0.28, 0.38, 0.50, 0.64, 0.78)]
    angles = (-35.0, -20.0, -10.0, 0.0, 10.0, 20.0, 35.0)
    image_area = float(width * height)
    for chart_width in base_widths:
        chart_height = chart_width / aspect
        if chart_height < 24 or chart_width < 36:
            continue
        if chart_width > width * 1.05 or chart_height > height * 1.05:
            continue
        for row in range(rows):
            for col in range(cols):
                local = np.array(
                    [
                        ((col + 0.5) / cols - 0.5) * chart_width,
                        ((row + 0.5) / rows - 0.5) * chart_height,
                    ],
                    dtype=np.float32,
                )
                for angle in angles:
                    rotation = _rotation_matrix(angle)
                    center = point - rotation @ local
                    box = _rotated_box(center, chart_width, chart_height, angle)
                    if _quad_shape_ok(box, rows=rows, cols=cols, image_area=image_area, allow_outside=True):
                        candidates.append(order_quad(box))
    return candidates


def _component_at_point(mask: np.ndarray, point: np.ndarray) -> np.ndarray | None:
    labels_count, labels, stats, centroids = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    px = int(round(float(point[0])))
    py = int(round(float(point[1])))
    if 0 <= py < labels.shape[0] and 0 <= px < labels.shape[1]:
        label = int(labels[py, px])
        if label > 0:
            return (labels == label).astype(np.uint8) * 255
    best_label = 0
    best_dist = float("inf")
    for label in range(1, labels_count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < 12:
            continue
        dist = float(np.linalg.norm(centroids[label] - point))
        if dist < best_dist:
            best_label = label
            best_dist = dist
    if best_label and best_dist <= max(mask.shape) * 0.04:
        return (labels == best_label).astype(np.uint8) * 255
    return None


def _rotation_matrix(angle_degrees: float) -> np.ndarray:
    angle = np.deg2rad(angle_degrees)
    return np.array(
        [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]],
        dtype=np.float32,
    )


def _rotated_box(center: np.ndarray, width: float, height: float, angle_degrees: float) -> np.ndarray:
    half = np.array(
        [
            [-width / 2.0, -height / 2.0],
            [width / 2.0, -height / 2.0],
            [width / 2.0, height / 2.0],
            [-width / 2.0, height / 2.0],
        ],
        dtype=np.float32,
    )
    rotation = _rotation_matrix(angle_degrees)
    return (half @ rotation.T) + center.reshape(1, 2)


def _quad_shape_ok(
    quad: np.ndarray,
    *,
    rows: int,
    cols: int,
    image_area: float,
    allow_outside: bool = False,
) -> bool:
    ordered = order_quad(np.asarray(quad, dtype=np.float32))
    area = abs(float(cv2.contourArea(ordered)))
    if area < image_area * 0.0015 or area > image_area * 0.92:
        return False
    width_top = float(np.linalg.norm(ordered[1] - ordered[0]))
    width_bottom = float(np.linalg.norm(ordered[2] - ordered[3]))
    height_left = float(np.linalg.norm(ordered[3] - ordered[0]))
    height_right = float(np.linalg.norm(ordered[2] - ordered[1]))
    width = max((width_top + width_bottom) / 2.0, 1.0)
    height = max((height_left + height_right) / 2.0, 1.0)
    ratio = width / height
    target = float(cols) / float(rows)
    if not (target * 0.48 <= ratio <= target * 1.85):
        return False
    if allow_outside:
        return True
    return bool(np.all(np.isfinite(ordered)))


def _dedupe_candidates(candidates: list[np.ndarray], width: int, height: int) -> list[np.ndarray]:
    unique: list[np.ndarray] = []
    seen: set[tuple[int, ...]] = set()
    for candidate in candidates:
        ordered = order_quad(np.asarray(candidate, dtype=np.float32))
        if not np.all(np.isfinite(ordered)):
            continue
        if np.any(ordered[:, 0] < -2) or np.any(ordered[:, 1] < -2):
            continue
        if np.any(ordered[:, 0] > width + 2) or np.any(ordered[:, 1] > height + 2):
            continue
        key = tuple(int(round(v / 4.0)) for v in ordered.reshape(-1))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ordered)
    return unique[:240]


def _score_candidate(
    image: np.ndarray,
    corners: np.ndarray,
    reference_bgr: np.ndarray,
    *,
    rows: int,
    cols: int,
) -> _ScoredCandidate | None:
    cell = 36
    width = cols * cell
    height = rows * cell
    target = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    try:
        homography = cv2.getPerspectiveTransform(order_quad(corners), target)
        warped = cv2.warpPerspective(image, homography, (width, height), flags=cv2.INTER_LINEAR)
    except cv2.error:
        return None
    samples = _sample_grid_bgr(warped, rows=rows, cols=cols, cell=cell)
    if samples is None:
        return None
    best_orientation: PatchOrientation = "normal"
    best_score = float("inf")
    best_direct = float("inf")
    for orientation in ORIENTATIONS:
        ordered_samples = _samples_in_reference_order(samples, rows=rows, cols=cols, orientation=orientation)
        score = _affine_rgb_score(ordered_samples, reference_bgr)
        direct = _direct_lab_score(ordered_samples, reference_bgr)
        structure = _grid_structure_score(warped, rows=rows, cols=cols, cell=cell)
        combined = float(score + structure + direct * 0.0002)
        if combined < best_score:
            best_score = combined
            best_direct = direct
            best_orientation = orientation
    return _ScoredCandidate(
        corners=order_quad(corners),
        orientation=best_orientation,
        score=best_score,
        direct_lab_score=best_direct,
    )


def _sample_grid_bgr(
    warped: np.ndarray,
    *,
    rows: int,
    cols: int,
    cell: int,
) -> np.ndarray | None:
    radius = max(3, int(round(cell * 0.18)))
    samples: list[np.ndarray] = []
    for row in range(rows):
        for col in range(cols):
            cx = int(round((col + 0.5) * cell))
            cy = int(round((row + 0.5) * cell))
            x0 = max(0, cx - radius)
            x1 = min(warped.shape[1], cx + radius + 1)
            y0 = max(0, cy - radius)
            y1 = min(warped.shape[0], cy + radius + 1)
            patch = warped[y0:y1, x0:x1]
            if patch.size == 0:
                return None
            samples.append(np.median(patch.reshape(-1, 3), axis=0))
    return np.asarray(samples, dtype=np.float32)


def _samples_in_reference_order(
    physical_samples: np.ndarray,
    *,
    rows: int,
    cols: int,
    orientation: PatchOrientation,
) -> np.ndarray:
    ordered: list[np.ndarray] = []
    for ref_row in range(rows):
        for ref_col in range(cols):
            physical_index = _physical_index(ref_row, ref_col, rows=rows, cols=cols, orientation=orientation)
            ordered.append(physical_samples[physical_index])
    return np.asarray(ordered, dtype=np.float32)


def _physical_index(
    row: int,
    col: int,
    *,
    rows: int,
    cols: int,
    orientation: PatchOrientation,
) -> int:
    if orientation == "rotate_180":
        return (rows - 1 - row) * cols + (cols - 1 - col)
    if orientation == "flip_horizontal":
        return row * cols + (cols - 1 - col)
    if orientation == "flip_vertical":
        return (rows - 1 - row) * cols + col
    return row * cols + col


def _affine_rgb_score(samples_bgr: np.ndarray, reference_bgr: np.ndarray) -> float:
    measured = np.clip(samples_bgr[:, ::-1] / 255.0, 0.0, 1.0).astype(np.float64)
    reference = np.clip(reference_bgr[:, ::-1] / 255.0, 0.0, 1.0).astype(np.float64)
    design = np.concatenate([measured, np.ones((measured.shape[0], 1), dtype=np.float64)], axis=1)
    coefficients, *_ = np.linalg.lstsq(design, reference, rcond=None)
    predicted = np.clip(design @ coefficients, 0.0, 1.0)
    residual = predicted - reference
    return float(np.sqrt(np.mean(residual * residual)))


def _direct_lab_score(samples_bgr: np.ndarray, reference_bgr: np.ndarray) -> float:
    sample_lab = _bgr_samples_to_lab(samples_bgr)
    reference_lab = _bgr_samples_to_lab(reference_bgr)
    distances = np.linalg.norm(sample_lab - reference_lab, axis=1)
    return float(np.median(distances))


def _grid_structure_score(warped: np.ndarray, *, rows: int, cols: int, cell: int) -> float:
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(np.float32)
    patch_values: list[float] = []
    line_values: list[float] = []
    patch_radius = max(3, int(round(cell * 0.22)))
    line_radius = max(1, int(round(cell * 0.055)))

    for row in range(rows):
        for col in range(cols):
            cx = int(round((col + 0.5) * cell))
            cy = int(round((row + 0.5) * cell))
            patch = gray[
                max(0, cy - patch_radius) : min(gray.shape[0], cy + patch_radius + 1),
                max(0, cx - patch_radius) : min(gray.shape[1], cx + patch_radius + 1),
            ]
            if patch.size:
                patch_values.append(float(np.median(patch)))

    for col in range(1, cols):
        x = int(round(col * cell))
        line = gray[:, max(0, x - line_radius) : min(gray.shape[1], x + line_radius + 1)]
        if line.size:
            line_values.append(float(np.median(line)))
    for row in range(1, rows):
        y = int(round(row * cell))
        line = gray[max(0, y - line_radius) : min(gray.shape[0], y + line_radius + 1), :]
        if line.size:
            line_values.append(float(np.median(line)))

    if not patch_values or not line_values:
        return 0.08
    patch_median = float(np.median(patch_values))
    line_median = float(np.median(line_values))
    contrast = patch_median - line_median
    return float(np.clip((18.0 - contrast) / 255.0, 0.0, 0.08))


def _score_to_confidence(score: float, threshold: float, margin: float) -> float:
    quality = 1.0 - min(max(score / max(threshold, 1e-6), 0.0), 1.6) / 1.6
    separation = min(max(margin / max(MIN_MARGIN * 4.0, 1e-6), 0.0), 1.0)
    return float(np.clip(0.15 + 0.65 * quality + 0.2 * separation, 0.0, 0.99))
