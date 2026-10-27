from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
import math
import xml.etree.ElementTree as ET

from shapely import affinity
import shapely
from shapely.geometry import GeometryCollection, box
from shapely.validation import make_valid

from core.naming import _sanitize, _strip_temp_prefix
from core.vector_engine import VectorAnalysis, VectorProcessor
from core.vector_structure import VectorStructurePlan
from core.svg_coordinate_domain import PRINT_GRID_KEY, SvgCoordinateDomain, project_print_regions
from core.vector_layer_geometry import resolve_vector_writer_grid_mm

SVG_LARGE_FORMAT_PREVIEW_FALLBACK_WARNING = (
    "Native vector large-format is unavailable for this SVG; large-format generation will fall back to raster tiling."
)
SVG_LARGE_FORMAT_GENERATE_FALLBACK_WARNING = "Raster fallback was used for this large-format SVG request."
SVG_LARGE_FORMAT_NATIVE_FAILURE_FALLBACK_WARNING = (
    "Native vector generation failed; raster fallback was used for this "
    "large-format SVG request."
)
SVG_LARGE_FORMAT_FALLBACK_UNSUPPORTED_FEATURE = "unsupported_svg_feature"
SVG_LARGE_FORMAT_FALLBACK_NATIVE_FAILURE = "native_vector_failure"

_UNSUPPORTED_LARGE_FORMAT_TAGS = {
    "text",
    "textPath",
    "tspan",
    "image",
    "foreignObject",
    "pattern",
    "clipPath",
    "mask",
    "filter",
}
_UNSUPPORTED_LARGE_FORMAT_ATTRS = {
    "clip-path",
    "mask",
    "filter",
}


def resolve_large_format_axis_count(total_mm: float, tile_mm: float) -> int:
    """Count positive-width tiles without a floating-point phantom remainder."""
    if not math.isfinite(total_mm) or total_mm <= 0:
        raise ValueError("total_mm must be finite and positive")
    if not math.isfinite(tile_mm) or tile_mm <= 0:
        raise ValueError("tile_mm must be finite and positive")
    count = max(1, math.ceil(total_mm / tile_mm))
    # Division can round above an integer even when multiplication reaches the
    # exact endpoint. Keep genuinely positive remainders, however small.
    if count > 1 and (count - 1) * tile_mm >= total_mm:
        count -= 1
    return count


def resolve_large_format_grid_shape(
    *,
    total_width_mm: float,
    total_height_mm: float,
    tile_width_mm: float,
    tile_height_mm: float,
) -> tuple[int, int]:
    """Validate physical dimensions and return grid columns/rows.

    校验物理尺寸并返回网格列数与行数；分块数量由实际请求决定。
    """

    dimensions = (
        ("total_width_mm", total_width_mm),
        ("total_height_mm", total_height_mm),
        ("tile_width_mm", tile_width_mm),
        ("tile_height_mm", tile_height_mm),
    )
    for name, value in dimensions:
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    cols = resolve_large_format_axis_count(total_width_mm, tile_width_mm)
    rows = resolve_large_format_axis_count(total_height_mm, tile_height_mm)
    return cols, rows


@dataclass(frozen=True)
class VectorTileSpec:
    """Resolved tile bounds in both mm and SVG-local coordinates."""

    row: int
    col: int
    label: str
    x0_mm: float
    y0_mm: float
    x1_mm: float
    y1_mm: float
    width_mm: float
    height_mm: float


@dataclass(frozen=True)
class SlicedVectorTile:
    """One non-empty tile carrying a tile-local VectorAnalysis."""

    spec: VectorTileSpec
    analysis: VectorAnalysis

    @property
    def label(self) -> str:
        return self.spec.label


