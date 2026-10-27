// Target-grid projection shares the parser's canonical boundary rule.
#include "canonical_boundary.h"
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <cmath>
#include <stdexcept>
#include <utility>
#include <vector>

namespace py = pybind11;
namespace cb = lumina::canonical;
namespace {
using Path = cb::PathOf<int64_t>;
using Node = cb::CanonicalNode<int64_t>;

struct ParsedRegions {
    std::vector<Path> paths;
    std::vector<std::pair<std::size_t, std::size_t>> ranges;
};

void appendPolygons(const Node& node, py::list& output);

ParsedRegions readRegions(
    const py::iterable& regions,
    double units_per_coordinate,
    bool require_integer_coordinates) {
    ParsedRegions parsed;
    for (const auto region : regions) {
        const auto start = parsed.paths.size();
        for (const auto ring : py::reinterpret_borrow<py::iterable>(region)) {
            const auto input = py::array_t<
                double, py::array::c_style | py::array::forcecast>::ensure(ring);
            if (!input || input.ndim() != 2 || input.shape(1) != 2)
                throw std::invalid_argument("Projection rings must have shape (N, 2)");
            const auto values = input.unchecked<2>();
            Path path;
            for (py::ssize_t i = 0; i < input.shape(0); ++i) {
                const long double x =
                    static_cast<long double>(values(i, 0)) * units_per_coordinate;
                const long double y =
                    static_cast<long double>(values(i, 1)) * units_per_coordinate;
                if (!std::isfinite(x) || !std::isfinite(y)
                    || std::abs(x) > 0x1p52L || std::abs(y) > 0x1p52L)
                    throw std::invalid_argument(
                        "Projection exceeds exact downstream integer coordinates");
                if (require_integer_coordinates
                    && (std::trunc(x) != x || std::trunc(y) != y))
                    throw std::invalid_argument(
                        "Canonical grid coordinates must be exact integers");
                const Clipper2Lib::Point64 point(
                    require_integer_coordinates ? static_cast<int64_t>(x)
                                                : std::llround(x),
                    require_integer_coordinates ? static_cast<int64_t>(y)
                                                : std::llround(y));
                if (path.empty() || path.back() != point) path.push_back(point);
            }
            if (path.size() > 1 && path.front() == path.back()) path.pop_back();
            parsed.paths.push_back(std::move(path));
        }
        parsed.ranges.emplace_back(start, parsed.paths.size());
    }
    return parsed;
}

py::list emitRegions(const std::vector<Node>& trees) {
    py::list output;
    for (const auto& tree : trees) {
        py::list polygons;
        appendPolygons(tree, polygons);
        output.append(polygons);
    }
    return output;
}

py::array_t<int64_t> coordinates(const Path& path) {
    py::array_t<int64_t> output({static_cast<py::ssize_t>(path.size() + 1), py::ssize_t{2}});
    auto data = output.mutable_unchecked<2>();
    for (std::size_t i = 0; i <= path.size(); ++i) {
        const auto& point = path[i % path.size()];
        data(i, 0) = point.x;
        data(i, 1) = point.y;
    }
    return output;
}

void appendPolygons(const Node& node, py::list& output) {
    for (const auto& child : node.children) {
        if (!child->is_hole && !child->path.empty()) {
            py::list holes;
            for (const auto& hole : child->children) {
                if (hole->is_hole && !hole->path.empty())
                    holes.append(coordinates(hole->path));
            }
            output.append(py::make_tuple(coordinates(child->path), holes));
        }
        appendPolygons(*child, output);
    }
}

py::list projectRegions(const py::iterable& regions, double units_per_coordinate) {
    if (!std::isfinite(units_per_coordinate) || units_per_coordinate <= 0)
        throw std::invalid_argument("Target-grid scale must be positive and finite");
    const auto parsed = readRegions(regions, units_per_coordinate, false);
    std::vector<Node> trees(parsed.ranges.size());
    {
        py::gil_scoped_release release;
        // Global noding preserves paint ownership through the stable ring ranges.
        // In particular, a vertex on another paint's edge is inserted in both.
        auto noded = cb::NodeToGrid<int64_t>(parsed.paths);
        for (std::size_t i = 0; i < parsed.ranges.size(); ++i) {
            const auto [begin, end] = parsed.ranges[i];
            std::vector<Path> region(noded.begin() + begin, noded.begin() + end);
            // Snap rounding can turn an inserted intersection into a tiny
            // local crossing. Resolve the labelled region's winding on the
            // target integer grid before the shared canonical area export.
            Clipper2Lib::Clipper64 clipper;
            clipper.PreserveCollinear(true);
            clipper.AddSubject(region);
            Clipper2Lib::PolyTree64 coverage;
            if (!clipper.Execute(Clipper2Lib::ClipType::Union,
                                 Clipper2Lib::FillRule::NonZero, coverage))
                throw std::runtime_error("Target-grid region union failed");
            const auto paths = cb::PolyTreePaths<int64_t>(coverage);
            cb::BuildFacesFromNoded<int64_t>(cb::NodeToGrid<int64_t>(paths), trees[i]);
        }
    }
    return emitRegions(trees);
}

py::list canonicalizeGridRegions(const py::iterable& regions) {
    const auto parsed = readRegions(regions, 1.0, true);
    std::vector<Node> trees(parsed.ranges.size());
    {
        py::gil_scoped_release release;
        for (std::size_t i = 0; i < parsed.ranges.size(); ++i) {
            const auto [begin, end] = parsed.ranges[i];
            const std::vector<Path> region(
                parsed.paths.begin() + begin, parsed.paths.begin() + end);
            // Owned coverage is already quantized and resolved by paint order.
            // Rebuild its canonical faces without a second boolean cleanup.
            cb::BuildFilledFaces<int64_t>(region, trees[i]);
        }
    }
    return emitRegions(trees);
}
} // namespace

void bindCoordinateProjection(py::module_& module) {
    module.def("project_regions_to_grid", &projectRegions,
               py::arg("regions"), py::arg("units_per_coordinate"),
               "Project labelled rings onto one canonical integer grid; ties round away from zero.");
    module.def("canonicalize_grid_regions", &canonicalizeGridRegions,
               py::arg("regions"),
               "Canonicalize already-owned integer-grid coverage without changing its fill.");
}
