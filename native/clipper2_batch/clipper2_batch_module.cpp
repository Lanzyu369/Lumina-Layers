#define PY_SSIZE_T_CLEAN
#include <Python.h>
#define NPY_NO_DEPRECATED_API NPY_1_7_API_VERSION
#include <numpy/arrayobject.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "clipper2/clipper.h"

namespace {

using Clipper2Lib::Clipper64;
using Clipper2Lib::ClipperOffset;
using Clipper2Lib::ClipType;
using Clipper2Lib::EndType;
using Clipper2Lib::FillRule;
using Clipper2Lib::JoinType;
using Clipper2Lib::Path64;
using Clipper2Lib::Paths64;
using Clipper2Lib::Point64;
using Clipper2Lib::PolyPath64;
using Clipper2Lib::PolyTree64;
using Clipper2Lib::Triangulate;
using Clipper2Lib::TriangulateResult;

struct PolyWithHoles {
  std::vector<Path64> rings;
};

using GroupInput = Paths64;
using GroupOutput = std::vector<PolyWithHoles>;

constexpr long double kTriangulationAreaRelTol = 1e-4L;
constexpr long double kTriangulationAreaAbsTol = 4.0L;

struct Vertex3 {
  double x;
  double y;
  double z;
};

struct Face3 {
  int64_t a;
  int64_t b;
  int64_t c;
};

struct MeshOutput {
  std::vector<Vertex3> vertices;
  std::vector<Face3> faces;
};

constexpr uint8_t kRetryMeshAccepted = 0;
constexpr uint8_t kRetryMeshSurfaceReject = 1;
constexpr uint8_t kRetryMeshEmpty = 2;

struct RejectedMeshRetryOutput {
  std::vector<MeshOutput> meshes;
  MeshOutput coalesced_mesh;
  std::vector<uint8_t> statuses;
  std::vector<GroupOutput> fallback_groups;
  size_t path_count = 0;
  bool meshes_coalesced = false;
};

struct PointKey {
  int64_t x;
  int64_t y;

  bool operator==(const PointKey& other) const {
    return x == other.x && y == other.y;
  }
};

struct PointKeyHash {
  size_t operator()(const PointKey& key) const {
    const uint64_t x = static_cast<uint64_t>(key.x);
    const uint64_t y = static_cast<uint64_t>(key.y);
    return static_cast<size_t>(x ^ (y + 0x9e3779b97f4a7c15ULL + (x << 6U) + (x >> 2U)));
  }
};

struct EdgeKey {
  int64_t a;
  int64_t b;

  bool operator==(const EdgeKey& other) const {
    return a == other.a && b == other.b;
  }
};

struct EdgeKeyHash {
  size_t operator()(const EdgeKey& key) const {
    const uint64_t a = static_cast<uint64_t>(key.a);
    const uint64_t b = static_cast<uint64_t>(key.b);
    return static_cast<size_t>(
        a ^ (b + 0x9e3779b97f4a7c15ULL + (a << 6U) + (a >> 2U)));
  }
};

bool HasClosedIndexedEdgeTopology(const MeshOutput& mesh) {
  if (mesh.vertices.empty() || mesh.faces.empty()) {
    return false;
  }
  std::unordered_map<EdgeKey, uint8_t, EdgeKeyHash> incidence;
  incidence.reserve(mesh.faces.size() * 3U);
  for (const Face3& face : mesh.faces) {
    const int64_t indices[3] = {face.a, face.b, face.c};
    for (size_t index = 0; index < 3U; ++index) {
      const int64_t left = indices[index];
      const int64_t right = indices[(index + 1U) % 3U];
      if (left < 0 || right < 0 || left == right ||
          left >= static_cast<int64_t>(mesh.vertices.size()) ||
          right >= static_cast<int64_t>(mesh.vertices.size())) {
        return false;
      }
      const EdgeKey key{std::min(left, right), std::max(left, right)};
      uint8_t& count = incidence[key];
      if (count >= 2U) {
        return false;
      }
      ++count;
    }
  }
  return std::all_of(
      incidence.begin(), incidence.end(),
      [](const auto& entry) { return entry.second == 2U; });
}

void AppendIndependentMesh(MeshOutput& destination, MeshOutput&& source) {
  if (source.vertices.empty() || source.faces.empty()) {
    return;
  }
  const int64_t vertex_offset = static_cast<int64_t>(destination.vertices.size());
  destination.vertices.insert(
      destination.vertices.end(),
      std::make_move_iterator(source.vertices.begin()),
      std::make_move_iterator(source.vertices.end()));
  destination.faces.reserve(destination.faces.size() + source.faces.size());
  for (const Face3& face : source.faces) {
    destination.faces.push_back(Face3{
        face.a + vertex_offset,
        face.b + vertex_offset,
        face.c + vertex_offset});
  }
}

[[noreturn]] void ThrowTypeError(const std::string& message) {
  throw std::runtime_error(message);
}

PyObject* SequenceFast(PyObject* obj, const char* label) {
  PyObject* seq = PySequence_Fast(obj, label);
  if (!seq) {
    ThrowTypeError(label);
  }
  return seq;
}

int64_t ScaleCoord(double value, int64_t scale) {
  if (!std::isfinite(value)) {
    ThrowTypeError("coordinate must be finite");
  }
  const long double scaled = static_cast<long double>(value) * scale;
  if (scaled < static_cast<long double>(std::numeric_limits<int64_t>::min()) ||
      scaled > static_cast<long double>(std::numeric_limits<int64_t>::max())) {
    ThrowTypeError("scaled coordinate overflow");
  }
  return static_cast<int64_t>(std::llround(scaled));
}

Path64 ParsePath(PyObject* path_obj, int64_t scale) {
  PyObject* path_seq = SequenceFast(path_obj, "path must be a sequence");
  const Py_ssize_t point_count = PySequence_Fast_GET_SIZE(path_seq);
  Path64 path;
  path.reserve(static_cast<size_t>(point_count));
  Point64 previous{std::numeric_limits<int64_t>::max(), std::numeric_limits<int64_t>::max()};

  for (Py_ssize_t i = 0; i < point_count; ++i) {
    PyObject* point_obj = PySequence_Fast_GET_ITEM(path_seq, i);
    PyObject* point_seq = SequenceFast(point_obj, "point must be a sequence");
    if (PySequence_Fast_GET_SIZE(point_seq) < 2) {
      Py_DECREF(point_seq);
      Py_DECREF(path_seq);
      ThrowTypeError("point must contain x and y");
    }
    const double x = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(point_seq, 0));
    const double y = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(point_seq, 1));
    Py_DECREF(point_seq);
    if (PyErr_Occurred()) {
      Py_DECREF(path_seq);
      ThrowTypeError("point coordinates must be numeric");
    }
    Point64 point{ScaleCoord(x, scale), ScaleCoord(y, scale)};
    if (path.empty() || point.x != previous.x || point.y != previous.y) {
      path.push_back(point);
      previous = point;
    }
  }
  Py_DECREF(path_seq);
  if (path.size() > 1 && path.front().x == path.back().x && path.front().y == path.back().y) {
    path.pop_back();
  }
  if (path.size() < 3) {
    return {};
  }
  return path;
}