@dataclass(frozen=True)
class SvgLargeFormatSupportInspector:
    """Inspect one SVG file for large-format native tiling compatibility."""

    svg_path: str

    @staticmethod
    def _local_name(name: str) -> str:
        return name.split("}", 1)[-1] if "}" in name else name

    def inspect(self) -> dict:
        """Detect whether native large-format vector tiling is safe for this SVG."""

        unsupported_features: list[str] = []
        try:
            tree = ET.parse(self.svg_path)
            root = tree.getroot()
        except ET.ParseError:
            return {
                "native_tiling_supported": False,
                "warnings": [SVG_LARGE_FORMAT_PREVIEW_FALLBACK_WARNING],
                "unsupported_features": ["parse-error"],
            }

        for element in root.iter():
            tag_name = self._local_name(element.tag)
            if tag_name in _UNSUPPORTED_LARGE_FORMAT_TAGS and tag_name not in unsupported_features:
                unsupported_features.append(tag_name)

            for attr_name, attr_value in element.attrib.items():
                local_attr = self._local_name(attr_name)
                if local_attr in _UNSUPPORTED_LARGE_FORMAT_ATTRS and attr_value and local_attr not in unsupported_features:
                    unsupported_features.append(local_attr)

        native_tiling_supported = len(unsupported_features) == 0
        warnings = []
        if not native_tiling_supported:
            feature_list = ", ".join(unsupported_features)
            warnings.append(f"{SVG_LARGE_FORMAT_PREVIEW_FALLBACK_WARNING} Unsupported features: {feature_list}.")
        return {
            "native_tiling_supported": native_tiling_supported,
            "warnings": warnings,
            "unsupported_features": unsupported_features,
        }


@dataclass(frozen=True)
class VectorTileLayoutPlanner:
    """Resolve the large-format tile grid independently of vector content."""

    total_width_mm: float
    total_height_mm: float
    tile_width_mm: float
    tile_height_mm: float

    def iter_tile_specs(self) -> Iterator[VectorTileSpec]:
        """Yield tile bounds without materializing the complete grid.

        不预先构造完整网格列表，逐个产出 tile 边界。
        """
        cols, rows = resolve_large_format_grid_shape(
            total_width_mm=self.total_width_mm,
            total_height_mm=self.total_height_mm,
            tile_width_mm=self.tile_width_mm,
            tile_height_mm=self.tile_height_mm,
        )

        for row in range(rows):
            for col in range(cols):
                x0_mm = col * self.tile_width_mm
                y0_mm = row * self.tile_height_mm
                x1_mm = min(x0_mm + self.tile_width_mm, self.total_width_mm)
                y1_mm = min(y0_mm + self.tile_height_mm, self.total_height_mm)
                yield VectorTileSpec(
                    row=row + 1,
                    col=col + 1,
                    label=f"R{row + 1}C{col + 1}",
                    x0_mm=float(x0_mm),
                    y0_mm=float(y0_mm),
                    x1_mm=float(x1_mm),
                    y1_mm=float(y1_mm),
                    width_mm=float(x1_mm - x0_mm),
                    height_mm=float(y1_mm - y0_mm),
                )

    def build_tile_specs(self) -> list[VectorTileSpec]:
        """Resolve all tile bounds for callers that explicitly need a list."""

        return list(self.iter_tile_specs())


