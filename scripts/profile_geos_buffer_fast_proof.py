#!/usr/bin/env python3
"""Profile the lossless GEOS dense-buffer proof kernel."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import resource
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

from shapely import from_wkb, get_num_coordinates, normalize
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry


MAX_CANDIDATE_SECONDS = 4.0
MAX_PEAK_RSS_RATIO = 1.20
MIN_REAL_COMPONENTS = 2_048
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / ".scratch" / "geos_buffer_fast_proof" / "results"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ProofLibraryError(RuntimeError):
    """Raised when the isolated proof GEOS library cannot complete a call."""


@dataclass(frozen=True)
class BufferSettings:
    """Production contour-normalization positive-buffer parameters."""

    distance: float = 0.03
    quadrant_segments: int = 1
    join_style: int = 2
    mitre_limit: float = 2.0


@dataclass(frozen=True)
class BufferMeasurement:
    """One backend result plus acceptance measurements."""

    result_wkb: bytes
    seconds: float
    peak_rss_bytes: int


class BufferBackend(Protocol):
    def buffer_wkb(self, input_wkb: bytes, settings: BufferSettings) -> bytes:
        """Return a positive-buffer result encoded as WKB."""


class ShapelyBufferBackend:
    """Current production GEOS path used as the proof oracle."""

    def buffer_wkb(self, input_wkb: bytes, settings: BufferSettings) -> bytes:
        geometry = from_wkb(input_wkb)
        result = geometry.buffer(
            settings.distance,
            quad_segs=settings.quadrant_segments,
            join_style=settings.join_style,
            mitre_limit=settings.mitre_limit,
        )
        return result.wkb


class GEOSCBufferBackend:
    """WKB-only adapter for an isolated proof ``libgeos_c``."""

    def __init__(self, library_path: Path) -> None:
        if not library_path.is_absolute():
            raise ProofLibraryError("proof GEOS library path must be absolute")
        if not library_path.is_file():
            raise ProofLibraryError(f"proof GEOS library does not exist: {library_path}")
        try:
            self._library = ctypes.CDLL(
                str(library_path),
                mode=getattr(ctypes, "RTLD_LOCAL", 0),
            )
        except OSError as exc:
            raise ProofLibraryError(
                f"failed to load proof GEOS library: {library_path}"
            ) from exc
        self._bind_reentrant_api()

    def _declare(self, name: str, argtypes: list[object], restype: object) -> None:
        try:
            function = getattr(self._library, name)
        except AttributeError as exc:
            raise ProofLibraryError(f"proof GEOS symbol is missing: {name}") from exc
        function.argtypes = argtypes
        function.restype = restype

    def _bind_reentrant_api(self) -> None:
        pointer = ctypes.c_void_p
        byte_pointer = ctypes.POINTER(ctypes.c_ubyte)
        size_pointer = ctypes.POINTER(ctypes.c_size_t)
        declarations = {
            "GEOS_init_r": ([], pointer),
            "GEOS_finish_r": ([pointer], None),
            "GEOSWKBReader_create_r": ([pointer], pointer),
            "GEOSWKBReader_destroy_r": ([pointer, pointer], None),
            "GEOSWKBReader_read_r": (
                [pointer, pointer, byte_pointer, ctypes.c_size_t],
                pointer,
            ),
            "GEOSWKBWriter_create_r": ([pointer], pointer),
            "GEOSWKBWriter_destroy_r": ([pointer, pointer], None),
            "GEOSWKBWriter_write_r": (
                [pointer, pointer, pointer, size_pointer],
                pointer,
            ),
            "GEOSBufferParams_create_r": ([pointer], pointer),
            "GEOSBufferParams_destroy_r": ([pointer, pointer], None),
            "GEOSBufferParams_setJoinStyle_r": (
                [pointer, pointer, ctypes.c_int],
                ctypes.c_int,
            ),
            "GEOSBufferParams_setMitreLimit_r": (
                [pointer, pointer, ctypes.c_double],
                ctypes.c_int,
            ),
            "GEOSBufferParams_setQuadrantSegments_r": (
                [pointer, pointer, ctypes.c_int],
                ctypes.c_int,
            ),
            "GEOSBufferWithParams_r": (
                [pointer, pointer, pointer, ctypes.c_double],
                pointer,
            ),
            "GEOSGeom_destroy_r": ([pointer, pointer], None),
            "GEOSFree_r": ([pointer, pointer], None),
        }
        for name, (argtypes, restype) in declarations.items():
            self._declare(name, argtypes, restype)

    @staticmethod
    def _require_pointer(value: object, operation: str) -> object:
        if not value:
            raise ProofLibraryError(f"proof GEOS returned null during {operation}")
        return value

    def buffer_wkb(self, input_wkb: bytes, settings: BufferSettings) -> bytes:
        library = self._library
        context = reader = writer = parameters = input_geometry = None
        result_geometry = output_buffer = None
        try:
            context = self._require_pointer(library.GEOS_init_r(), "context creation")
            reader = self._require_pointer(
                library.GEOSWKBReader_create_r(context),
                "WKB reader creation",
            )
            writer = self._require_pointer(
                library.GEOSWKBWriter_create_r(context),
                "WKB writer creation",
            )
            parameters = self._require_pointer(
                library.GEOSBufferParams_create_r(context),
                "buffer parameter creation",
            )
            source_buffer = (ctypes.c_ubyte * len(input_wkb)).from_buffer_copy(input_wkb)
            input_geometry = self._require_pointer(
                library.GEOSWKBReader_read_r(
                    context,
                    reader,
                    source_buffer,
                    len(input_wkb),
                ),
                "WKB read",
            )
            setters = (
                (
                    library.GEOSBufferParams_setQuadrantSegments_r,
                    settings.quadrant_segments,
                    "quadrant segments",
                ),
                (
                    library.GEOSBufferParams_setJoinStyle_r,
                    settings.join_style,
                    "join style",
                ),
                (
                    library.GEOSBufferParams_setMitreLimit_r,
                    settings.mitre_limit,
                    "mitre limit",
                ),
            )
            for setter, value, label in setters:
                if setter(context, parameters, value) != 1:
                    raise ProofLibraryError(
                        f"proof GEOS rejected buffer parameter: {label}"
                    )
            result_geometry = self._require_pointer(
                library.GEOSBufferWithParams_r(
                    context,
                    input_geometry,
                    parameters,
                    settings.distance,
                ),
                "positive buffer",
            )
            output_size = ctypes.c_size_t()
            output_buffer = self._require_pointer(
                library.GEOSWKBWriter_write_r(
                    context,
                    writer,
                    result_geometry,
                    ctypes.byref(output_size),
                ),
                "WKB write",
            )
            return ctypes.string_at(output_buffer, output_size.value)
        finally:
            if context:
                if output_buffer:
                    library.GEOSFree_r(context, output_buffer)
                if result_geometry:
                    library.GEOSGeom_destroy_r(context, result_geometry)
                if input_geometry:
                    library.GEOSGeom_destroy_r(context, input_geometry)
                if parameters:
                    library.GEOSBufferParams_destroy_r(context, parameters)
                if writer:
                    library.GEOSWKBWriter_destroy_r(context, writer)
                if reader:
                    library.GEOSWKBReader_destroy_r(context, reader)
                library.GEOS_finish_r(context)


def _polygon_parts(geometry: BaseGeometry) -> list[BaseGeometry]:
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    return []


def dense_geometry_metadata(
    geometry: BaseGeometry,
    *,
    require_real_density: bool = False,
) -> dict[str, object]:
    """Return density evidence and enforce the real-sample proof floor."""

    component_count = len(_polygon_parts(geometry))
    if require_real_density and component_count < MIN_REAL_COMPONENTS:
        raise ValueError(
            "real proof requires at least 2,048 polygon components; "
            f"found {component_count}"
        )
    return {
        "dense_component_count": component_count,
        "dense_coordinate_count": int(get_num_coordinates(geometry)),
    }


def extract_dense_geometry(
    processor: object,
    svg_path: Path,
    target_width_mm: float,
    *,
    require_real_density: bool = True,
) -> tuple[BaseGeometry, dict[str, object]]:
    """Run the production parse/clip policy and select the densest color region."""

    processor._parse_expand_stroke_to_fill = False
    shape_data, _, _ = processor._parse_svg(str(svg_path), target_width_mm)
    clipped, _ = processor._clip_occlusion(shape_data, return_silhouette=True)
    geometries = [
        item.get("geometry")
        for item in clipped
        if item.get("geometry") is not None and not item["geometry"].is_empty
    ]
    if not geometries:
        raise ValueError(f"SVG produced no clipped polygon geometry: {svg_path}")
    dense_geometry = max(geometries, key=lambda geometry: len(_polygon_parts(geometry)))
    metadata = {
        "source_shape_count": len(shape_data),
        "clipped_shape_count": len(clipped),
        **dense_geometry_metadata(
            dense_geometry,
            require_real_density=require_real_density,
        ),
    }
    return dense_geometry, metadata


def build_synthetic_cases() -> dict[str, BaseGeometry]:
    """Build deterministic cases that stress buffer topology and lookup paths."""

    disjoint = MultiPolygon(
        [
            box(column * 2.0, row * 2.0, column * 2.0 + 0.8, row * 2.0 + 0.8)
            for row in range(64)
            for column in range(64)
        ]
    )
    interacting_chain = MultiPolygon(
        [box(index * 1.04, 0.0, index * 1.04 + 1.0, 1.0) for index in range(128)]
    )
    shell_with_hole = Polygon(
        [(0, 0), (20, 0), (20, 20), (0, 20)],
        holes=[[(4, 4), (16, 4), (16, 16), (4, 16)]],
    )
    holes_and_nested = MultiPolygon([shell_with_hole, box(8, 8, 12, 12)])
    sharp_mitres = Polygon(
        [(0, 0), (10, 0), (5, 0.02), (10, 5), (0, 5), (5, 4.98)]
    )
    tiny_components = MultiPolygon(
        [
            box(index * 0.0001, 0, index * 0.0001 + 0.000001, 0.000001)
            for index in range(64)
        ]
    )
    merging_inputs = MultiPolygon([box(0, 0, 1, 1), box(1.04, 0, 2.04, 1)])
    return {
        "disjoint_4096": disjoint,
        "interacting_square_chain": interacting_chain,
        "holes_and_nested_shells": holes_and_nested,
        "sharp_mitres": sharp_mitres,
        "tiny_valid_components": tiny_components,
        "positive_buffer_merges_inputs": merging_inputs,
    }


def geometry_fingerprint(geometry: BaseGeometry) -> dict[str, object]:
    """Return product-semantic geometry evidence.

    返回用于产品语义比对的几何证据。

    Args:
        geometry: Polygonal Shapely geometry to summarize.

    Returns:
        Stable structural fields plus a diagnostic normalized-WKB digest.
    """

    parts = _polygon_parts(geometry)
    normalized_wkb = normalize(geometry).wkb
    return {
        "valid": bool(geometry.is_valid),
        "geom_type": geometry.geom_type,
        "components": len(parts),
        "holes": sum(len(part.interiors) for part in parts),
        "area": float(geometry.area),
        "bounds": [float(value) for value in geometry.bounds],
        "normalized_wkb_sha256": hashlib.sha256(normalized_wkb).hexdigest(),
    }


def compare_geometry(
    stock: BaseGeometry,
    candidate: BaseGeometry,
) -> dict[str, object]:
    """Compare geometries using the material-region contract.

    按耗材区域不变的产品约束比较几何结果。

    Args:
        stock: Current production GEOS result.
        candidate: Candidate optimized GEOS result.

    Returns:
        Structural fingerprints and exact topological-difference evidence.
    """

    difference = stock.symmetric_difference(candidate)
    stock_fingerprint = geometry_fingerprint(stock)
    candidate_fingerprint = geometry_fingerprint(candidate)
    same_structure = all(
        stock_fingerprint[key] == candidate_fingerprint[key]
        for key in (
            "valid",
            "geom_type",
            "components",
            "holes",
            "area",
            "bounds",
        )
    )
    return {
        "pass": bool(difference.is_empty and same_structure),
        "symmetric_difference_empty": bool(difference.is_empty),
        "symmetric_difference_area": float(difference.area),
        "stock": stock_fingerprint,
        "candidate": candidate_fingerprint,
    }


def _peak_rss_bytes() -> int:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def measure_backend(
    backend: BufferBackend,
    input_wkb: bytes,
    settings: BufferSettings,
    *,
    clock: Callable[[], float] = time.perf_counter,
    peak_rss_reader: Callable[[], int] = _peak_rss_bytes,
) -> BufferMeasurement:
    """Measure one backend without including report comparison work."""

    started = float(clock())
    result_wkb = backend.buffer_wkb(input_wkb, settings)
    seconds = float(clock()) - started
    if not isinstance(result_wkb, bytes):
        raise TypeError("buffer backend must return bytes")
    return BufferMeasurement(
        result_wkb=result_wkb,
        seconds=seconds,
        peak_rss_bytes=int(peak_rss_reader()),
    )


def evaluate_measurements(
    *,
    input_sha256: str,
    build_manifest: dict[str, object],
    stock: BufferMeasurement,
    candidate: BufferMeasurement,
    settings: BufferSettings | None = None,
    input_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Compare measurements against every proof acceptance gate."""

    settings = settings or BufferSettings()
    stock_geometry = from_wkb(stock.result_wkb)
    candidate_geometry = from_wkb(candidate.result_wkb)
    comparison = compare_geometry(stock_geometry, candidate_geometry)
    memory_limit = float(stock.peak_rss_bytes) * MAX_PEAK_RSS_RATIO
    memory_pass = (
        candidate.peak_rss_bytes <= memory_limit
        if stock.peak_rss_bytes > 0
        else candidate.peak_rss_bytes == 0
    )
    gates = {
        "geometry_exact": bool(comparison["pass"]),
        "candidate_seconds_at_most_4": candidate.seconds <= MAX_CANDIDATE_SECONDS,
        "candidate_peak_rss_at_most_1_20x_stock": bool(memory_pass),
    }
    report_input: dict[str, object] = {"sha256": input_sha256}
    if input_metadata:
        report_input.update(input_metadata)
    return {
        "schema_version": 1,
        "input": report_input,
        "build": dict(build_manifest),
        "settings": asdict(settings),
        "stock": {
            "seconds": stock.seconds,
            "peak_rss_bytes": stock.peak_rss_bytes,
        },
        "candidate": {
            "seconds": candidate.seconds,
            "peak_rss_bytes": candidate.peak_rss_bytes,
        },
        "comparison": comparison,
        "gates": gates,
        "pass": all(gates.values()),
    }


