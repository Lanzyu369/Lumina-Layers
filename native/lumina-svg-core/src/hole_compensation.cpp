// Copyright 2025 neroued (ChromaPrint3D), Apache-2.0.
// Modified for Lumina Studio: reuse the area/perimeter hole criteria and
// 100000/mm grid from vector_mesh_builder.cpp, without offsets, simplification,
// color grouping, or mesh operations. Canonical noded boundary faces preserve
// painted islands and derive filled coverage after one global union.
// See THIRD_PARTY_NOTICES.md and THIRD_PARTY_LICENSES/ChromaPrint3D.txt.

#include <clipper2/clipper.h>
#include "canonical_boundary.h"
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <memory>
#include <numeric>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace py = pybind11;
namespace clipper = Clipper2Lib;
namespace {

// This surface (hole-compensation criteria) evaluates in floating point and
// never snaps to the integer grid, so one noding pass already settles its
// linework. The integer area output needs the bounded settle pass the shared
// rule applies; both go through the same implementation.
constexpr double kClipperScale = 100000.0;

using CanonicalPoint = lumina::canonical::PointOf<long double>;
using CanonicalPath = lumina::canonical::PathOf<long double>;
using CanonicalNode = lumina::canonical::CanonicalNode<long double>;
using SimpleRing = lumina::canonical::SimpleRing<long double>;
using Noder = lumina::canonical::BoundaryNoder<long double>;

struct PolygonParts {
  const CanonicalPath* shell;
  std::vector<const CanonicalPath*> interiors;
};

inline long double Cross(const CanonicalPoint& a, const CanonicalPoint& b) {
  return lumina::canonical::Cross<long double>(a, b);
}

inline long double SignedArea(const CanonicalPath& path) {
  return lumina::canonical::SignedArea<long double>(path);
}

inline void SplitTouchingRing(const CanonicalPath& path,
                              std::vector<SimpleRing>& rings) {
  lumina::canonical::SplitTouchingRing<long double>(path, rings);
}

inline void BuildRingTree(std::vector<SimpleRing> rings, CanonicalNode& output) {
  lumina::canonical::BuildRingTree<long double>(std::move(rings), output);
}

// Hole-compensation entry: the compensated coverage arrives as a PolyTree and
// is re-expressed with the shared rule.
void NormalizeTouchingRings(const clipper::PolyTree64& input, CanonicalNode& output) {
  const auto paths = lumina::canonical::PolyTreePaths<long double>(input);
  lumina::canonical::BuildRingsFromNoded<long double>(Noder(paths).Run(), output);
}

// Hole-compensation entry: every path is noded and oriented with the
// represented area on one side. The shared rule's face walk re-expresses
// them as rings that meet only along their boundaries.
inline std::vector<SimpleRing> TraceBoundaryFaces(
    const std::vector<CanonicalPath>& paths) {
  return lumina::canonical::TraceFilledFaces<long double>(paths);
}

void ValidateThreshold(double value, const char* name) {
  if (!std::isfinite(value) || value < 0.0) {
    throw std::invalid_argument(std::string(name) +
                                " must be finite and nonnegative");
  }
}

int64_t CoordinateToGrid(double value) {
  const long double scaled = static_cast<long double>(value) * kClipperScale;
  if (!std::isfinite(value) ||
      std::abs(scaled) > static_cast<long double>(clipper::MAX_COORD)) {
    throw std::invalid_argument(
        "SVG compensation coordinate is non-finite or outside the native range");
  }
  return static_cast<int64_t>(std::llround(scaled));
}

clipper::Paths64 ReadRings(const py::iterable& rings) {
  clipper::Paths64 paths;
  for (const py::handle ring : rings) {
    auto coordinates =
        py::array_t<double, py::array::c_style | py::array::forcecast>::ensure(ring);
    if (!coordinates || coordinates.ndim() != 2 || coordinates.shape(1) != 2) {
      throw std::invalid_argument("SVG compensation rings require float64 Nx2 coordinates");
    }
    const auto values = coordinates.unchecked<2>();
    clipper::Path64 path;
    path.reserve(static_cast<std::size_t>(coordinates.shape(0)));
    for (py::ssize_t index = 0; index < coordinates.shape(0); ++index) {
      path.emplace_back(CoordinateToGrid(values(index, 0)),
                        CoordinateToGrid(values(index, 1)));
    }
    if (path.size() >= 3) paths.push_back(std::move(path));
  }
  return paths;
}

// Adapted from ChromaPrint3D PathPerimeter: convert operands before subtraction.
double PathPerimeter(const CanonicalPath& path) {
  double length = 0.0;
  for (std::size_t index = 0; index < path.size(); ++index) {
    const auto& current = path[index];
    const auto& next = path[(index + 1) % path.size()];
    const long double dx = next.x - current.x;
    const long double dy = next.y - current.y;
    length += std::hypot(dx, dy);
  }
  return length;
}

bool SelectHole(const PolygonParts& hole, double max_area, double max_width) {
  long double area = std::abs(SignedArea(*hole.shell));
  double perimeter = PathPerimeter(*hole.shell);
  for (const auto* island : hole.interiors) {
    area -= std::abs(SignedArea(*island));
    perimeter += PathPerimeter(*island);
  }
  area /= kClipperScale * kClipperScale;
  perimeter /= kClipperScale;
  if (area <= 0.0) return false;
  return (max_area > 0.0 && area <= max_area) ||
         (max_width > 0.0 && perimeter > 0.0 &&
          area / (0.5 * perimeter) <= max_width);
}

std::vector<PolygonParts> TreePolygons(const CanonicalNode& tree) {
  std::vector<PolygonParts> polygons;
  std::vector<const CanonicalNode*> pending{&tree};
  while (!pending.empty()) {
    const auto* node = pending.back();
    pending.pop_back();
    for (const auto& child : node->children) pending.push_back(child.get());
    if (node->is_hole || node->path.empty()) continue;
    PolygonParts polygon{&node->path, {}};
    for (const auto& hole : node->children) polygon.interiors.push_back(&hole->path);
    polygons.push_back(std::move(polygon));
  }
  return polygons;
}

CanonicalPath OrientedPath(const CanonicalPath& path, bool positive) {
  CanonicalPath oriented = path;
  if ((SignedArea(path) > 0) != positive) std::reverse(oriented.begin(), oriented.end());
  return oriented;
}

std::vector<PolygonParts> EmptyComponents(
    const CanonicalNode& tree, std::vector<std::unique_ptr<CanonicalNode>>& domains) {
  std::vector<PolygonParts> components;
  std::vector<const CanonicalNode*> pending{&tree};
  while (!pending.empty()) {
    const auto* node = pending.back();
    pending.pop_back();
    for (const auto& child : node->children) pending.push_back(child.get());
    if (!node->is_hole) continue;
    if (node->children.empty()) {
      components.push_back({&node->path, {}});
      continue;
    }
    std::vector<CanonicalPath> paths{OrientedPath(node->path, true)};
    for (const auto& island : node->children) paths.push_back(OrientedPath(island->path, false));
    auto domain = std::make_unique<CanonicalNode>();
    BuildRingTree(TraceBoundaryFaces(paths), *domain);
    const auto polygons = TreePolygons(*domain);
    components.insert(components.end(), polygons.begin(), polygons.end());
    domains.push_back(std::move(domain));
  }
  return components;
}

std::vector<PolygonParts> SelectAndFill(
    const CanonicalNode& tree, const std::vector<PolygonParts>& voids,
    double max_area, double max_width, CanonicalNode& filled) {
  std::vector<PolygonParts> selected;
  std::vector<CanonicalPath> remaining;
  for (const auto& shell : tree.children) remaining.push_back(shell->path);
  for (const auto& component : voids) {
    if (SelectHole(component, max_area, max_width)) {
      selected.push_back(component);
    } else {
      remaining.push_back(OrientedPath(*component.shell, false));
      for (const auto* island : component.interiors) {
        remaining.push_back(OrientedPath(*island, true));
      }
    }
  }
  BuildRingTree(TraceBoundaryFaces(remaining), filled);
  return selected;
}

py::array_t<double> RingArray(const CanonicalPath& path, bool positive) {
  const auto count = static_cast<py::ssize_t>(path.size());
  py::array_t<double> coordinates({count, py::ssize_t{2}});
  auto values = coordinates.mutable_unchecked<2>();
  const bool reverse = (SignedArea(path) > 0.0) != positive;
  for (py::ssize_t index = 0; index < count; ++index) {
    const auto& point = path[static_cast<std::size_t>(reverse ? count - 1 - index : index)];
    values(index, 0) = static_cast<double>(point.x / kClipperScale);
    values(index, 1) = static_cast<double>(point.y / kClipperScale);
  }
  return coordinates;
}

py::list ExportPolygons(const std::vector<PolygonParts>& polygons) {
  py::list result;
  for (const auto& polygon : polygons) {
    py::list interiors;
    for (const auto* interior : polygon.interiors) {
      interiors.append(RingArray(*interior, false));
    }
    result.append(py::make_tuple(RingArray(*polygon.shell, true), interiors));
  }
  return result;
}

py::tuple FindHolesMm(const py::iterable& rings, double max_area, double max_width) {
  ValidateThreshold(max_area, "max_hole_area_mm2");
  ValidateThreshold(max_width, "max_hole_width_mm");
  const auto paths = ReadRings(rings);
  clipper::PolyTree64 union_tree;
  CanonicalNode tree;
  CanonicalNode filled;
  std::vector<std::unique_ptr<CanonicalNode>> void_domains;
  std::vector<PolygonParts> holes;
  std::vector<PolygonParts> coverage;
  {
    py::gil_scoped_release release;
    clipper::Clipper64 engine;
    engine.AddSubject(paths);
    if (!engine.Execute(clipper::ClipType::Union, clipper::FillRule::NonZero, union_tree)) {
      throw std::runtime_error("SVG compensation coverage union failed");
    }
    NormalizeTouchingRings(union_tree, tree);
    const auto voids = EmptyComponents(tree, void_domains);
    holes = SelectAndFill(tree, voids, max_area, max_width, filled);
    coverage = TreePolygons(filled);
  }
  return py::make_tuple(ExportPolygons(holes), ExportPolygons(coverage));
}

}  // namespace