long double SignedArea(const Path64& path) {
  const size_t n = path.size();
  if (n < 3) {
    return 0.0L;
  }
  long double sum = 0.0L;
  for (size_t i = 0; i < n; ++i) {
    const Point64& p0 = path[i];
    const Point64& p1 = path[(i + 1U) % n];
    sum += static_cast<long double>(p0.x) * static_cast<long double>(p1.y) -
           static_cast<long double>(p1.x) * static_cast<long double>(p0.y);
  }
  return sum / 2.0L;
}

long double FilledArea(const Paths64& paths) {
  long double signed_sum = 0.0L;
  for (const Path64& path : paths) {
    signed_sum += SignedArea(path);
  }
  return std::fabs(signed_sum);
}

long double TriangleAreaSum(const Paths64& triangles) {
  long double total = 0.0L;
  for (const Path64& triangle : triangles) {
    total += std::fabs(SignedArea(triangle));
  }
  return total;
}

bool TriangulatedAreaMatches(const Paths64& paths, const Paths64& triangles) {
  const long double expected_area = FilledArea(paths);
  const long double triangle_area = TriangleAreaSum(triangles);
  const long double delta = std::fabs(triangle_area - expected_area);
  const long double tolerance =
      std::max(kTriangulationAreaAbsTol, expected_area * kTriangulationAreaRelTol);
  return delta <= tolerance;
}

GroupInput ParseGroup(PyObject* group_obj, int64_t scale) {
  PyObject* group_seq = SequenceFast(group_obj, "group must be a sequence");
  const Py_ssize_t path_count = PySequence_Fast_GET_SIZE(group_seq);
  GroupInput paths;
  paths.reserve(static_cast<size_t>(path_count));
  for (Py_ssize_t i = 0; i < path_count; ++i) {
    Path64 path = ParsePath(PySequence_Fast_GET_ITEM(group_seq, i), scale);
    if (path.size() >= 3) {
      paths.push_back(std::move(path));
    }
  }
  Py_DECREF(group_seq);
  return paths;
}

std::vector<GroupInput> ParseGroups(PyObject* groups_obj, int64_t scale) {
  PyObject* groups_seq = SequenceFast(groups_obj, "groups must be a sequence");
  const Py_ssize_t group_count = PySequence_Fast_GET_SIZE(groups_seq);
  std::vector<GroupInput> groups;
  groups.reserve(static_cast<size_t>(group_count));
  for (Py_ssize_t i = 0; i < group_count; ++i) {
    groups.push_back(ParseGroup(PySequence_Fast_GET_ITEM(groups_seq, i), scale));
  }
  Py_DECREF(groups_seq);
  return groups;
}

void UnionToTree(const Paths64& paths, PolyTree64& tree) {
  if (paths.empty()) {
    return;
  }
  Clipper64 clipper;
  clipper.AddSubject(paths);
  clipper.Execute(ClipType::Union, FillRule::NonZero, tree);
}

void OffsetToTree(const Paths64& paths, int64_t delta, PolyTree64& tree) {
  if (paths.empty()) {
    return;
  }
  ClipperOffset offset(2.0);
  offset.AddPaths(paths, JoinType::Miter, EndType::Polygon);
  offset.Execute(static_cast<double>(delta), tree);
}

void CollectPolygons(const PolyPath64& node, GroupOutput& output) {
  if (!node.Polygon().empty() && !node.IsHole()) {
    PolyWithHoles poly;
    poly.rings.push_back(node.Polygon());
    std::vector<const PolyPath64*> islands;
    for (const auto& child_ptr : node) {
      const PolyPath64& child = *child_ptr;
      if (child.IsHole()) {
        if (!child.Polygon().empty()) {
          poly.rings.push_back(child.Polygon());
        }
        for (const auto& grandchild_ptr : child) {
          islands.push_back(grandchild_ptr.get());
        }
      } else {
        islands.push_back(&child);
      }
    }
    if (!poly.rings.empty()) {
      output.push_back(std::move(poly));
    }
    for (const PolyPath64* island : islands) {
      CollectPolygons(*island, output);
    }
    return;
  }

  for (const auto& child_ptr : node) {
    CollectPolygons(*child_ptr, output);
  }
}

GroupOutput ProcessGroup(const GroupInput& paths, int64_t close_delta) {
  GroupOutput output;
  if (paths.empty()) {
    return output;
  }

  PolyTree64 tree;
  UnionToTree(paths, tree);
  if (close_delta > 0) {
    Paths64 union_paths = Clipper2Lib::PolyTreeToPaths64(tree);
    PolyTree64 inflated;
    OffsetToTree(union_paths, close_delta, inflated);
    Paths64 inflated_paths = Clipper2Lib::PolyTreeToPaths64(inflated);
    PolyTree64 deflated;
    OffsetToTree(inflated_paths, -close_delta, deflated);
    if (deflated.Count() > 0) {
      CollectPolygons(deflated, output);
      return output;
    }
  }
  CollectPolygons(tree, output);
  return output;
}

GroupOutput DifferenceGroup(const GroupInput& subjects, const GroupInput& clips) {
  GroupOutput output;
  if (subjects.empty()) {
    return output;
  }

  if (clips.empty()) {
    PolyTree64 tree;
    UnionToTree(subjects, tree);
    CollectPolygons(tree, output);
    return output;
  }

  PolyTree64 tree;
  Clipper64 clipper;
  clipper.AddSubject(subjects);
  clipper.AddClip(clips);
  clipper.Execute(ClipType::Difference, FillRule::NonZero, tree);
  CollectPolygons(tree, output);
  return output;
}

