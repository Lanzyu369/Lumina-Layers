#define PY_SSIZE_T_CLEAN
#include <Python.h>
#define NPY_NO_DEPRECATED_API NPY_1_7_API_VERSION
#include <numpy/arrayobject.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
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
  return std::fabsl(signed_sum);
}

long double TriangleAreaSum(const Paths64& triangles) {
  long double total = 0.0L;
  for (const Path64& triangle : triangles) {
    total += std::fabsl(SignedArea(triangle));
  }
  return total;
}

bool TriangulatedAreaMatches(const Paths64& paths, const Paths64& triangles) {
  const long double expected_area = FilledArea(paths);
  const long double triangle_area = TriangleAreaSum(triangles);
  const long double delta = std::fabsl(triangle_area - expected_area);
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

  size_t point_count = 0;
  for (const PolyWithHoles& poly : polygons) {
    for (const Path64& ring : poly.rings) {
      point_count += ring.size();
    }
  }

  std::unordered_map<PointKey, int64_t, PointKeyHash> bottom_index;
  std::unordered_map<PointKey, int64_t, PointKeyHash> top_index;
  bottom_index.reserve(point_count);
  top_index.reserve(point_count);

  for (const PolyWithHoles& poly : polygons) {
    if (poly.rings.empty()) {
      continue;
    }
    if (!AddTriangleFacesForPaths(
            mesh, bottom_index, top_index, poly.rings, scale, height, z_offset, xy_scale)) {
      return MeshOutput{};
    }
    for (const Path64& ring : poly.rings) {
      AddSideFacesForPath(mesh, bottom_index, top_index, ring, scale, height, z_offset, xy_scale);
    }
  }

  return mesh;
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
  static const char* kwlist[] = {
      "groups", "close_delta_mm", "scale", "height", "z_offset", "xy_scale", nullptr};
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|dLddd",
                                   const_cast<char**>(kwlist),
                                   &groups_obj, &close_delta_mm, &scale_arg,
                                   &height, &z_offset, &xy_scale)) {
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
  Py_BEGIN_ALLOW_THREADS
  for (size_t i = 0; i < groups.size(); ++i) {
    GroupOutput polygons = ProcessGroup(groups[i], close_delta);
    outputs[i] = ExtrudePolygonsToMesh(polygons, scale, height, z_offset, xy_scale);
  }
  Py_END_ALLOW_THREADS

  PyObject* result = PyList_New(static_cast<Py_ssize_t>(outputs.size()));
  if (!result) {
    return nullptr;
  }
  for (Py_ssize_t i = 0; i < static_cast<Py_ssize_t>(outputs.size()); ++i) {
    PyObject* py_mesh = BuildMesh(outputs[static_cast<size_t>(i)]);
    if (!py_mesh) {
      Py_DECREF(result);
      return nullptr;
    }
    PyList_SET_ITEM(result, i, py_mesh);
  }
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
