#include "lumina_svg_core/paint_command.h"
#include "lumina_svg_core/geometry_kernel.h"
#include "lumina_svg_core/result.h"

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl/filesystem.h>
#include <pybind11/stl.h>

#include <array>
#include <chrono>
#include <filesystem>
#include <string>

namespace py = pybind11;

namespace {

const char* commandKindName(lunasvg::PaintCommandKind kind)
{
    switch(kind) {
    case lunasvg::PaintCommandKind::Fill: return "fill";
    case lunasvg::PaintCommandKind::Stroke: return "stroke";
    case lunasvg::PaintCommandKind::ClipBegin: return "clip_begin";
    case lunasvg::PaintCommandKind::ClipEnd: return "clip_end";
    case lunasvg::PaintCommandKind::GroupBegin: return "group_begin";
    case lunasvg::PaintCommandKind::GroupEnd: return "group_end";
    }
    return "unknown";
}

const char* pathVerbName(lunasvg::PaintPathVerb verb)
{
    switch(verb) {
    case lunasvg::PaintPathVerb::MoveTo: return "move_to";
    case lunasvg::PaintPathVerb::LineTo: return "line_to";
    case lunasvg::PaintPathVerb::CubicTo: return "cubic_to";
    case lunasvg::PaintPathVerb::Close: return "close";
    }
    return "unknown";
}

const char* lineCapName(lunasvg::PaintLineCap lineCap)
{
    switch(lineCap) {
    case lunasvg::PaintLineCap::Butt: return "butt";
    case lunasvg::PaintLineCap::Round: return "round";
    case lunasvg::PaintLineCap::Square: return "square";
    }
    return "unknown";
}

const char* lineJoinName(lunasvg::PaintLineJoin lineJoin)
{
    switch(lineJoin) {
    case lunasvg::PaintLineJoin::Miter: return "miter";
    case lunasvg::PaintLineJoin::Round: return "round";
    case lunasvg::PaintLineJoin::Bevel: return "bevel";
    }
    return "unknown";
}

py::tuple pathVerbs(const lunasvg::PaintCommand& command)
{
    py::tuple values(command.path_verbs.size());
    for(size_t index = 0; index < command.path_verbs.size(); ++index)
        values[index] = pathVerbName(command.path_verbs[index]);
    return values;
}

py::tuple pathPoints(const lunasvg::PaintCommand& command)
{
    py::tuple values(command.path_points.size());
    for(size_t index = 0; index < command.path_points.size(); ++index) {
        const auto& point = command.path_points[index];
        values[index] = py::make_tuple(point.x, point.y);
    }
    return values;
}

py::tuple commands(const lumina_svg_core::RecorderResult& result)
{
    py::tuple values(result.commands.size());
    for(size_t index = 0; index < result.commands.size(); ++index)
        values[index] = py::cast(result.commands[index]);
    return values;
}

py::capsule arrayOwner(const std::shared_ptr<lumina_svg_core::NativeResult>& owner)
{
    return py::capsule(
        new std::shared_ptr<lumina_svg_core::NativeResult>(owner),
        [](void* value) {
            delete static_cast<std::shared_ptr<lumina_svg_core::NativeResult>*>(value);
        });
}

template<typename T>
py::array readOnlyVector(
    const std::vector<T>& values,
    const std::shared_ptr<lumina_svg_core::NativeResult>& owner)
{
    py::array array(
        py::dtype::of<T>(),
        {static_cast<py::ssize_t>(values.size())},
        {static_cast<py::ssize_t>(sizeof(T))},
        values.data(),
        arrayOwner(owner));
    array.attr("setflags")(false);
    return array;
}

py::array coordinates(const lumina_svg_core::GeometryCollectionView& view)
{
    const auto& values = view.collection->coordinates;
    py::array array(
        py::dtype::of<int64_t>(),
        {static_cast<py::ssize_t>(values.size() / 2), py::ssize_t(2)},
        {static_cast<py::ssize_t>(sizeof(int64_t) * 2),
         static_cast<py::ssize_t>(sizeof(int64_t))},
        values.data(),
        arrayOwner(view.owner));
    array.attr("setflags")(false);
    return array;
}

py::array rgba(const lumina_svg_core::GeometryCollectionView& view)
{
    const auto& values = view.collection->rgba;
    py::array array(
        py::dtype::of<uint8_t>(),
        {static_cast<py::ssize_t>(values.size() / 4), py::ssize_t(4)},
        {py::ssize_t(4), py::ssize_t(1)},
        values.data(),
        arrayOwner(view.owner));
    array.attr("setflags")(false);
    return array;
}

lumina_svg_core::GeometryCollectionView collectionView(
    lumina_svg_core::NativeResult& result,
    const lumina_svg_core::GeometryCollection& collection)
{
    return {result.shared_from_this(), &collection};
}

} // namespace