Paths64 ProcessGroupToPaths(const GroupInput& paths, int64_t close_delta) {
  if (paths.empty()) {
    return {};
  }

  PolyTree64 tree;
  UnionToTree(paths, tree);
  if (close_delta > 0) {
    Paths64 union_paths = Clipper2Lib::PolyTreeToPaths64(tree);
    PolyTree64 inflated;
    OffsetToTree(union_paths, close_delta, inflated);
    Paths64 inflated_paths = Clipper2Lib::PolyTreeToPaths64(inflated);
    PolyTree64 deflated;
    OffsetToTree(inflated_paths, -close_delta, deflated);
    if (deflated.Count() > 0) {
      return Clipper2Lib::PolyTreeToPaths64(deflated);
    }
  }
  return Clipper2Lib::PolyTreeToPaths64(tree);
}

int64_t AddVertex(
    MeshOutput& mesh,
    std::unordered_map<PointKey, int64_t, PointKeyHash>& bottom_index,
    std::unordered_map<PointKey, int64_t, PointKeyHash>& top_index,
    const Point64& point,
    bool top,
    int64_t scale,
    double height,
    double z_offset,
    double xy_scale) {
  PointKey key{point.x, point.y};
  auto& index_map = top ? top_index : bottom_index;
  const auto found = index_map.find(key);
  if (found != index_map.end()) {
    return found->second;
  }
  const int64_t idx = static_cast<int64_t>(mesh.vertices.size());
  index_map.emplace(key, idx);
  mesh.vertices.push_back(Vertex3{
      (static_cast<double>(point.x) / scale) * xy_scale,
      (static_cast<double>(point.y) / scale) * xy_scale,
      z_offset + (top ? height : 0.0),
  });
  return idx;
}

bool AddTriangleFacesForPaths(
    MeshOutput& mesh,
    std::unordered_map<PointKey, int64_t, PointKeyHash>& bottom_index,
    std::unordered_map<PointKey, int64_t, PointKeyHash>& top_index,
    const Paths64& paths,
    int64_t scale,
    double height,
    double z_offset,
    double xy_scale) {
  Paths64 triangles;
  TriangulateResult tri_result = Triangulate(paths, triangles, false);
  if (tri_result != TriangulateResult::success || triangles.empty()) {
    return false;
  }
  if (!TriangulatedAreaMatches(paths, triangles)) {
    return false;
  }

  for (const Path64& tri : triangles) {
    if (tri.size() < 3) {
      continue;
    }
    const int64_t b0 = AddVertex(mesh, bottom_index, top_index, tri[0], false, scale, height, z_offset, xy_scale);
    const int64_t b1 = AddVertex(mesh, bottom_index, top_index, tri[1], false, scale, height, z_offset, xy_scale);
    const int64_t b2 = AddVertex(mesh, bottom_index, top_index, tri[2], false, scale, height, z_offset, xy_scale);
    const int64_t t0 = AddVertex(mesh, bottom_index, top_index, tri[0], true, scale, height, z_offset, xy_scale);
    const int64_t t1 = AddVertex(mesh, bottom_index, top_index, tri[1], true, scale, height, z_offset, xy_scale);
    const int64_t t2 = AddVertex(mesh, bottom_index, top_index, tri[2], true, scale, height, z_offset, xy_scale);

    mesh.faces.push_back(Face3{b0, b2, b1});
    mesh.faces.push_back(Face3{t0, t1, t2});
  }
  return true;
}

void AddSideFacesForPath(
    MeshOutput& mesh,
    std::unordered_map<PointKey, int64_t, PointKeyHash>& bottom_index,
    std::unordered_map<PointKey, int64_t, PointKeyHash>& top_index,
    const Path64& path,
    int64_t scale,
    double height,
    double z_offset,
    double xy_scale) {
  const size_t n = path.size();
  if (n < 3) {
    return;
  }
  for (size_t i = 0; i < n; ++i) {
    const Point64& p0 = path[i];
    const Point64& p1 = path[(i + 1U) % n];
    if (p0.x == p1.x && p0.y == p1.y) {
      continue;
    }
    const int64_t b0 = AddVertex(mesh, bottom_index, top_index, p0, false, scale, height, z_offset, xy_scale);
    const int64_t b1 = AddVertex(mesh, bottom_index, top_index, p1, false, scale, height, z_offset, xy_scale);
    const int64_t t0 = AddVertex(mesh, bottom_index, top_index, p0, true, scale, height, z_offset, xy_scale);
    const int64_t t1 = AddVertex(mesh, bottom_index, top_index, p1, true, scale, height, z_offset, xy_scale);
    mesh.faces.push_back(Face3{b0, b1, t1});
    mesh.faces.push_back(Face3{b0, t1, t0});
  }
}