PYBIND11_MODULE(_lumina_svg_compensation, module) {
  module.doc() = "Optional physical-mm SVG hole compensation / 可选 SVG 毫米孔洞补偿";
  module.def(
      "find_holes_mm", &FindHolesMm, py::arg("rings"),
      py::arg("max_hole_area_mm2"), py::arg("max_hole_width_mm"),
      R"doc(Find enclosed holes and filled coverage in physical millimetres.
识别物理毫米坐标中的封闭孔洞，并返回补偿后的覆盖区域。

Args:
    rings: Float64 Nx2 rings, shells CCW and holes CW.
        float64 Nx2 环坐标，外环逆时针，孔环顺时针。
    max_hole_area_mm2: Nonnegative hole area threshold; zero disables it.
        非负孔洞面积阈值，零表示关闭面积判断。
    max_hole_width_mm: Nonnegative 2*area/perimeter threshold; zero disables it.
        非负 2*面积/周长阈值，零表示关闭宽度判断。

Returns:
    (holes, filled_coverage), each a list of (shell, interiors) owning arrays.
    (孔洞, 补偿后覆盖区域)，两者均为拥有内存的 (外环, 内环列表) 列表。

Raises:
    ValueError: A setting or coordinate cannot be represented.
        参数或坐标无效或超出表示范围。
)doc");
}
