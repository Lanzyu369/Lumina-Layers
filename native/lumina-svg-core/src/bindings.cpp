#include "lumina_svg_core/paint_command.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>
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

} // namespace

PYBIND11_MODULE(_lumina_svg_core, module)
{
    module.doc() = "Native SVG paint recorder and print geometry kernel";

    py::class_<lunasvg::PaintStrokeStyle>(module, "PaintStrokeStyle")
        .def_property_readonly("width", [](const lunasvg::PaintStrokeStyle& value) { return value.width; })
        .def_property_readonly("miter_limit", [](const lunasvg::PaintStrokeStyle& value) { return value.miter_limit; })
        .def_property_readonly("dash_offset", [](const lunasvg::PaintStrokeStyle& value) { return value.dash_offset; })
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
        .def_readonly("source_kind", &lunasvg::PaintCommand::source_kind);

    py::class_<lumina_svg_core::RecorderResult>(module, "RecorderResult")
        .def_readonly("status", &lumina_svg_core::RecorderResult::status)
        .def_readonly("reason_code", &lumina_svg_core::RecorderResult::reason_code)
        .def_readonly("schema_version", &lumina_svg_core::RecorderResult::schema_version)
        .def_property_readonly("bounds", [](const lumina_svg_core::RecorderResult& value) {
            return py::make_tuple(value.bounds.x, value.bounds.y,
                                  value.bounds.w, value.bounds.h);
        })
        .def_property_readonly("commands", &commands);

    module.def("record_paint_commands", [](const py::object& path) {
        auto filename = py::str(path).cast<std::string>();
        py::gil_scoped_release release;
        return lumina_svg_core::recordPaintCommands(filename);
    }, py::arg("path"));

    module.def("record_paint_commands_svg", [](const std::string& svg) {
        py::gil_scoped_release release;
        return lumina_svg_core::recordPaintCommandsSvg(svg);
    }, py::arg("svg"));
}