MeshOutput ExtrudePathsToMesh(
    const Paths64& paths,
    int64_t scale,
    double height,
    double z_offset,
    double xy_scale) {
  MeshOutput mesh;
  if (paths.empty() || height <= 0.0 || xy_scale <= 0.0) {
    return mesh;
  }

  Paths64 triangles;
  TriangulateResult tri_result = Triangulate(paths, triangles, false);
  if (tri_result != TriangulateResult::success || triangles.empty()) {
    return mesh;
  }

  std::unordered_map<PointKey, int64_t, PointKeyHash> bottom_index;
  std::unordered_map<PointKey, int64_t, PointKeyHash> top_index;
  bottom_index.reserve(triangles.size() * 3U);
  top_index.reserve(triangles.size() * 3U);

  for (const Path64& tri : triangles) {
    if (tri.size() < 3) {
      continue;
    }
    const int64_t b0 = AddVertex(mesh, bottom_index, top_index, tri[0], false, scale, height, z_offset, xy_scale);
    const int64_t b1 = AddVertex(mesh, bottom_index, top_index, tri[1], false, scale, height, z_offset, xy_scale);
    const int64_t b2 = AddVertex(mesh, bottom_index, top_index, tri[2], false, scale, height, z_offset, xy_scale);
    const int64_t t0 = AddVertex(mesh, bottom_index, top_index, tri[0], true, scale, height, z_offset, xy_scale);
    const int64_t t1 = AddVertex(mesh, bottom_index, top_index, tri[1], true, scale, height, z_offset, xy_scale);
    const int64_t t2 = AddVertex(mesh, bottom_index, top_index, tri[2], true, scale, height, z_offset, xy_scale);

    mesh.faces.push_back(Face3{b0, b2, b1});
    mesh.faces.push_back(Face3{t0, t1, t2});
  }

  for (const Path64& path : paths) {
    const size_t n = path.size();
    if (n < 3) {
      continue;
    }
    for (size_t i = 0; i < n; ++i) {
      const Point64& p0 = path[i];
      const Point64& p1 = path[(i + 1U) % n];
      if (p0.x == p1.x && p0.y == p1.y) {
        continue;
      }
      const int64_t b0 = AddVertex(mesh, bottom_index, top_index, p0, false, scale, height, z_offset, xy_scale);
      const int64_t b1 = AddVertex(mesh, bottom_index, top_index, p1, false, scale, height, z_offset, xy_scale);
      const int64_t t0 = AddVertex(mesh, bottom_index, top_index, p0, true, scale, height, z_offset, xy_scale);
      const int64_t t1 = AddVertex(mesh, bottom_index, top_index, p1, true, scale, height, z_offset, xy_scale);
      mesh.faces.push_back(Face3{b0, b1, t1});
      mesh.faces.push_back(Face3{b0, t1, t0});
    }
  }

  return mesh;
}

MeshOutput ExtrudePolygonsToMesh(
    const GroupOutput& polygons,
    int64_t scale,
    double height,
    double z_offset,
    double xy_scale) {
  MeshOutput mesh;
  if (polygons.empty() || height <= 0.0 || xy_scale <= 0.0) {
    return mesh;
  }

  for (const PolyWithHoles& poly : polygons) {
    if (poly.rings.empty()) {
      continue;
    }
    size_t point_count = 0;
    for (const Path64& ring : poly.rings) {
      point_count += ring.size();
    }
    // Keep coincident vertices in different polygon shells independently
    // indexed. Sharing this map across polygons welds point contacts while
    // retaining both shells' sidewalls, creating 4/6/8-face indexed edges.
    std::unordered_map<PointKey, int64_t, PointKeyHash> bottom_index;
    std::unordered_map<PointKey, int64_t, PointKeyHash> top_index;
    bottom_index.reserve(point_count);
    top_index.reserve(point_count);
    if (!AddTriangleFacesForPaths(
            mesh, bottom_index, top_index, poly.rings, scale, height, z_offset, xy_scale)) {
      return MeshOutput{};
    }
    for (const Path64& ring : poly.rings) {
      AddSideFacesForPath(mesh, bottom_index, top_index, ring, scale, height, z_offset, xy_scale);
    }
  }

  return HasClosedIndexedEdgeTopology(mesh) ? std::move(mesh) : MeshOutput{};
}

double MeshSurfaceArea(const MeshOutput& mesh) {
  double total = 0.0;
  for (const Face3& face : mesh.faces) {
    const Vertex3& a = mesh.vertices[static_cast<size_t>(face.a)];
    const Vertex3& b = mesh.vertices[static_cast<size_t>(face.b)];
    const Vertex3& c = mesh.vertices[static_cast<size_t>(face.c)];
    const double ab_x = b.x - a.x;
    const double ab_y = b.y - a.y;
    const double ab_z = b.z - a.z;
    const double ac_x = c.x - a.x;
    const double ac_y = c.y - a.y;
    const double ac_z = c.z - a.z;
    const double cross_x = ab_y * ac_z - ab_z * ac_y;
    const double cross_y = ab_z * ac_x - ab_x * ac_z;
    const double cross_z = ab_x * ac_y - ab_y * ac_x;
    total += std::sqrt(
                 cross_x * cross_x + cross_y * cross_y + cross_z * cross_z) /
             2.0;
  }
  return total;
}

double RetryExpectedSurfaceArea(
    const PolyWithHoles& polygon,
    int64_t scale,
    double height,
    double xy_scale) {
  if (polygon.rings.empty()) {
    return 0.0;
  }
  long double area_units = std::fabs(SignedArea(polygon.rings.front()));
  long double perimeter_units = 0.0L;
  for (size_t ring_index = 0; ring_index < polygon.rings.size(); ++ring_index) {
    const Path64& ring = polygon.rings[ring_index];
    if (ring_index > 0) {
      area_units -= std::fabs(SignedArea(ring));
    }
    for (size_t point_index = 0; point_index < ring.size(); ++point_index) {
      const Point64& p0 = ring[point_index];
      const Point64& p1 = ring[(point_index + 1U) % ring.size()];
      const long double dx = static_cast<long double>(p1.x) - p0.x;
      const long double dy = static_cast<long double>(p1.y) - p0.y;
      perimeter_units += std::sqrt(dx * dx + dy * dy);
    }
  }
  const long double unit_scale =
      static_cast<long double>(xy_scale) / static_cast<long double>(scale);
  const long double area_mm2 = std::max(0.0L, area_units) * unit_scale * unit_scale;
  const long double perimeter_mm = perimeter_units * unit_scale;
  return static_cast<double>(
      2.0L * area_mm2 + perimeter_mm * static_cast<long double>(height));
}

bool RetrySurfaceAreaMatches(
    const MeshOutput& mesh,
    const PolyWithHoles& polygon,
    int64_t scale,
    double height,
    double xy_scale,
    double relative_tolerance,
    double absolute_tolerance) {
  const double expected = RetryExpectedSurfaceArea(
      polygon, scale, height, xy_scale);
  if (expected <= absolute_tolerance) {
    return true;
  }
  const double delta = std::fabs(MeshSurfaceArea(mesh) - expected);
  if (delta <= absolute_tolerance) {
    return true;
  }
  return delta / expected <= relative_tolerance;
}

double GroupExpectedSurfaceArea(
    const GroupOutput& polygons,
    int64_t scale,
    double height,
    double xy_scale) {
  double total = 0.0;
  for (const PolyWithHoles& polygon : polygons) {
    total += RetryExpectedSurfaceArea(polygon, scale, height, xy_scale);
  }
  return total;
}

