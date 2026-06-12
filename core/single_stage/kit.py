"""Single-stage calibration kit generation.

Builds a printable multi-job kit aligned with the ChromaPrint3D single-stage
geometry so Lumina can generate, distribute, and later extract single-stage
datasets for Stage A fitting.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw

from config import (
    DEFAULT_PRINTER_ID,
    DEFAULT_SLICER_ID,
    ColorSystem,
    MODELS_DIR,
    PaletteEntry,
    TEMP_DIR,
)
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

_trimesh = None


def _get_trimesh():
    global _trimesh
    if _trimesh is None:
        import trimesh as _tm

        _trimesh = _tm
    return _trimesh


_SANITIZE_RE = re.compile(r"[^a-z0-9]+")
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
_SUBSTRATE_PRESETS: dict[str, tuple[int, int, int]] = {
    "white": (255, 255, 255),
    "black": (24, 24, 24),
}


@dataclass(frozen=True)
class SingleStageSpec:
    """Reference single-stage physical specification."""

    grid_cols: int = 6
    grid_rows: int = 3
    block_mm: float = 10.0
    gap_mm: float = 1.0
    margin_mm: float = 1.0
    pixel_mm: float = 1.0
    layer_height_mm: float = 0.04
    base_mm: float = 1.0
    max_step_layers: int = 25
    step_layers: tuple[int, ...] = field(
        default_factory=lambda: tuple(list(range(17)) + [25])
    )
    shrink_xy_mm: float = 0.02

    @property
    def base_layers(self) -> int:
        return int(round(self.base_mm / self.layer_height_mm))

    @property
    def board_width_mm(self) -> float:
        return (
            self.grid_cols * self.block_mm
            + (self.grid_cols - 1) * self.gap_mm
            + 2 * self.margin_mm
        )

    @property
    def board_height_mm(self) -> float:
        return (
            self.grid_rows * self.block_mm
            + (self.grid_rows - 1) * self.gap_mm
            + 2 * self.margin_mm
        )


@dataclass(frozen=True)
class SingleStageKitResult:
    """Generated single-stage kit outputs."""

    zip_path: str
    manifest_path: str
    preview_image: Image.Image
    jobs: list[dict[str, str]]
    message: str


SINGLE_STAGE_SPEC = SingleStageSpec()


def _sanitize_token(value: str) -> str:
    normalized = _SANITIZE_RE.sub("-", value.strip().lower()).strip("-")
    return normalized or "item"


def _parse_hex_rgb(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    match = _HEX_RE.match(value.strip())
    if not match:
        return None
    hex_value = match.group(1)
    return tuple(int(hex_value[i : i + 2], 16) for i in (0, 2, 4))


def _build_preview_lookup() -> dict[str, tuple[int, int, int]]:
    lookup: dict[str, tuple[int, int, int]] = {}
    for config in (
        ColorSystem.CMYW,
        ColorSystem.RYBW,
        ColorSystem.SIX_COLOR,
        ColorSystem.SIX_COLOR_RYBW,
        ColorSystem.EIGHT_COLOR,
        ColorSystem.BW,
        ColorSystem.FIVE_COLOR_EXTENDED,
    ):
        slots = config.get("slots", [])
        preview = config.get("preview", {})
        for index, slot in enumerate(slots):
            rgba = preview.get(index)
            if rgba:
                lookup[_sanitize_token(str(slot))] = tuple(int(v) for v in rgba[:3])
    lookup["deep-blue"] = (10, 41, 137)
    return lookup


_PREVIEW_LOOKUP = _build_preview_lookup()


def _resolve_rgb(entry: PaletteEntry) -> tuple[int, int, int]:
    rgb = _parse_hex_rgb(entry.hex_color)
    if rgb is not None:
        return rgb

    for candidate in (entry.color_name, entry.color):
        if candidate:
            key = _sanitize_token(candidate)
            if key in _PREVIEW_LOOKUP:
                return _PREVIEW_LOOKUP[key]

    return (180, 180, 180)


def _resolve_substrate_rgb(
    substrate_id: str,
    substrate_display_name: str,
    palette: Iterable[PaletteEntry],
) -> tuple[int, int, int]:
    for candidate in (substrate_id, substrate_display_name):
        key = _sanitize_token(candidate)
        if key in _SUBSTRATE_PRESETS:
            return _SUBSTRATE_PRESETS[key]

    for entry in palette:
        for candidate in (entry.color_name, entry.color):
            if not candidate:
                continue
            if _sanitize_token(candidate) == _sanitize_token(substrate_display_name):
                return _resolve_rgb(entry)

    return (235, 235, 235)


def _format_hex_rgb(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{int(channel):02X}" for channel in rgb)


def _build_shared_stage_entry(
    palette: list[PaletteEntry],
    substrate_id: str,
    substrate_display_name: str,
    material_default: str,
) -> PaletteEntry:
    substrate_tokens = {
        _sanitize_token(substrate_id),
        _sanitize_token(substrate_display_name),
    }

    reference_entry = palette[0]
    for entry in palette:
        candidates = [entry.color_name, entry.color]
        if any(
            candidate and _sanitize_token(candidate) not in substrate_tokens
            for candidate in candidates
        ):
            reference_entry = entry
            break

    reference_rgb = _resolve_rgb(reference_entry)
    reference_material = (
        (reference_entry.material or material_default).strip() or material_default
    )
    return PaletteEntry(
        color="Sample",
        material=reference_material,
        hex_color=_format_hex_rgb(reference_rgb),
        color_name="Sample",
    )


def _generate_voxel_mesh(
    voxel_matrix: np.ndarray,
    material_index: int,
    scale_x: float,
    scale_y: float,
    scale_z: float,
    shrink_xy: float,
):
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    grid_h, grid_w = voxel_matrix.shape[1], voxel_matrix.shape[2]

    for z in range(voxel_matrix.shape[0]):
        z_bottom = z * scale_z
        z_top = (z + 1) * scale_z
        layer_mask = voxel_matrix[z] == material_index
        if not np.any(layer_mask):
            continue

        for y in range(grid_h):
            padded_row = np.pad(layer_mask[y], (1, 1), mode="constant")
            diff = np.diff(padded_row.astype(int))
            starts = np.where(diff == 1)[0]
            ends = np.where(diff == -1)[0]
            for start, end in zip(starts, ends):
                x0 = start * scale_x + shrink_xy
                x1 = end * scale_x - shrink_xy
                y0 = y * scale_y + shrink_xy
                y1 = (y + 1) * scale_y - shrink_xy
                if x1 <= x0 or y1 <= y0:
                    continue

                base_idx = len(vertices)
                vertices.extend(
                    [
                        [x0, y0, z_bottom],
                        [x1, y0, z_bottom],
                        [x1, y1, z_bottom],
                        [x0, y1, z_bottom],
                        [x0, y0, z_top],
                        [x1, y0, z_top],
                        [x1, y1, z_top],
                        [x0, y1, z_top],
                    ]
                )
                faces.extend(
                    [
                        [base_idx + 0, base_idx + 2, base_idx + 1],
                        [base_idx + 0, base_idx + 3, base_idx + 2],
                        [base_idx + 4, base_idx + 5, base_idx + 6],
                        [base_idx + 4, base_idx + 6, base_idx + 7],
                        [base_idx + 0, base_idx + 1, base_idx + 5],
                        [base_idx + 0, base_idx + 5, base_idx + 4],
                        [base_idx + 1, base_idx + 2, base_idx + 6],
                        [base_idx + 1, base_idx + 6, base_idx + 5],
                        [base_idx + 2, base_idx + 3, base_idx + 7],
                        [base_idx + 2, base_idx + 7, base_idx + 6],
                        [base_idx + 3, base_idx + 0, base_idx + 4],
                        [base_idx + 3, base_idx + 4, base_idx + 7],
                    ]
                )

    if not vertices:
        return None

    mesh = _get_trimesh().Trimesh(vertices=vertices, faces=faces)
    mesh.merge_vertices()
    mesh.update_faces(mesh.unique_faces())
    return mesh


def _apply_face_down_x_mirror(scene, model_width_mm: float) -> None:
    mirror = np.array(
        [
            [-1.0, 0.0, 0.0, model_width_mm],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    for geom_name in list(scene.geometry.keys()):
        scene.geometry[geom_name].apply_transform(mirror)


def _build_stage_matrix(spec: SingleStageSpec) -> np.ndarray:
    block_px = int(round(spec.block_mm / spec.pixel_mm))
    gap_px = int(round(spec.gap_mm / spec.pixel_mm))
    margin_px = int(round(spec.margin_mm / spec.pixel_mm))
    width = spec.grid_cols * block_px + (spec.grid_cols - 1) * gap_px + 2 * margin_px
    height = spec.grid_rows * block_px + (spec.grid_rows - 1) * gap_px + 2 * margin_px
    total_layers = spec.base_layers + spec.max_step_layers

    voxel = np.zeros((total_layers, height, width), dtype=np.int16)

    for index, step_layers in enumerate(spec.step_layers):
        row = index // spec.grid_cols
        col = index % spec.grid_cols
        x0 = margin_px + col * (block_px + gap_px)
        y0 = margin_px + row * (block_px + gap_px)
        x1 = x0 + block_px
        y1 = y0 + block_px
        if step_layers <= 0:
            continue
        voxel[:step_layers, y0:y1, x0:x1] = 1

    return voxel


def _build_stage_scene(
    entry: PaletteEntry,
    substrate_id: str,
    substrate_display_name: str,
    substrate_rgb: tuple[int, int, int],
    spec: SingleStageSpec,
):
    voxel = _build_stage_matrix(spec)
    scene = _get_trimesh().Scene()

    base_name = f"Base - {substrate_display_name}"
    step_name = f"Step - {entry.color_name or entry.color}"
    preview_colors = {
        base_name: (*substrate_rgb, 255),
        step_name: (*_resolve_rgb(entry), 255),
    }
    slot_names = [base_name, step_name]

    for material_index, name in enumerate(slot_names):
        mesh = _generate_voxel_mesh(
            voxel_matrix=voxel,
            material_index=material_index,
            scale_x=spec.pixel_mm,
            scale_y=spec.pixel_mm,
            scale_z=spec.layer_height_mm,
            shrink_xy=spec.shrink_xy_mm,
        )
        if mesh is None:
            continue
        mesh.visual.face_colors = preview_colors[name]
        mesh.metadata["name"] = name
        if material_index == 1:
            mesh.metadata["bambu_material_name"] = entry.material or name
        scene.add_geometry(mesh, node_name=name, geom_name=name)

    _apply_face_down_x_mirror(scene, spec.board_width_mm)

    preview = np.full((voxel.shape[1], voxel.shape[2], 3), substrate_rgb, dtype=np.uint8)
    preview[voxel[0] == 1] = _resolve_rgb(entry)
    return scene, Image.fromarray(preview)


def _compose_preview_grid(
    items: list[tuple[str, Image.Image]],
    *,
    tile_padding: int = 20,
    label_height: int = 28,
    columns: int = 2,
) -> Image.Image:
    if not items:
        return Image.new("RGB", (320, 180), (245, 245, 245))

    tile_w = max(image.width for _, image in items)
    tile_h = max(image.height for _, image in items) + label_height
    rows = (len(items) + columns - 1) // columns
    canvas = Image.new(
        "RGB",
        (
            columns * tile_w + (columns + 1) * tile_padding,
            rows * tile_h + (rows + 1) * tile_padding,
        ),
        (248, 248, 248),
    )
    draw = ImageDraw.Draw(canvas)

    for index, (label, image) in enumerate(items):
        row = index // columns
        col = index % columns
        x = tile_padding + col * tile_w + col * tile_padding
        y = tile_padding + row * tile_h + row * tile_padding
        canvas.paste(image, (x, y))
        draw.rectangle(
            [x, y + image.height, x + tile_w, y + image.height + label_height],
            fill=(235, 235, 235),
        )
        draw.text((x + 8, y + image.height + 6), label, fill=(40, 40, 40))

    return canvas


def _resolve_colorchecker_bundle() -> tuple[Path | None, Path | None]:
    candidates = [
        Path("reference/ChromaPrint3D/modeling/data/ColorChecker"),
        Path("assets/ColorChecker"),
    ]
    for root in candidates:
        ref_json = root / "ColorCheckerjson.json"
        if ref_json.exists():
            ref_desc = root / "desc.txt"
            return ref_json, ref_desc if ref_desc.exists() else None
    return None, None


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def generate_single_stage_kit(
    palette: list[PaletteEntry],
    substrate_id: str = "white",
    substrate_display_name: str = "White",
    material_default: str = "PLA Basic",
    spec: SingleStageSpec = SINGLE_STAGE_SPEC,
    layer_height_mm: float | None = None,
    printer_id: str = DEFAULT_PRINTER_ID,
    slicer: str = DEFAULT_SLICER_ID,
    nozzle_size: str | float | None = None,
    device_profile_id: str | None = None,
) -> SingleStageKitResult:
    """Generate a ChromaPrint3D-aligned single-stage kit zip."""
    if not palette:
        raise ValueError("Single-stage kit requires at least one palette entry.")

    if layer_height_mm is not None:
        spec = replace(spec, layer_height_mm=layer_height_mm)

    os.makedirs(MODELS_DIR, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="single_stage_", dir=TEMP_DIR))

    try:
        substrate_rgb = _resolve_substrate_rgb(substrate_id, substrate_display_name, palette)
        shared_entry = _build_shared_stage_entry(
            palette,
            substrate_id,
            substrate_display_name,
            material_default,
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_filename = f"single_stage_{_sanitize_token(substrate_id)}_{timestamp}.3mf"
        model_path = work_dir / model_filename

        scene, preview_image = _build_stage_scene(
            shared_entry,
            substrate_id,
            substrate_display_name,
            substrate_rgb,
            spec,
        )
        # 无原图，封面走静默占位（不发 WARNING）
        export_scene_with_bambu_metadata(
            scene=scene,
            output_path=str(model_path),
            slot_names=list(scene.geometry.keys()),
            preview_colors={
                name: tuple(scene.geometry[name].visual.face_colors[0][:4])
                for name in scene.geometry.keys()
            },
            settings={
                "layer_height": f"{spec.layer_height_mm:.2f}",
                "initial_layer_height": f"{spec.layer_height_mm:.2f}",
                "wall_loops": "1",
                "top_shell_layers": "0",
                "bottom_shell_layers": "1",
                "bottom_surface_pattern": "monotonicline",
                "elefant_foot_compensation": "0",
                "sparse_infill_density": "100%",
                "sparse_infill_pattern": "zig-zag",
            },
            color_mode="BW (Black & White)",
            printer_id=printer_id,
            slicer=slicer,
            nozzle_size=nozzle_size,
            device_profile_id=device_profile_id,
            cover_source=None,
        )

        manifest = {
            "schema_version": "1.0",
            "workflow": "single-stage-kit",
            "substrate_id": substrate_id,
            "substrate_display_name": substrate_display_name,
            "material_default": material_default,
            "dataset_layout": "{substrate_id}/{color_name}/",
            "spec": asdict(spec),
            "labelme": {
                "required_labels": ["ColorChecker", "stage"],
                "dataset_layout": "{substrate_id}/{color_name}/",
                "color_source": "folder_name",
            },
            "shared_model_filename": model_filename,
            "jobs": [],
        }
        manifest_path = Path(MODELS_DIR) / f"Lumina_SingleStage_Manifest_{timestamp}.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        readme_path = work_dir / "README_single_stage.txt"
        _write_text(
            readme_path,
            "\n".join(
                [
                    "Lumina Single-Stage Kit",
                    "",
                    "1. Print the shared 3MF board with the single material sample you want to characterize.",
                    "2. Photograph each printed board with a ColorChecker in frame.",
                    "3. Label each image with LabelMe.",
                    "4. Required polygons: ColorChecker, stage.",
                    "5. Place captures under dataset_template/{substrate_id}/Sample/ and zip using {substrate_id}/{color_name}/ structure.",
                ]
            ),
        )

        template_root = work_dir / "dataset_template" / substrate_id
        template_label = shared_entry.color_name or shared_entry.color or "Sample"
        placeholder = template_root / template_label / "PUT_PHOTOS_AND_LABELME_JSON_HERE.txt"
        _write_text(
            placeholder,
            "Place images and matching LabelMe JSON files in this folder.\n",
        )

        ref_json, ref_desc = _resolve_colorchecker_bundle()

        zip_path = Path(MODELS_DIR) / f"Lumina_SingleStage_Kit_{timestamp}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(model_path, model_filename)
            archive.write(manifest_path, "manifest.json")
            archive.write(readme_path, "README_single_stage.txt")
            for placeholder in template_root.rglob("*"):
                if placeholder.is_file():
                    archive.write(
                        placeholder,
                        str(placeholder.relative_to(work_dir)).replace("\\", "/"),
                    )
            if ref_json is not None:
                archive.write(ref_json, "colorchecker/ColorCheckerjson.json")
            if ref_desc is not None:
                archive.write(ref_desc, "colorchecker/desc.txt")

        return SingleStageKitResult(
            zip_path=str(zip_path),
            manifest_path=str(manifest_path),
            preview_image=preview_image,
            jobs=[],
            message="Single-stage shared 3MF packaged into kit zip.",
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