class TileGeometrySlicer:
    """Slice geometries into a single tile and normalize the result."""

    def __init__(self, tile_box, *, xoff: float, yoff: float):
        self.tile_box = tile_box
        self.xoff = xoff
        self.yoff = yoff

    def slice_geometry(self, geometry):
        """Clip one geometry to the tile bounds and translate it to tile-local space."""

        if geometry is None or geometry.is_empty:
            return None

        grid = float(shapely.get_precision(geometry)) if isinstance(geometry, shapely.Geometry) else 0.0
        if grid > 0:
            sliced = shapely.intersection(geometry, self.tile_box, grid_size=grid)
            sliced = VectorProcessor._extract_polygonal_geometry(sliced)
            if sliced is None or sliced.is_empty:
                return None
            translated = affinity.translate(
                sliced,
                xoff=math.floor(self.xoff / grid + 0.5) * grid,
                yoff=math.floor(self.yoff / grid + 0.5) * grid,
            )
            return shapely.set_precision(translated, grid, mode="pointwise")

        try:
            sliced = geometry.intersection(self.tile_box)
        except MemoryError:
            raise
        except Exception:
            try:
                sliced = make_valid(geometry).intersection(self.tile_box)
            except MemoryError:
                raise
            except Exception:
                return None

        if sliced is None or sliced.is_empty:
            return None
        if not sliced.is_valid:
            sliced = make_valid(sliced)
        sliced = VectorProcessor._extract_polygonal_geometry(sliced)
        if sliced is None or sliced.is_empty:
            return None
        translated = affinity.translate(sliced, xoff=self.xoff, yoff=self.yoff)
        if translated is None or translated.is_empty:
            return None
        return translated

    def slice_records(self, records: list[dict], *, geometry_key: str) -> list[dict]:
        """Clip record geometry and preserve every non-geometry field."""

        sliced_records: list[dict] = []
        for record in records:
            geometry = self.slice_geometry(record.get(geometry_key))
            if geometry is None or geometry.is_empty:
                continue
            next_record = dict(record)
            next_record[geometry_key] = geometry
            sliced_records.append(next_record)
        return sliced_records