bool GroupSurfaceAreaMatches(
    const MeshOutput& mesh,
    const GroupOutput& polygons,
    int64_t scale,
    double height,
    double xy_scale,
    double relative_tolerance,
    double absolute_tolerance) {
  const double expected = GroupExpectedSurfaceArea(
      polygons, scale, height, xy_scale);
  if (expected <= absolute_tolerance) {
    return true;
  }
  const double delta = std::fabs(MeshSurfaceArea(mesh) - expected);
  if (delta <= absolute_tolerance) {
    return true;
  }
  return delta / expected <= relative_tolerance;
}

RejectedMeshRetryOutput RetryRejectedPolygonsToMeshes(
    const GroupOutput& polygons,
    int64_t scale,
    double height,
    double z_offset,
    double xy_scale,
    bool coalesce_meshes,
    bool validate_surfaces,
    double relative_tolerance,
    double absolute_tolerance) {
  RejectedMeshRetryOutput output;
  output.meshes_coalesced = coalesce_meshes;
  if (!coalesce_meshes) {
    output.meshes.reserve(polygons.size());
  }
  output.statuses.reserve(polygons.size());
  output.fallback_groups.resize(polygons.size());
  for (size_t index = 0; index < polygons.size(); ++index) {
    const PolyWithHoles& polygon = polygons[index];
    GroupInput retry_input = polygon.rings;
    output.path_count += retry_input.size();
    GroupOutput retry_polygons = ProcessGroup(retry_input, 0);
    MeshOutput retry_mesh = ExtrudePolygonsToMesh(
        retry_polygons, scale, height, z_offset, xy_scale);
    uint8_t status = kRetryMeshAccepted;
    if (retry_mesh.vertices.empty() || retry_mesh.faces.empty()) {
      status = kRetryMeshEmpty;
    } else if (validate_surfaces) {
      if (!RetrySurfaceAreaMatches(
              retry_mesh,
              polygon,
              scale,
              height,
              xy_scale,
              relative_tolerance,
              absolute_tolerance)) {
        retry_mesh = MeshOutput{};
        status = kRetryMeshSurfaceReject;
      }
    }
    if (status != kRetryMeshAccepted) {
      output.fallback_groups[index].push_back(polygon);
    }
    if (coalesce_meshes) {
      if (status == kRetryMeshAccepted) {
        AppendIndependentMesh(output.coalesced_mesh, std::move(retry_mesh));
      }
    } else {
      output.meshes.push_back(std::move(retry_mesh));
    }
    output.statuses.push_back(status);
  }
  return output;
}

PyObject* BuildPoint(const Point64& point, int64_t scale) {
  return Py_BuildValue("(dd)", static_cast<double>(point.x) / scale,
                       static_cast<double>(point.y) / scale);
}

PyObject* BuildPath(const Path64& path, int64_t scale) {
  PyObject* py_path = PyList_New(static_cast<Py_ssize_t>(path.size()));
  if (!py_path) {
    return nullptr;
  }
  for (Py_ssize_t i = 0; i < static_cast<Py_ssize_t>(path.size()); ++i) {
    PyObject* py_point = BuildPoint(path[static_cast<size_t>(i)], scale);
    if (!py_point) {
      Py_DECREF(py_path);
      return nullptr;
    }
    PyList_SET_ITEM(py_path, i, py_point);
  }
  return py_path;
}

PyObject* BuildGroup(const GroupOutput& group, int64_t scale) {
  PyObject* py_group = PyList_New(static_cast<Py_ssize_t>(group.size()));
  if (!py_group) {
    return nullptr;
  }
  for (Py_ssize_t i = 0; i < static_cast<Py_ssize_t>(group.size()); ++i) {
    const PolyWithHoles& poly = group[static_cast<size_t>(i)];
    PyObject* py_poly = PyList_New(static_cast<Py_ssize_t>(poly.rings.size()));
    if (!py_poly) {
      Py_DECREF(py_group);
      return nullptr;
    }
    for (Py_ssize_t j = 0; j < static_cast<Py_ssize_t>(poly.rings.size()); ++j) {
      PyObject* py_path = BuildPath(poly.rings[static_cast<size_t>(j)], scale);
      if (!py_path) {
        Py_DECREF(py_poly);
        Py_DECREF(py_group);
        return nullptr;
      }
      PyList_SET_ITEM(py_poly, j, py_path);
    }
    PyList_SET_ITEM(py_group, i, py_poly);
  }
  return py_group;
}

PyObject* BuildMesh(const MeshOutput& mesh) {
  npy_intp vertex_dims[2] = {static_cast<npy_intp>(mesh.vertices.size()), 3};
  PyObject* py_vertices = PyArray_SimpleNew(2, vertex_dims, NPY_DOUBLE);
  if (!py_vertices) {
    return nullptr;
  }
  double* vertex_data =
      static_cast<double*>(PyArray_DATA(reinterpret_cast<PyArrayObject*>(py_vertices)));
  for (size_t i = 0; i < mesh.vertices.size(); ++i) {
    const Vertex3& vertex = mesh.vertices[i];
    const size_t offset = i * 3U;
    vertex_data[offset] = vertex.x;
    vertex_data[offset + 1U] = vertex.y;
    vertex_data[offset + 2U] = vertex.z;
  }

  npy_intp face_dims[2] = {static_cast<npy_intp>(mesh.faces.size()), 3};
  PyObject* py_faces = PyArray_SimpleNew(2, face_dims, NPY_INT64);
  if (!py_faces) {
    Py_DECREF(py_vertices);
    return nullptr;
  }
  auto* face_data =
      static_cast<int64_t*>(PyArray_DATA(reinterpret_cast<PyArrayObject*>(py_faces)));
  for (size_t i = 0; i < mesh.faces.size(); ++i) {
    const Face3& face = mesh.faces[i];
    const size_t offset = i * 3U;
    face_data[offset] = face.a;
    face_data[offset + 1U] = face.b;
    face_data[offset + 2U] = face.c;
  }

  PyObject* tuple = PyTuple_New(2);
  if (!tuple) {
    Py_DECREF(py_faces);
    Py_DECREF(py_vertices);
    return nullptr;
  }
  PyTuple_SET_ITEM(tuple, 0, py_vertices);
  PyTuple_SET_ITEM(tuple, 1, py_faces);
  return tuple;
}