def run_proof(
    *,
    input_wkb: bytes,
    input_sha256: str,
    build_manifest: dict[str, object],
    stock_backend: BufferBackend,
    candidate_backend: BufferBackend,
    settings: BufferSettings | None = None,
    clock: Callable[[], float] = time.perf_counter,
    peak_rss_reader: Callable[[], int] = _peak_rss_bytes,
    input_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Time stock then candidate and return a deterministic proof report."""

    settings = settings or BufferSettings()
    stock = measure_backend(
        stock_backend,
        input_wkb,
        settings,
        clock=clock,
        peak_rss_reader=peak_rss_reader,
    )
    candidate = measure_backend(
        candidate_backend,
        input_wkb,
        settings,
        clock=clock,
        peak_rss_reader=peak_rss_reader,
    )
    return evaluate_measurements(
        input_sha256=input_sha256,
        build_manifest=build_manifest,
        stock=stock,
        candidate=candidate,
        settings=settings,
        input_metadata=input_metadata,
    )


def render_report_json(report: dict[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_report_markdown(report: dict[str, object]) -> str:
    status = "PASS" if report["pass"] else "FAIL"
    stock = report["stock"]
    candidate = report["candidate"]
    comparison = report["comparison"]
    gates = report["gates"]
    gate_lines = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}: `{name}`"
        for name, passed in gates.items()
    )
    return (
        f"# Dense GEOS buffer proof: {status}\n\n"
        f"- Stock: {stock['seconds']:.6f} s, {stock['peak_rss_bytes']} peak RSS bytes\n"
        f"- Candidate: {candidate['seconds']:.6f} s, "
        f"{candidate['peak_rss_bytes']} peak RSS bytes\n"
        f"- Symmetric difference empty: "
        f"{comparison['symmetric_difference_empty']}\n"
        f"- Symmetric difference area: "
        f"{comparison['symmetric_difference_area']:.17g}\n\n"
        f"## Gates\n\n{gate_lines}\n"
    )


def write_report(
    report: dict[str, object],
    out_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}.json"
    markdown_path = out_dir / f"{stem}.md"
    json_path.write_text(render_report_json(report), encoding="utf-8")
    markdown_path.write_text(render_report_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def run_synthetic_suite(
    stock_backend: BufferBackend,
    candidate_backend: BufferBackend,
    *,
    repeats: int = 2,
    settings: BufferSettings | None = None,
) -> dict[str, object]:
    """Run differential buffer checks across deterministic topology cases."""

    if repeats < 2:
        raise ValueError("synthetic proof requires at least two candidate repeats")
    settings = settings or BufferSettings()
    case_reports: dict[str, object] = {}
    for name, geometry in build_synthetic_cases().items():
        stock = measure_backend(stock_backend, geometry.wkb, settings)
        candidate_runs = [
            measure_backend(candidate_backend, geometry.wkb, settings)
            for _ in range(repeats)
        ]
        stock_geometry = from_wkb(stock.result_wkb)
        candidate_geometries = [from_wkb(run.result_wkb) for run in candidate_runs]
        comparisons = [
            compare_geometry(stock_geometry, candidate_geometry)
            for candidate_geometry in candidate_geometries
        ]
        fingerprints = [
            geometry_fingerprint(candidate_geometry)
            for candidate_geometry in candidate_geometries
        ]
        deterministic = all(fingerprint == fingerprints[0] for fingerprint in fingerprints)
        valid_polygonal = bool(
            stock_geometry.is_valid
            and stock_geometry.geom_type in ("Polygon", "MultiPolygon")
            and all(
                geometry.is_valid
                and geometry.geom_type in ("Polygon", "MultiPolygon")
                for geometry in candidate_geometries
            )
        )
        case_pass = bool(
            valid_polygonal
            and deterministic
            and all(comparison["pass"] for comparison in comparisons)
        )
        case_reports[name] = {
            "input": geometry_fingerprint(geometry),
            "stock_seconds": stock.seconds,
            "candidate_seconds": [run.seconds for run in candidate_runs],
            "comparisons": comparisons,
            "candidate_fingerprints": fingerprints,
            "deterministic": deterministic,
            "valid_polygonal": valid_polygonal,
            "pass": case_pass,
        }
    return {
        "schema_version": 1,
        "settings": asdict(settings),
        "repeats": repeats,
        "cases": case_reports,
        "pass": all(case["pass"] for case in case_reports.values()),
    }


def render_synthetic_markdown(report: dict[str, object]) -> str:
    status = "PASS" if report["pass"] else "FAIL"
    lines = [f"# Synthetic dense GEOS proof: {status}", ""]
    for name, case in report["cases"].items():
        case_status = "PASS" if case["pass"] else "FAIL"
        timings = ", ".join(f"{value:.6f}" for value in case["candidate_seconds"])
        lines.append(
            f"- {case_status} `{name}`: stock {case['stock_seconds']:.6f} s; "
            f"candidate [{timings}] s"
        )
    return "\n".join(lines) + "\n"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_real_geometry(
    svg_path: Path,
    lut_path: Path,
    color_mode: str,
    target_width_mm: float,
    *,
    require_real_density: bool = True,
) -> tuple[BaseGeometry, dict[str, object]]:
    """Construct the production processor and extract the proof geometry."""

    from core.vector_engine import VectorProcessor

    processor = VectorProcessor(str(lut_path), color_mode)
    return extract_dense_geometry(
        processor,
        svg_path,
        target_width_mm,
        require_real_density=require_real_density,
    )


def _load_build_manifest() -> dict[str, object]:
    from scripts.build_geos_buffer_fast_proof import MANIFEST_PATH

    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(
            "proof build manifest is missing; run build_geos_buffer_fast_proof.py"
        )
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid proof build manifest: {MANIFEST_PATH}")
    return data


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--target-width-mm", type=float, default=300.0)
    parser.add_argument("--lut", type=Path)
    parser.add_argument("--color-mode", default="4-Color RYBW")
    parser.add_argument("--library", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--skip-stock-timing", action="store_true")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--allow-small-real-case", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = _load_build_manifest()
    library_path = (
        args.library.resolve()
        if args.library is not None
        else Path(str(manifest["library_path"])).resolve()
    )
    candidate_backend = GEOSCBufferBackend(library_path)
    stock_backend = ShapelyBufferBackend()
    out_dir = args.out_dir.resolve()
    if args.synthetic:
        report = run_synthetic_suite(stock_backend, candidate_backend)
        report["build"] = manifest
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / "synthetic.json"
        markdown_path = out_dir / "synthetic.md"
        json_path.write_text(render_report_json(report), encoding="utf-8")
        markdown_path.write_text(render_synthetic_markdown(report), encoding="utf-8")
        print(render_report_json(report), end="")
        print(f"JSON report: {json_path}")
        print(f"Markdown report: {markdown_path}")
        return 0 if report["pass"] else 1

    if args.input is None or args.lut is None:
        raise ValueError("--input and --lut are required outside --synthetic mode")
    svg_path = args.input.resolve()
    lut_path = args.lut.resolve()
    if not svg_path.is_file():
        raise FileNotFoundError(f"SVG input does not exist: {svg_path}")
    if not lut_path.is_file():
        raise FileNotFoundError(f"LUT does not exist: {lut_path}")

    geometry, input_metadata = prepare_real_geometry(
        svg_path,
        lut_path,
        args.color_mode,
        args.target_width_mm,
        require_real_density=not args.allow_small_real_case,
    )
    input_wkb = geometry.wkb
    settings = BufferSettings()
    common = {
        "input_sha256": _sha256_file(svg_path),
        "build_manifest": manifest,
        "settings": settings,
        "input_metadata": {
            "path": str(svg_path),
            "target_width_mm": args.target_width_mm,
            "dense_gate_enforced": not args.allow_small_real_case,
            **input_metadata,
        },
    }
    if args.skip_stock_timing:
        stock_wkb = stock_backend.buffer_wkb(input_wkb, settings)
        stock = BufferMeasurement(stock_wkb, -1.0, _peak_rss_bytes())
        candidate = measure_backend(candidate_backend, input_wkb, settings)
        report = evaluate_measurements(stock=stock, candidate=candidate, **common)
        report["acceptance_mode"] = False
        report["gates"]["stock_timing_present"] = False
        report["pass"] = False
    else:
        report = run_proof(
            input_wkb=input_wkb,
            stock_backend=stock_backend,
            candidate_backend=candidate_backend,
            **common,
        )
        report["acceptance_mode"] = True

    stem = f"{svg_path.stem}-{args.target_width_mm:g}mm"
    json_path, markdown_path = write_report(report, out_dir, stem)
    print(render_report_json(report), end="")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0 if report["pass"] or args.skip_stock_timing else 1


if __name__ == "__main__":
    raise SystemExit(main())