@dataclass(frozen=True)
class VectorAnalysisTiler:
    """Partition a global vector analysis into tile-local analyses."""

    analysis: VectorAnalysis
    total_width_mm: float
    total_height_mm: float
    tile_width_mm: float
    tile_height_mm: float
    _print_grid_mm: float | None = field(default=None, init=False, repr=False)
    _print_regions: tuple | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.analysis.scale_factor <= 0:
            raise ValueError("analysis.scale_factor must be positive")
        resolve_large_format_grid_shape(
            total_width_mm=self.total_width_mm, total_height_mm=self.total_height_mm,
            tile_width_mm=self.tile_width_mm, tile_height_mm=self.tile_height_mm,
        )
        domain = getattr(self.analysis, "svg_coordinate_domain", None)
        if isinstance(domain, SvgCoordinateDomain):
            plan = getattr(self.analysis, "structure_plan", None)
            margin = (plan.outline_width_mm if isinstance(plan, VectorStructurePlan) else 0.0)
            margin += 0.15 * domain.source_mm_per_unit
            grid = resolve_vector_writer_grid_mm(max(self.tile_width_mm, self.tile_height_mm) + margin)
            object.__setattr__(self, "_print_grid_mm", grid)

    def _prepared_print_regions(self) -> tuple:
        if self._print_regions is None:
            if self._print_grid_mm is None:
                return ()
            regions = project_print_regions(
                [item["geometry"] for item in self.analysis.matched_shapes],
                mm_per_unit=self.analysis.scale_factor, grid_mm=self._print_grid_mm,
            )
            object.__setattr__(self, "_print_regions", tuple(regions))
        return self._print_regions

    def build_tile_specs(self) -> list[VectorTileSpec]:
        """Resolve tile bounds from total output size and tile size."""

        return VectorTileLayoutPlanner(
            total_width_mm=self.total_width_mm,
            total_height_mm=self.total_height_mm,
            tile_width_mm=self.tile_width_mm,
            tile_height_mm=self.tile_height_mm,
        ).build_tile_specs()

    def iter_tile_specs(self) -> Iterator[VectorTileSpec]:
        """Yield tile bounds without retaining the complete grid.

        不保留完整网格，逐个产出 tile 边界。
        """

        return VectorTileLayoutPlanner(
            total_width_mm=self.total_width_mm,
            total_height_mm=self.total_height_mm,
            tile_width_mm=self.tile_width_mm,
            tile_height_mm=self.tile_height_mm,
        ).iter_tile_specs()

    def _tile_svg_bounds(self, spec: VectorTileSpec) -> tuple[float, float, float, float]:
        scale = self.analysis.scale_factor
        if self._print_grid_mm is not None:
            grid = self._print_grid_mm
            return tuple(math.floor(value / grid + 0.5) * grid / scale for value in (
                spec.x0_mm, spec.y0_mm, spec.x1_mm, spec.y1_mm,
            ))
        return (
            spec.x0_mm / scale,
            spec.y0_mm / scale,
            spec.x1_mm / scale,
            spec.y1_mm / scale,
        )

    def _build_tile_analysis(self, spec: VectorTileSpec) -> SlicedVectorTile | None:
        svg_domain = getattr(self.analysis, "svg_coordinate_domain", None)
        tile_x0_svg, tile_y0_svg, tile_x1_svg, tile_y1_svg = self._tile_svg_bounds(spec)
        slicer = TileGeometrySlicer(
            box(tile_x0_svg, tile_y0_svg, tile_x1_svg, tile_y1_svg),
            xoff=-tile_x0_svg,
            yoff=-tile_y0_svg,
        )

        if self._print_grid_mm is None:
            matched_shapes = slicer.slice_records(self.analysis.matched_shapes, geometry_key="geometry")
        else:
            grid = self._print_grid_mm
            units = tuple(math.floor(value / grid + 0.5) for value in (
                spec.x0_mm, spec.y0_mm, spec.x1_mm, spec.y1_mm,
            ))
            print_slicer = TileGeometrySlicer(box(*units), xoff=-units[0], yoff=-units[1])
            matched_shapes = []
            for record, prepared in zip(self.analysis.matched_shapes, self._prepared_print_regions(), strict=True):
                geometry = slicer.slice_geometry(record.get("geometry"))
                if geometry is not None:
                    matched_shapes.append({
                        **record, "geometry": geometry,
                        "print_geometry": print_slicer.slice_geometry(prepared) or GeometryCollection(),
                        PRINT_GRID_KEY: grid,
                    })
        clipped_shapes = slicer.slice_records(self.analysis.clipped_shapes, geometry_key="geometry")
        shape_data = slicer.slice_records(self.analysis.shape_data, geometry_key="poly")
        silhouette = slicer.slice_geometry(self.analysis.silhouette)
        structure_plan = None
        global_plan = getattr(self.analysis, "structure_plan", None)
        if isinstance(global_plan, VectorStructurePlan) and not global_plan.envelope.is_empty:
            plan_scale = global_plan.mm_per_unit
            frame_bounds_mm = tuple(value * self.analysis.scale_factor for value in (
                tile_x0_svg, tile_y0_svg, tile_x1_svg, tile_y1_svg,
            ))
            x0, y0, x1, y1 = global_plan.envelope.bounds
            structural_slicer = TileGeometrySlicer(
                box(
                    min(x0, 0.0) if spec.x0_mm == 0 else frame_bounds_mm[0] / plan_scale,
                    min(y0, 0.0) if spec.y0_mm == 0 else frame_bounds_mm[1] / plan_scale,
                    max(x1, frame_bounds_mm[2] / plan_scale) if spec.x1_mm == self.total_width_mm else frame_bounds_mm[2] / plan_scale,
                    max(y1, frame_bounds_mm[3] / plan_scale) if spec.y1_mm == self.total_height_mm else frame_bounds_mm[3] / plan_scale,
                ), xoff=-frame_bounds_mm[0] / plan_scale, yoff=-frame_bounds_mm[1] / plan_scale,
            )
            structure_plan = VectorStructurePlan(
                *(structural_slicer.slice_geometry(geometry) or GeometryCollection()
                  for geometry in (global_plan.body, global_plan.envelope, global_plan.outline)),
                outline_width_mm=global_plan.outline_width_mm,
                mm_per_unit=plan_scale,
                precision_grid=global_plan.precision_grid,
            )

        if (
            not matched_shapes and not clipped_shapes and not shape_data
            and (silhouette is None or silhouette.is_empty)
            and (structure_plan is None or structure_plan.envelope.is_empty)
        ):
            return None

        tile_analysis = VectorAnalysis(
            shape_data=shape_data,
            clipped_shapes=clipped_shapes,
            matched_shapes=matched_shapes,
            silhouette=silhouette,
            scale_factor=self.analysis.scale_factor,
            bbox=(0.0, 0.0, tile_x1_svg - tile_x0_svg, tile_y1_svg - tile_y0_svg),
            color_conf=self.analysis.color_conf,
            slot_names=list(self.analysis.slot_names),
            num_channels=self.analysis.num_channels,
            num_layers=self.analysis.num_layers,
            preview_colors=dict(self.analysis.preview_colors),
            stage_timings={},
            image_vectorizer_bounds=self.analysis.image_vectorizer_bounds,
            material_dynamic_layer_info=(
                dict(self.analysis.material_dynamic_layer_info)
                if isinstance(self.analysis.material_dynamic_layer_info, dict)
                else None
            ),
            material_solver_info=(
                dict(self.analysis.material_solver_info)
                if isinstance(self.analysis.material_solver_info, dict)
                else None
            ),
            structure_plan=structure_plan,
            svg_coordinate_domain=(
                replace(
                    svg_domain,
                    frame_origin_mm=(tile_x0_svg * self.analysis.scale_factor,
                                     tile_y0_svg * self.analysis.scale_factor),
                    frame_extent_mm=((tile_x1_svg-tile_x0_svg) * self.analysis.scale_factor,
                                     (tile_y1_svg-tile_y0_svg) * self.analysis.scale_factor),
                ) if isinstance(svg_domain, SvgCoordinateDomain) else None
            ),
        )
        return SlicedVectorTile(spec=spec, analysis=tile_analysis)

    def iter_tiles(self) -> Iterator[SlicedVectorTile]:
        """Yield non-empty tile analyses without retaining previous tiles."""

        for spec in self.iter_tile_specs():
            tile = self._build_tile_analysis(spec)
            if tile is not None:
                yield tile
                # Suspended generators retain local variables. Release the
                # yielded analysis before building the next full tile.
                tile = None

    def slice(self) -> list[SlicedVectorTile]:
        """Return every non-empty tile-local vector analysis."""

        return list(self.iter_tiles())