PyObject* BuildRejectedMeshRetryRecords(
    const std::vector<RejectedMeshRetryOutput>& retry_outputs,
    int64_t scale) {
  PyObject* records = PyList_New(
      static_cast<Py_ssize_t>(retry_outputs.size()));
  if (!records) {
    return nullptr;
  }
  for (Py_ssize_t index = 0;
       index < static_cast<Py_ssize_t>(retry_outputs.size()); ++index) {
    const RejectedMeshRetryOutput& retry =
        retry_outputs[static_cast<size_t>(index)];
    if (retry.statuses.empty()) {
      Py_INCREF(Py_None);
      PyList_SET_ITEM(records, index, Py_None);
      continue;
    }

    PyObject* meshes = nullptr;
    if (retry.meshes_coalesced) {
      meshes = BuildMesh(retry.coalesced_mesh);
      if (!meshes) {
        Py_DECREF(records);
        return nullptr;
      }
    } else {
      meshes = PyList_New(static_cast<Py_ssize_t>(retry.meshes.size()));
      if (!meshes) {
        Py_DECREF(records);
        return nullptr;
      }
      for (Py_ssize_t mesh_index = 0;
           mesh_index < static_cast<Py_ssize_t>(retry.meshes.size());
           ++mesh_index) {
        PyObject* mesh = BuildMesh(
            retry.meshes[static_cast<size_t>(mesh_index)]);
        if (!mesh) {
          Py_DECREF(meshes);
          Py_DECREF(records);
          return nullptr;
        }
        PyList_SET_ITEM(meshes, mesh_index, mesh);
      }
    }

    npy_intp status_dims[1] = {
        static_cast<npy_intp>(retry.statuses.size())};
    PyObject* statuses = PyArray_SimpleNew(1, status_dims, NPY_UINT8);
    if (!statuses) {
      Py_DECREF(meshes);
      Py_DECREF(records);
      return nullptr;
    }
    auto* status_data = static_cast<uint8_t*>(
        PyArray_DATA(reinterpret_cast<PyArrayObject*>(statuses)));
    std::copy(retry.statuses.begin(), retry.statuses.end(), status_data);

    PyObject* fallbacks = PyDict_New();
    if (!fallbacks) {
      Py_DECREF(statuses);
      Py_DECREF(meshes);
      Py_DECREF(records);
      return nullptr;
    }
    for (size_t fallback_index = 0;
         fallback_index < retry.fallback_groups.size(); ++fallback_index) {
      const GroupOutput& fallback = retry.fallback_groups[fallback_index];
      if (fallback.empty()) {
        continue;
      }
      PyObject* key = PyLong_FromSize_t(fallback_index);
      PyObject* group = BuildGroup(fallback, scale);
      if (!key || !group) {
        Py_XDECREF(group);
        Py_XDECREF(key);
        Py_DECREF(fallbacks);
        Py_DECREF(statuses);
        Py_DECREF(meshes);
        Py_DECREF(records);
        return nullptr;
      }
      if (PyDict_SetItem(fallbacks, key, group) < 0) {
        Py_DECREF(group);
        Py_DECREF(key);
        Py_DECREF(fallbacks);
        Py_DECREF(statuses);
        Py_DECREF(meshes);
        Py_DECREF(records);
        return nullptr;
      }
      Py_DECREF(group);
      Py_DECREF(key);
    }

    PyObject* path_count = PyLong_FromSize_t(retry.path_count);
    PyObject* record = PyTuple_New(retry.meshes_coalesced ? 5 : 4);
    if (!path_count || !record) {
      Py_XDECREF(record);
      Py_XDECREF(path_count);
      Py_DECREF(fallbacks);
      Py_DECREF(statuses);
      Py_DECREF(meshes);
      Py_DECREF(records);
      return nullptr;
    }
    PyTuple_SET_ITEM(record, 0, meshes);
    PyTuple_SET_ITEM(record, 1, statuses);
    PyTuple_SET_ITEM(record, 2, fallbacks);
    PyTuple_SET_ITEM(record, 3, path_count);
    if (retry.meshes_coalesced) {
      PyObject* coalesced = PyBool_FromLong(1);
      if (!coalesced) {
        Py_DECREF(record);
        Py_DECREF(records);
        return nullptr;
      }
      PyTuple_SET_ITEM(record, 4, coalesced);
    }
    PyList_SET_ITEM(records, index, record);
  }
  return records;
}

PyObject* NativeMeshCapabilities(PyObject*, PyObject*) {
  PyObject* result = PyDict_New();
  if (!result) {
    return nullptr;
  }
  PyObject* area_guard = PyBool_FromLong(1);
  if (!area_guard) {
    Py_DECREF(result);
    return nullptr;
  }
  PyDict_SetItemString(result, "triangulation_area_guard", area_guard);
  Py_DECREF(area_guard);
  PyObject* rejected_group_reuse = PyBool_FromLong(1);
  if (!rejected_group_reuse) {
    Py_DECREF(result);
    return nullptr;
  }
  PyDict_SetItemString(result, "rejected_group_reuse", rejected_group_reuse);
  Py_DECREF(rejected_group_reuse);
  PyObject* rejected_mesh_retry = PyBool_FromLong(1);
  if (!rejected_mesh_retry) {
    Py_DECREF(result);
    return nullptr;
  }
  PyDict_SetItemString(result, "rejected_mesh_retry", rejected_mesh_retry);
  Py_DECREF(rejected_mesh_retry);
  PyObject* coalesced_rejected_mesh_retry = PyBool_FromLong(1);
  if (!coalesced_rejected_mesh_retry) {
    Py_DECREF(result);
    return nullptr;
  }
  PyDict_SetItemString(
      result,
      "coalesced_rejected_mesh_retry",
      coalesced_rejected_mesh_retry);
  Py_DECREF(coalesced_rejected_mesh_retry);
  PyObject* native_surface_validation = PyBool_FromLong(1);
  if (!native_surface_validation) {
    Py_DECREF(result);
    return nullptr;
  }
  PyDict_SetItemString(
      result, "native_surface_validation", native_surface_validation);
  Py_DECREF(native_surface_validation);
  PyObject* topology_guard = PyBool_FromLong(1);
  if (!topology_guard) {
    Py_DECREF(result);
    return nullptr;
  }
  PyDict_SetItemString(
      result, "indexed_edge_manifold_guard", topology_guard);
  Py_DECREF(topology_guard);
  return result;
}