PYBIND11_MODULE(_lumina_svg_core, module)
{
    module.doc() = "Native SVG paint recorder and print geometry kernel";

    py::class_<lunasvg::PaintStrokeStyle>(module, "PaintStrokeStyle")
        .def_property_readonly("width", [](const lunasvg::PaintStrokeStyle& value) { return value.width; })
        .def_property_readonly("miter_limit", [](const lunasvg::PaintStrokeStyle& value) { return value.miter_limit; })
        .def_property_readonly("dash_offset", [](const lunasvg::PaintStrokeStyle& value) { return value.dash_offset; })
        .def_property_readonly("line_cap", [](const lunasvg::PaintStrokeStyle& value) {
            return lineCapName(value.line_cap);
        })
        .def_property_readonly("line_join", [](const lunasvg::PaintStrokeStyle& value) {
            return lineJoinName(value.line_join);
        })
        .def_property_readonly("dash_array", [](const lunasvg::PaintStrokeStyle& value) {
            py::tuple values(value.dash_array.size());
            for(size_t index = 0; index < value.dash_array.size(); ++index)
                values[index] = value.dash_array[index];
            return values;
        });

    py::class_<lunasvg::PaintCommand>(module, "PaintCommand")
        .def_property_readonly("kind", [](const lunasvg::PaintCommand& value) {
            return commandKindName(value.kind);
        })
        .def_property_readonly("path_verbs", &pathVerbs)
        .def_property_readonly("path_points", &pathPoints)
        .def_property_readonly("rgba", [](const lunasvg::PaintCommand& value) {
            return py::make_tuple(value.rgba[0], value.rgba[1],
                                  value.rgba[2], value.rgba[3]);
        })
        .def_property_readonly("matrix", [](const lunasvg::PaintCommand& value) {
            return py::make_tuple(value.transform.a, value.transform.b,
                                  value.transform.c, value.transform.d,
                                  value.transform.e, value.transform.f);
        })
        .def_property_readonly("fill_rule", [](const lunasvg::PaintCommand& value) {
            return value.fill_rule == lunasvg::PaintFillRule::EvenOdd
                ? "evenodd" : "nonzero";
        })
        .def_readonly("stroke", &lunasvg::PaintCommand::stroke)
        .def_readonly("group_opacity", &lunasvg::PaintCommand::group_opacity)
        .def_readonly("source_index", &lunasvg::PaintCommand::source_index)
        .def_readonly(
            "relative_path_operation_count",
            &lunasvg::PaintCommand::relative_path_operation_count)
        .def_readonly(
            "transform_operation_count",
            &lunasvg::PaintCommand::transform_operation_count)
        .def_readonly(
            "path_input_precision_error",
            &lunasvg::PaintCommand::path_input_precision_error)
        .def_readonly(
            "transform_linear_precision_error",
            &lunasvg::PaintCommand::transform_linear_precision_error)
        .def_readonly(
            "transform_translation_precision_error",
            &lunasvg::PaintCommand::transform_translation_precision_error)
        .def_readonly("source_kind", &lunasvg::PaintCommand::source_kind);

    py::class_<lumina_svg_core::RecorderResult>(module, "RecorderResult")
        .def_readonly("status", &lumina_svg_core::RecorderResult::status)
        .def_readonly("reason_code", &lumina_svg_core::RecorderResult::reason_code)
        .def_readonly("schema_version", &lumina_svg_core::RecorderResult::schema_version)
        .def_property_readonly("bounds", [](const lumina_svg_core::RecorderResult& value) {
            return py::make_tuple(value.bounds.x, value.bounds.y,
                                  value.bounds.w, value.bounds.h);
        })
        .def_property_readonly("viewport", [](const lumina_svg_core::RecorderResult& value) {
            return py::make_tuple(value.viewport.x, value.viewport.y,
                                  value.viewport.w, value.viewport.h);
        })
        .def_readonly("image_vectorizer_origin",
                      &lumina_svg_core::RecorderResult::image_vectorizer_origin)
        .def_property_readonly("commands", &commands);

    py::class_<lumina_svg_core::GeometryCollectionView>(module, "GeometryCollection")
        .def_property_readonly("coordinates", &coordinates)
        .def_property_readonly("ring_offsets", [](const lumina_svg_core::GeometryCollectionView& view) {
            return readOnlyVector(view.collection->ring_offsets, view.owner);
        })
        .def_property_readonly("polygon_offsets", [](const lumina_svg_core::GeometryCollectionView& view) {
            return readOnlyVector(view.collection->polygon_offsets, view.owner);
        })
        .def_property_readonly("geometry_offsets", [](const lumina_svg_core::GeometryCollectionView& view) {
            return readOnlyVector(view.collection->geometry_offsets, view.owner);
        })
        .def_property_readonly("hole_parent", [](const lumina_svg_core::GeometryCollectionView& view) {
            return readOnlyVector(view.collection->hole_parent, view.owner);
        })
        .def_property_readonly("rgba", &rgba)
        .def_property_readonly("draw_indices", [](const lumina_svg_core::GeometryCollectionView& view) {
            return readOnlyVector(view.collection->draw_indices, view.owner);
        })
        .def_property_readonly("source_indices", [](const lumina_svg_core::GeometryCollectionView& view) {
            return readOnlyVector(view.collection->source_indices, view.owner);
        })
        .def_property_readonly("source_kinds", [](const lumina_svg_core::GeometryCollectionView& view) {
            return readOnlyVector(view.collection->source_kinds, view.owner);
        })
        .def_property_readonly("geometry_count", [](const lumina_svg_core::GeometryCollectionView& view) {
            return view.collection->geometryCount();
        })
        .def_property_readonly("component_count", [](const lumina_svg_core::GeometryCollectionView& view) {
            return view.collection->componentCount();
        })
        .def_property_readonly("hole_count", [](const lumina_svg_core::GeometryCollectionView& view) {
            return view.collection->holeCount();
        });

    py::class_<lumina_svg_core::NativeResult,
               std::shared_ptr<lumina_svg_core::NativeResult>>(module, "NativeResult")
        .def_readonly("status", &lumina_svg_core::NativeResult::status)
        .def_readonly("reason_code", &lumina_svg_core::NativeResult::reason_code)
        .def_readonly("schema_version", &lumina_svg_core::NativeResult::schema_version)
        .def_property_readonly("bbox", [](const lumina_svg_core::NativeResult& value) {
            return py::make_tuple(value.bbox[0], value.bbox[1],
                                  value.bbox[2], value.bbox[3]);
        })
        .def_property_readonly("viewport_bounds", [](const lumina_svg_core::NativeResult& value) {
            return py::make_tuple(value.viewport_bounds[0],
                                  value.viewport_bounds[1],
                                  value.viewport_bounds[2],
                                  value.viewport_bounds[3]);
        })
        .def_readonly("image_vectorizer_origin",
                      &lumina_svg_core::NativeResult::image_vectorizer_origin)
        .def_readonly("scale_factor", &lumina_svg_core::NativeResult::scale_factor)
        .def_readonly("grid_to_source_unit", &lumina_svg_core::NativeResult::grid_to_source_unit)
        .def_readonly("max_flattening_error_mm", &lumina_svg_core::NativeResult::max_flattening_error_mm)
        .def_readonly("max_quantization_error_mm", &lumina_svg_core::NativeResult::max_quantization_error_mm)
        .def_readonly(
            "legacy_contour_normalization_identity",
            &lumina_svg_core::NativeResult::legacy_contour_normalization_identity)
        .def_readonly(
            "legacy_contour_normalization_compatible",
            &lumina_svg_core::NativeResult::legacy_contour_normalization_compatible)
        .def_readonly(
            "legacy_area_filter_identity",
            &lumina_svg_core::NativeResult::legacy_area_filter_identity)
        .def_readonly(
            "legacy_curve_tolerance_compatible",
            &lumina_svg_core::NativeResult::legacy_curve_tolerance_compatible)
        .def_readonly("recorder_seconds", &lumina_svg_core::NativeResult::recorder_seconds)
        .def_readonly("kernel_seconds", &lumina_svg_core::NativeResult::kernel_seconds)
        .def_readonly("bounds_seconds", &lumina_svg_core::NativeResult::bounds_seconds)
        .def_readonly("replay_seconds", &lumina_svg_core::NativeResult::replay_seconds)
        .def_readonly("topology_seconds", &lumina_svg_core::NativeResult::topology_seconds)
        .def_readonly("legacy_raw_seconds", &lumina_svg_core::NativeResult::legacy_raw_seconds)
        .def_readonly("composite_seconds", &lumina_svg_core::NativeResult::composite_seconds)
        .def_readonly("legacy_visible_seconds", &lumina_svg_core::NativeResult::legacy_visible_seconds)
        .def_readonly("export_seconds", &lumina_svg_core::NativeResult::export_seconds)
        .def_readonly("result_conversion_seconds", &lumina_svg_core::NativeResult::result_conversion_seconds)
        .def_property_readonly("raw", [](lumina_svg_core::NativeResult& value) {
            return collectionView(value, value.raw);
        })
        .def_property_readonly("visible", [](lumina_svg_core::NativeResult& value) {
            return collectionView(value, value.visible);
        })
        .def_property_readonly("silhouette", [](lumina_svg_core::NativeResult& value) {
            return collectionView(value, value.silhouette);
        });

    module.def("record_paint_commands", [](const std::filesystem::path& path) {
        py::gil_scoped_release release;
        return lumina_svg_core::recordPaintCommandsPath(path);
    }, py::arg("path"));

    module.def("record_paint_commands_svg", [](const std::string& svg) {
        py::gil_scoped_release release;
        return lumina_svg_core::recordPaintCommandsSvg(svg);
    }, py::arg("svg"));

    module.def(
        "_set_thread_launch_failure_after_for_testing",
        &lumina_svg_core::setThreadLaunchFailureAfterForTesting,
        py::arg("successful_launches"));

    module.def("analyze_svg", [](const std::filesystem::path& path,
                                  double targetWidthMm,
                                  double toleranceMm,
                                  bool allowStrokes,
                                  double legacyCloseDeltaSourceUnits,
                                  double legacyMinimumPaintAreaFactor) {
        std::shared_ptr<lumina_svg_core::NativeResult> result;
        {
            py::gil_scoped_release release;
            result = lumina_svg_core::analyzeSvgPath(
                path, targetWidthMm, toleranceMm, allowStrokes,
                legacyCloseDeltaSourceUnits, legacyMinimumPaintAreaFactor);
        }
        const auto conversionStarted = std::chrono::steady_clock::now();
        auto value = py::cast(result);
        result->result_conversion_seconds = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - conversionStarted).count();
        return value;
    }, py::arg("path"), py::arg("target_width_mm"),
       py::arg("tolerance_mm"), py::arg("allow_strokes") = true,
       py::arg("legacy_close_delta_source_units") = 0.0,
       py::arg("legacy_minimum_paint_area_factor") = 0.0);

    module.def("analyze_svg_svg", [](const std::string& svg,
                                      double targetWidthMm,
                                      double toleranceMm,
                                      bool allowStrokes,
                                      double legacyCloseDeltaSourceUnits,
                                      double legacyMinimumPaintAreaFactor) {
        std::shared_ptr<lumina_svg_core::NativeResult> result;
        {
            py::gil_scoped_release release;
            result = lumina_svg_core::analyzeSvgData(
                svg, targetWidthMm, toleranceMm, allowStrokes,
                legacyCloseDeltaSourceUnits, legacyMinimumPaintAreaFactor);
        }
        const auto conversionStarted = std::chrono::steady_clock::now();
        auto value = py::cast(result);
        result->result_conversion_seconds = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - conversionStarted).count();
        return value;
    }, py::arg("svg"), py::arg("target_width_mm"),
       py::arg("tolerance_mm"), py::arg("allow_strokes") = true,
       py::arg("legacy_close_delta_source_units") = 0.0,
       py::arg("legacy_minimum_paint_area_factor") = 0.0);
}