def inspect_svg_large_format_support(svg_path: str) -> dict:
    """Detect whether native large-format vector tiling is safe for this SVG."""

    return SvgLargeFormatSupportInspector(svg_path).inspect()

def normalize_large_format_source_basename(source_basename: str | None) -> str:
    """Normalize a source basename for safe cross-platform tile filenames."""

    base = str(source_basename or "").strip()
    if not base:
        return ""
    return _strip_temp_prefix(_sanitize(base)).strip(" ._")


def format_large_format_tile_label(*, source_basename: str | None, tile_label: str) -> str:
    """Build a stable, user-facing tile label from source name and tile id."""

    base = normalize_large_format_source_basename(source_basename)
    return f"{base}_{tile_label}" if base else tile_label


def build_tile_specs(
    *,
    total_width_mm: float,
    total_height_mm: float,
    tile_width_mm: float,
    tile_height_mm: float,
) -> list[VectorTileSpec]:
    """Resolve a row/column grid of tile specs from total output dimensions."""

    return VectorTileLayoutPlanner(
        total_width_mm=total_width_mm,
        total_height_mm=total_height_mm,
        tile_width_mm=tile_width_mm,
        tile_height_mm=tile_height_mm,
    ).build_tile_specs()


def slice_vector_analysis_into_tiles(
    *,
    analysis: VectorAnalysis,
    total_width_mm: float,
    total_height_mm: float,
    tile_width_mm: float,
    tile_height_mm: float,
    materialize: bool = True,
) -> list[SlicedVectorTile] | Iterator[SlicedVectorTile]:
    """Partition a globally analyzed VectorAnalysis into non-empty tile-local analyses."""

    tiler = VectorAnalysisTiler(
        analysis=analysis,
        total_width_mm=total_width_mm,
        total_height_mm=total_height_mm,
        tile_width_mm=tile_width_mm,
        tile_height_mm=tile_height_mm,
    )
    return tiler.slice() if materialize else tiler.iter_tiles()