PyObject* MergeRunGroups(PyObject*, PyObject* args, PyObject* kwargs) {
  PyObject* groups_obj = nullptr;
  double close_delta_mm = 0.03;
  long long scale_arg = 1000000;
  static const char* kwlist[] = {"groups", "close_delta_mm", "scale", nullptr};
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|dL",
                                   const_cast<char**>(kwlist),
                                   &groups_obj, &close_delta_mm, &scale_arg)) {
    return nullptr;
  }
  if (scale_arg <= 0) {
    PyErr_SetString(PyExc_ValueError, "scale must be positive");
    return nullptr;
  }
  const int64_t scale = static_cast<int64_t>(scale_arg);
  const int64_t close_delta = close_delta_mm > 0.0
                                  ? static_cast<int64_t>(std::llround(close_delta_mm * scale))
                                  : 0;

  std::vector<GroupInput> groups;
  try {
    groups = ParseGroups(groups_obj, scale);
  } catch (const std::exception& exc) {
    if (!PyErr_Occurred()) {
      PyErr_SetString(PyExc_TypeError, exc.what());
    }
    return nullptr;
  }

  std::vector<GroupOutput> outputs(groups.size());
  Py_BEGIN_ALLOW_THREADS
  for (size_t i = 0; i < groups.size(); ++i) {
    outputs[i] = ProcessGroup(groups[i], close_delta);
  }
  Py_END_ALLOW_THREADS

  PyObject* result = PyList_New(static_cast<Py_ssize_t>(outputs.size()));
  if (!result) {
    return nullptr;
  }
  for (Py_ssize_t i = 0; i < static_cast<Py_ssize_t>(outputs.size()); ++i) {
    PyObject* py_group = BuildGroup(outputs[static_cast<size_t>(i)], scale);
    if (!py_group) {
      Py_DECREF(result);
      return nullptr;
    }
    PyList_SET_ITEM(result, i, py_group);
  }
  return result;
}

PyObject* MergeRunGroupsToMeshes(PyObject*, PyObject* args, PyObject* kwargs) {
  PyObject* groups_obj = nullptr;
  double close_delta_mm = 0.03;
  long long scale_arg = 1000000;
  double height = 1.0;
  double z_offset = 0.0;
  double xy_scale = 1.0;
  int return_rejected_groups = 0;
  int return_rejected_meshes = 0;
  int validate_retry_surfaces = 0;
  int validate_primary_surfaces = 0;
  int coalesce_retry_meshes = 0;
  double surface_rel_tol = 0.001;
  double surface_abs_tol = 0.01;
  static const char* kwlist[] = {
      "groups", "close_delta_mm", "scale", "height", "z_offset", "xy_scale",
      "return_rejected_groups", "return_rejected_meshes",
      "validate_retry_surfaces", "validate_primary_surfaces",
      "coalesce_retry_meshes",
      "surface_rel_tol", "surface_abs_tol", nullptr};
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|dLdddpppppdd",
                                   const_cast<char**>(kwlist),
                                   &groups_obj, &close_delta_mm, &scale_arg,
                                   &height, &z_offset, &xy_scale,
                                   &return_rejected_groups,
                                   &return_rejected_meshes,
                                   &validate_retry_surfaces,
                                   &validate_primary_surfaces,
                                   &coalesce_retry_meshes,
                                   &surface_rel_tol,
                                   &surface_abs_tol)) {
    return nullptr;
  }
  if (return_rejected_groups && return_rejected_meshes) {
    PyErr_SetString(
        PyExc_ValueError,
        "return_rejected_groups and return_rejected_meshes are mutually exclusive");
    return nullptr;
  }
  if (coalesce_retry_meshes && !return_rejected_meshes) {
    PyErr_SetString(
        PyExc_ValueError,
        "coalesce_retry_meshes requires return_rejected_meshes");
    return nullptr;
  }
  if (scale_arg <= 0) {
    PyErr_SetString(PyExc_ValueError, "scale must be positive");
    return nullptr;
  }
  if (height <= 0.0) {
    PyErr_SetString(PyExc_ValueError, "height must be positive");
    return nullptr;
  }
  if (xy_scale <= 0.0) {
    PyErr_SetString(PyExc_ValueError, "xy_scale must be positive");
    return nullptr;
  }
  const int64_t scale = static_cast<int64_t>(scale_arg);
  const int64_t close_delta = close_delta_mm > 0.0
                                  ? static_cast<int64_t>(std::llround(close_delta_mm * scale))
                                  : 0;

  std::vector<GroupInput> groups;
  try {
    groups = ParseGroups(groups_obj, scale);
  } catch (const std::exception& exc) {
    if (!PyErr_Occurred()) {
      PyErr_SetString(PyExc_TypeError, exc.what());
    }
    return nullptr;
  }

  std::vector<MeshOutput> outputs(groups.size());
  std::vector<GroupOutput> rejected_groups;
  if (return_rejected_groups) {
    rejected_groups.resize(groups.size());
  }
  std::vector<RejectedMeshRetryOutput> rejected_mesh_retries;
  std::vector<uint8_t> primary_statuses;
  if (return_rejected_meshes) {
    rejected_mesh_retries.resize(groups.size());
    primary_statuses.resize(groups.size(), kRetryMeshAccepted);
  }
  Py_BEGIN_ALLOW_THREADS
  for (size_t i = 0; i < groups.size(); ++i) {
    GroupOutput polygons = ProcessGroup(groups[i], close_delta);
    outputs[i] = ExtrudePolygonsToMesh(polygons, scale, height, z_offset, xy_scale);
    bool primary_empty =
        outputs[i].vertices.empty() || outputs[i].faces.empty();
    if (return_rejected_meshes && primary_empty) {
      primary_statuses[i] = kRetryMeshEmpty;
    } else if (return_rejected_meshes && validate_primary_surfaces &&
               !GroupSurfaceAreaMatches(
                   outputs[i],
                   polygons,
                   scale,
                   height,
                   xy_scale,
                   std::max(0.0, surface_rel_tol),
                   std::max(0.0, surface_abs_tol))) {
      outputs[i] = MeshOutput{};
      primary_statuses[i] = kRetryMeshSurfaceReject;
      primary_empty = true;
    }
    if (primary_empty) {
      if (return_rejected_meshes) {
        rejected_mesh_retries[i] = RetryRejectedPolygonsToMeshes(
            polygons,
            scale,
            height,
            z_offset,
            xy_scale,
            coalesce_retry_meshes != 0,
            validate_retry_surfaces != 0,
            std::max(0.0, surface_rel_tol),
            std::max(0.0, surface_abs_tol));
      } else if (return_rejected_groups) {
        rejected_groups[i] = std::move(polygons);
      }
    }
  }
  Py_END_ALLOW_THREADS

  PyObject* mesh_result = PyList_New(static_cast<Py_ssize_t>(outputs.size()));
  if (!mesh_result) {
    return nullptr;
  }
  for (Py_ssize_t i = 0; i < static_cast<Py_ssize_t>(outputs.size()); ++i) {
    PyObject* py_mesh = BuildMesh(outputs[static_cast<size_t>(i)]);
    if (!py_mesh) {
      Py_DECREF(mesh_result);
      return nullptr;
    }
    PyList_SET_ITEM(mesh_result, i, py_mesh);
  }
  if (return_rejected_meshes) {
    PyObject* retry_records = BuildRejectedMeshRetryRecords(
        rejected_mesh_retries, scale);
    if (!retry_records) {
      Py_DECREF(mesh_result);
      return nullptr;
    }
    npy_intp status_dims[1] = {
        static_cast<npy_intp>(primary_statuses.size())};
    PyObject* primary_status_result = PyArray_SimpleNew(
        1, status_dims, NPY_UINT8);
    if (!primary_status_result) {
      Py_DECREF(retry_records);
      Py_DECREF(mesh_result);
      return nullptr;
    }
    auto* primary_status_data = static_cast<uint8_t*>(
        PyArray_DATA(reinterpret_cast<PyArrayObject*>(primary_status_result)));
    std::copy(
        primary_statuses.begin(), primary_statuses.end(), primary_status_data);
    PyObject* result = PyTuple_New(3);
    if (!result) {
      Py_DECREF(primary_status_result);
      Py_DECREF(retry_records);
      Py_DECREF(mesh_result);
      return nullptr;
    }
    PyTuple_SET_ITEM(result, 0, mesh_result);
    PyTuple_SET_ITEM(result, 1, primary_status_result);
    PyTuple_SET_ITEM(result, 2, retry_records);
    return result;
  }
  if (!return_rejected_groups) {
    return mesh_result;
  }

  PyObject* rejected_result = PyList_New(
      static_cast<Py_ssize_t>(rejected_groups.size()));
  if (!rejected_result) {
    Py_DECREF(mesh_result);
    return nullptr;
  }
  for (Py_ssize_t i = 0;
       i < static_cast<Py_ssize_t>(rejected_groups.size()); ++i) {
    PyObject* py_group = BuildGroup(
        rejected_groups[static_cast<size_t>(i)], scale);
    if (!py_group) {
      Py_DECREF(rejected_result);
      Py_DECREF(mesh_result);
      return nullptr;
    }
    PyList_SET_ITEM(rejected_result, i, py_group);
  }

  PyObject* result = PyTuple_New(2);
  if (!result) {
    Py_DECREF(rejected_result);
    Py_DECREF(mesh_result);
    return nullptr;
  }
  PyTuple_SET_ITEM(result, 0, mesh_result);
  PyTuple_SET_ITEM(result, 1, rejected_result);
  return result;
}

