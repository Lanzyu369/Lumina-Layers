from __future__ import annotations

from dataclasses import dataclass
import math
import xml.etree.ElementTree as ET

from shapely import affinity
from shapely.geometry import box
from shapely.validation import make_valid

from core.vector_engine import VectorAnalysis, VectorProcessor

SVG_LARGE_FORMAT_PREVIEW_FALLBACK_WARNING = (
    "Native vector large-format is unavailable for this SVG; large-format generation will fall back to raster tiling."
)
SVG_LARGE_FORMAT_GENERATE_FALLBACK_WARNING = "Raster fallback was used for this large-format SVG request."
SVG_LARGE_FORMAT_DENSITY_REDUCED_WARNING = (
    "Raster fallback density was reduced to keep SVG large-format generation within the pixel budget."
)

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
class SvgRasterFallbackDensityPlanner:
    """Choose a raster density that stays within the large-format pixel budget."""

    total_width_mm: float
    total_height_mm: float
    desired_pixels_per_mm: float = 10.0
    min_pixels_per_mm: float = 2.0
    max_total_pixels: int = 12_000_000

    def choose_density(self) -> tuple[float, list[str]]:
        """Choose a bounded raster fallback density for SVG large-format generation."""

        warnings: list[str] = []
        area_mm2 = max(self.total_width_mm * self.total_height_mm, 1.0)
        max_ppm = math.sqrt(self.max_total_pixels / area_mm2)
        chosen = min(self.desired_pixels_per_mm, max_ppm)
        if max_ppm >= self.min_pixels_per_mm:
            chosen = max(self.min_pixels_per_mm, chosen)
        else:
            chosen = max(chosen, 0.25)
        if chosen < self.desired_pixels_per_mm:
            warnings.append(SVG_LARGE_FORMAT_DENSITY_REDUCED_WARNING)
        return chosen, warnings


@dataclass(frozen=True)
class VectorTileLayoutPlanner:
    """Resolve the large-format tile grid independently of vector content."""

    total_width_mm: float
    total_height_mm: float
    tile_width_mm: float
    tile_height_mm: float

    def build_tile_specs(self) -> list[VectorTileSpec]:
        """Resolve tile bounds from total output size and tile size."""

        for name, value in (
            ("total_width_mm", self.total_width_mm),
            ("total_height_mm", self.total_height_mm),
            ("tile_width_mm", self.tile_width_mm),
            ("tile_height_mm", self.tile_height_mm),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")

        cols = max(1, math.ceil(self.total_width_mm / self.tile_width_mm))
        rows = max(1, math.ceil(self.total_height_mm / self.tile_height_mm))
        specs: list[VectorTileSpec] = []

        for row in range(rows):
            for col in range(cols):
                x0_mm = col * self.tile_width_mm
                y0_mm = row * self.tile_height_mm
                x1_mm = min(x0_mm + self.tile_width_mm, self.total_width_mm)
                y1_mm = min(y0_mm + self.tile_height_mm, self.total_height_mm)
                specs.append(
                    VectorTileSpec(
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
                )
        return specs


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

        try:
            sliced = geometry.intersection(self.tile_box)
        except Exception:
            try:
                sliced = make_valid(geometry).intersection(self.tile_box)
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

    def __post_init__(self) -> None:
        if self.analysis.scale_factor <= 0:
            raise ValueError("analysis.scale_factor must be positive")

    def build_tile_specs(self) -> list[VectorTileSpec]:
        """Resolve tile bounds from total output size and tile size."""

        return VectorTileLayoutPlanner(
            total_width_mm=self.total_width_mm,
            total_height_mm=self.total_height_mm,
            tile_width_mm=self.tile_width_mm,
            tile_height_mm=self.tile_height_mm,
        ).build_tile_specs()

    def _tile_svg_bounds(self, spec: VectorTileSpec) -> tuple[float, float, float, float]:
        scale = self.analysis.scale_factor
        return (
            spec.x0_mm / scale,
            spec.y0_mm / scale,
            spec.x1_mm / scale,
            spec.y1_mm / scale,
        )

    def _build_tile_analysis(self, spec: VectorTileSpec) -> SlicedVectorTile | None:
        tile_x0_svg, tile_y0_svg, tile_x1_svg, tile_y1_svg = self._tile_svg_bounds(spec)
        slicer = TileGeometrySlicer(
            box(tile_x0_svg, tile_y0_svg, tile_x1_svg, tile_y1_svg),
            xoff=-tile_x0_svg,
            yoff=-tile_y0_svg,
        )

        matched_shapes = slicer.slice_records(self.analysis.matched_shapes, geometry_key="geometry")
        clipped_shapes = slicer.slice_records(self.analysis.clipped_shapes, geometry_key="geometry")
        shape_data = slicer.slice_records(self.analysis.shape_data, geometry_key="poly")
        silhouette = slicer.slice_geometry(self.analysis.silhouette)
        if not matched_shapes and not clipped_shapes and not shape_data and (silhouette is None or silhouette.is_empty):
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
        )
        return SlicedVectorTile(spec=spec, analysis=tile_analysis)

    def slice(self) -> list[SlicedVectorTile]:
        """Return every non-empty tile-local vector analysis."""

        tiles: list[SlicedVectorTile] = []
        for spec in self.build_tile_specs():
            tile = self._build_tile_analysis(spec)
            if tile is not None:
                tiles.append(tile)
        return tiles


def inspect_svg_large_format_support(svg_path: str) -> dict:
    """Detect whether native large-format vector tiling is safe for this SVG."""

    return SvgLargeFormatSupportInspector(svg_path).inspect()

def choose_svg_raster_fallback_density(
    *,
    total_width_mm: float,
    total_height_mm: float,
    desired_pixels_per_mm: float = 10.0,
    min_pixels_per_mm: float = 2.0,
    max_total_pixels: int = 12_000_000,
) -> tuple[float, list[str]]:
    """Choose a bounded raster fallback density for SVG large-format generation."""

    planner = SvgRasterFallbackDensityPlanner(
        total_width_mm=total_width_mm,
        total_height_mm=total_height_mm,
        desired_pixels_per_mm=desired_pixels_per_mm,
        min_pixels_per_mm=min_pixels_per_mm,
        max_total_pixels=max_total_pixels,
    )
    return planner.choose_density()


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
) -> list[SlicedVectorTile]:
    """Partition a globally analyzed VectorAnalysis into non-empty tile-local analyses."""

    return VectorAnalysisTiler(
        analysis=analysis,
        total_width_mm=total_width_mm,
        total_height_mm=total_height_mm,
        tile_width_mm=tile_width_mm,
        tile_height_mm=tile_height_mm,
    ).slice()