PyObject* DifferencePaths(PyObject*, PyObject* args, PyObject* kwargs) {
  PyObject* subjects_obj = nullptr;
  PyObject* clips_obj = nullptr;
  long long scale_arg = 1000000;
  static const char* kwlist[] = {"subject_paths", "clip_paths", "scale", nullptr};
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "OO|L",
                                   const_cast<char**>(kwlist),
                                   &subjects_obj, &clips_obj, &scale_arg)) {
    return nullptr;
  }
  if (scale_arg <= 0) {
    PyErr_SetString(PyExc_ValueError, "scale must be positive");
    return nullptr;
  }
  const int64_t scale = static_cast<int64_t>(scale_arg);

  GroupInput subjects;
  GroupInput clips;
  try {
    subjects = ParseGroup(subjects_obj, scale);
    clips = ParseGroup(clips_obj, scale);
  } catch (const std::exception& exc) {
    if (!PyErr_Occurred()) {
      PyErr_SetString(PyExc_TypeError, exc.what());
    }
    return nullptr;
  }

  GroupOutput output;
  Py_BEGIN_ALLOW_THREADS
  output = DifferenceGroup(subjects, clips);
  Py_END_ALLOW_THREADS

  return BuildGroup(output, scale);
}

PyMethodDef Methods[] = {
    {"native_mesh_capabilities", reinterpret_cast<PyCFunction>(NativeMeshCapabilities),
     METH_NOARGS,
     "Return native vector mesh safety capabilities."},
    {"difference_paths", reinterpret_cast<PyCFunction>(DifferencePaths),
     METH_VARARGS | METH_KEYWORDS,
     "Difference subject polygon paths by clip polygon paths with Clipper2."},
    {"merge_run_groups", reinterpret_cast<PyCFunction>(MergeRunGroups),
     METH_VARARGS | METH_KEYWORDS,
     "Batch union and close SVG run-group polygons with Clipper2."},
    {"merge_run_groups_to_meshes", reinterpret_cast<PyCFunction>(MergeRunGroupsToMeshes),
     METH_VARARGS | METH_KEYWORDS,
     "Batch union, close, triangulate, and extrude polygons with Clipper2."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef Module = {
    PyModuleDef_HEAD_INIT,
    "clipper2_batch",
    "Minimal Clipper2 batch geometry POC for Lumina vector mesh profiling.",
    -1,
    Methods,
};

}  // namespace

PyMODINIT_FUNC PyInit_clipper2_batch(void) {
  PyObject* module = PyModule_Create(&Module);
  if (!module) {
    return nullptr;
  }
  if (_import_array() < 0) {
    Py_DECREF(module);
    return nullptr;
  }
  return module;
}
