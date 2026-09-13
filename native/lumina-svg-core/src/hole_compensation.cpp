// Copyright 2025 neroued (ChromaPrint3D), Apache-2.0.
// Modified for Lumina Studio: reuse the area/perimeter hole criteria and
// 100000/mm grid from vector_mesh_builder.cpp, without offsets, simplification,
// color grouping, or mesh operations. Canonical noded boundary faces preserve
// painted islands and derive filled coverage after one global union.
// See THIRD_PARTY_NOTICES.md and THIRD_PARTY_LICENSES/ChromaPrint3D.txt.

#include <clipper2/clipper.h>
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

constexpr double kClipperScale = 100000.0;

using CanonicalPoint = clipper::Point<long double>;
using CanonicalPath = clipper::Path<long double>;
using CanonicalBounds = clipper::Rect<long double>;

struct PolygonParts {
  const CanonicalPath* shell;
  std::vector<const CanonicalPath*> interiors;
};

struct CanonicalNode {
  CanonicalPath path;
  bool is_hole = false;
  std::vector<std::unique_ptr<CanonicalNode>> children;
};

struct SimpleRing {
  CanonicalPath path;
  CanonicalBounds bounds;
  long double signed_area;
};

struct PointHash {
  std::size_t operator()(const CanonicalPoint& point) const {
    const auto x = std::hash<long double>{}(point.x);
    const auto y = std::hash<long double>{}(point.y);
    return x ^ (y + 0x9e3779b9 + (x << 6) + (x >> 2));
  }
};

long double Cross(const CanonicalPoint& a, const CanonicalPoint& b) {
  return a.x * b.y - a.y * b.x;
}

long double SignedArea(const CanonicalPath& path) {
  if (path.size() < 3) return 0;
  long double area = 0;
  for (std::size_t index = 1; index + 1 < path.size(); ++index) {
    area += Cross(path[index] - path[0], path[index + 1] - path[0]);
  }
  return area * 0.5L;
}

void SplitTouchingRing(const CanonicalPath& path, std::vector<SimpleRing>& rings) {
  if (path.empty()) return;
  CanonicalPath trace;
  trace.reserve(path.size());
  std::unordered_map<CanonicalPoint, std::size_t, PointHash> positions;
  for (std::size_t index = 0; index <= path.size(); ++index) {
    const auto& point = path[index % path.size()];
    const auto found = positions.find(point);
    if (found == positions.end()) {
      positions.emplace(point, trace.size());
      trace.push_back(point);
      continue;
    }
    const auto start = found->second;
    CanonicalPath cycle(trace.begin() + start, trace.end());
    const long double area = SignedArea(cycle);
    if (area != 0) {
      const auto bounds = clipper::GetBounds(cycle);
      rings.push_back({std::move(cycle), bounds, area});
    }
    for (std::size_t removed = start + 1; removed < trace.size(); ++removed) {
      positions.erase(trace[removed]);
    }
    trace.resize(start + 1);
  }
}

class BoundsIndex {
 public:
  static constexpr std::size_t kMissing = std::numeric_limits<std::size_t>::max();

  explicit BoundsIndex(const std::vector<CanonicalBounds>& bounds) : bounds_(bounds) {
    order_.resize(bounds.size());
    std::iota(order_.begin(), order_.end(), 0);
    if (!bounds.empty()) Build(0, bounds.size());
  }

  template <typename Visitor>
  void Query(const CanonicalBounds& bounds, bool containing, Visitor visit) const {
    if (nodes_.empty()) return;
    std::vector<std::size_t> pending{0};
    while (!pending.empty()) {
      const auto& node = nodes_[pending.back()];
      pending.pop_back();
      if (!Matches(node.bounds, bounds, containing)) continue;
      if (node.left != kMissing) {
        pending.push_back(node.left);
        pending.push_back(node.right);
      } else {
        for (std::size_t item = node.begin; item < node.end; ++item) {
          const auto candidate = order_[item];
          if (Matches(bounds_[candidate], bounds, containing)) visit(candidate);
        }
      }
    }
  }

 private:
  struct Node {
    CanonicalBounds bounds;
    std::size_t begin;
    std::size_t end;
    std::size_t left = kMissing;
    std::size_t right = kMissing;
  };

  static bool Matches(const CanonicalBounds& a, const CanonicalBounds& b, bool containing) {
    return containing ? a.Contains(b) : a.Intersects(b);
  }

  std::size_t Build(std::size_t begin, std::size_t end) {
    auto bounds = bounds_[order_[begin]];
    for (std::size_t index = begin + 1; index < end; ++index) bounds += bounds_[order_[index]];
    const auto node_index = nodes_.size();
    nodes_.push_back({bounds, begin, end});
    if (end - begin <= 8) return node_index;
    const bool split_x = bounds.Width() >= bounds.Height();
    const auto middle = begin + (end - begin) / 2;
    std::nth_element(order_.begin() + begin, order_.begin() + middle, order_.begin() + end,
                     [&](std::size_t a, std::size_t b) {
                       const auto& first = bounds_[a];
                       const auto& second = bounds_[b];
                       return split_x ? first.left + first.right < second.left + second.right
                                      : first.top + first.bottom < second.top + second.bottom;
                     });
    const auto left = Build(begin, middle);
    const auto right = Build(middle, end);
    nodes_[node_index].left = left;
    nodes_[node_index].right = right;
    return node_index;
  }

  const std::vector<CanonicalBounds>& bounds_;
  std::vector<std::size_t> order_;
  std::vector<Node> nodes_;
};

class BoundaryNoder {
 public:
  explicit BoundaryNoder(const std::vector<CanonicalPath>& paths) {
    for (const auto& path : paths) {
      const auto begin = segments_.size();
      for (std::size_t index = 0; index < path.size(); ++index) {
        const auto a = NodeFor(path[index]);
        const auto b = NodeFor(path[(index + 1) % path.size()]);
        if (a == b) continue;
        segments_.push_back({a, b, {{0, a}, {1, b}}});
        bounds_.push_back(clipper::GetBounds(CanonicalPath{nodes_[a], nodes_[b]}));
      }
      ranges_.emplace_back(begin, segments_.size());
    }
  }

  std::vector<CanonicalPath> Run() {
    const BoundsIndex index(bounds_);
    for (std::size_t first = 0; first < segments_.size(); ++first) {
      index.Query(bounds_[first], false, [&](std::size_t second) {
        if (second > first) Intersect(first, second);
      });
    }
    std::vector<CanonicalPath> paths;
    for (const auto [begin, end] : ranges_) {
      CanonicalPath path;
      for (std::size_t index = begin; index < end; ++index) {
        auto& cuts = segments_[index].cuts;
        std::sort(cuts.begin(), cuts.end());
        for (const auto [parameter, node] : cuts) {
          if (parameter < 1 && (path.empty() || path.back() != nodes_[node])) {
            path.push_back(nodes_[node]);
          }
        }
      }
      paths.push_back(std::move(path));
    }
    return paths;
  }

 private:
  struct Segment {
    std::size_t a;
    std::size_t b;
    std::vector<std::pair<long double, std::size_t>> cuts;
  };

  std::size_t NodeFor(const CanonicalPoint& point) {
    const auto [entry, inserted] = node_ids_.emplace(point, nodes_.size());
    if (inserted) nodes_.push_back(point);
    return entry->second;
  }

  void AddCollinearEndpoint(Segment& segment, std::size_t node) {
    const auto& a = nodes_[segment.a];
    const auto direction = nodes_[segment.b] - a;
    const auto relative = nodes_[node] - a;
    const auto parameter = std::abs(direction.x) >= std::abs(direction.y)
                               ? relative.x / direction.x : relative.y / direction.y;
    if (parameter >= 0 && parameter <= 1) segment.cuts.emplace_back(parameter, node);
  }

  void Intersect(std::size_t first, std::size_t second) {
    auto& a = segments_[first];
    auto& b = segments_[second];
    const auto origin = nodes_[a.a];
    const auto other = nodes_[b.a];
    const auto direction = nodes_[a.b] - origin;
    const auto other_direction = nodes_[b.b] - other;
    const auto offset = other - origin;
    const long double denominator = Cross(direction, other_direction);
    if (denominator == 0) {
      if (Cross(offset, direction) != 0) return;
      AddCollinearEndpoint(a, b.a);
      AddCollinearEndpoint(a, b.b);
      AddCollinearEndpoint(b, a.a);
      AddCollinearEndpoint(b, a.b);
      return;
    }
    const long double t = Cross(offset, other_direction) / denominator;
    const long double u = Cross(offset, direction) / denominator;
    if (t < 0 || t > 1 || u < 0 || u > 1) return;
    std::size_t node;
    if (t == 0) node = a.a;
    else if (t == 1) node = a.b;
    else if (u == 0) node = b.a;
    else if (u == 1) node = b.b;
    else node = NodeFor(CanonicalPoint(origin.x + t * direction.x,
                                      origin.y + t * direction.y));
    a.cuts.emplace_back(t, node);
    b.cuts.emplace_back(u, node);
  }

  std::vector<CanonicalPoint> nodes_;
  std::unordered_map<CanonicalPoint, std::size_t, PointHash> node_ids_;
  std::vector<Segment> segments_;
  std::vector<CanonicalBounds> bounds_;
  std::vector<std::pair<std::size_t, std::size_t>> ranges_;
};

int PointLocation(const CanonicalPoint& point, const CanonicalPath& path) {
  bool inside = false;
  for (std::size_t index = 0; index < path.size(); ++index) {
    const auto& a = path[index];
    const auto& b = path[(index + 1) % path.size()];
    const auto cross = Cross(b - a, point - a);
    if (cross == 0 && point.x >= std::min(a.x, b.x) && point.x <= std::max(a.x, b.x) &&
        point.y >= std::min(a.y, b.y) && point.y <= std::max(a.y, b.y)) return 0;
    if ((a.y > point.y) != (b.y > point.y) &&
        point.x < a.x + (point.y - a.y) * (b.x - a.x) / (b.y - a.y)) inside = !inside;
  }
  return inside ? 1 : -1;
}

bool RingContains(const CanonicalPath& outer, const CanonicalPath& inner) {
  for (const auto& point : inner) {
    const int location = PointLocation(point, outer);
    if (location != 0) return location > 0;
  }
  for (std::size_t index = 0; index < inner.size(); ++index) {
    const auto& a = inner[index];
    const auto& b = inner[(index + 1) % inner.size()];
    const int location = PointLocation(CanonicalPoint((a.x + b.x) / 2, (a.y + b.y) / 2), outer);
    if (location != 0) return location > 0;
  }
  return false;
}

void BuildRingTree(std::vector<SimpleRing> rings, CanonicalNode& output) {
  std::vector<CanonicalBounds> bounds;
  for (const auto& ring : rings) bounds.push_back(ring.bounds);
  const BoundsIndex index(bounds);
  std::vector<std::vector<std::size_t>> children(rings.size());
  struct Attachment {
    std::size_t ring;
    CanonicalNode* parent;
    int parent_winding;
  };
  std::vector<Attachment> to_attach;
  for (std::size_t child = 0; child < rings.size(); ++child) {
    const auto& ring = rings[child];
    auto parent = BoundsIndex::kMissing;
    long double parent_area = std::numeric_limits<long double>::infinity();
    index.Query(ring.bounds, true, [&](std::size_t candidate) {
      const auto& enclosing = rings[candidate];
      const long double area = std::abs(enclosing.signed_area);
      if (area > std::abs(ring.signed_area) && area < parent_area &&
          RingContains(enclosing.path, ring.path)) {
        parent = candidate;
        parent_area = area;
      }
    });
    if (parent == BoundsIndex::kMissing) to_attach.push_back({child, &output, 0});
    else children[parent].push_back(child);
  }
  while (!to_attach.empty()) {
    auto [ring_index, parent, parent_winding] = to_attach.back();
    to_attach.pop_back();
    auto& ring = rings[ring_index];
    const int winding = parent_winding + (ring.signed_area > 0 ? 1 : -1);
    // A cycle wholly inside already-painted coverage is retained by that coverage,
    // not emitted as an overlapping duplicate polygon.
    if ((parent_winding == 0) != (winding == 0)) {
      const bool is_hole = winding == 0;
      if ((ring.signed_area > 0) == is_hole) std::reverse(ring.path.begin(), ring.path.end());
      auto node = std::make_unique<CanonicalNode>();
      node->path = std::move(ring.path);
      node->is_hole = is_hole;
      auto* attached = node.get();
      parent->children.push_back(std::move(node));
      parent = attached;
    }
    for (const auto child : children[ring_index]) to_attach.push_back({child, parent, winding});
  }
}

void NormalizeTouchingRings(const clipper::PolyTree64& input, CanonicalNode& output) {
  std::vector<CanonicalPath> paths;
  std::vector<const clipper::PolyPath64*> pending{&input};
  while (!pending.empty()) {
    const auto* node = pending.back();
    pending.pop_back();
    if (!node->Polygon().empty()) {
      CanonicalPath path;
      for (const auto& point : node->Polygon()) path.emplace_back(point);
      paths.push_back(std::move(path));
    }
    for (const auto& child : *node) pending.push_back(child.get());
  }
  std::vector<SimpleRing> rings;
  for (const auto& path : BoundaryNoder(paths).Run()) SplitTouchingRing(path, rings);
  BuildRingTree(std::move(rings), output);
}

struct EdgeKey {
  std::size_t a;
  std::size_t b;
  bool operator==(const EdgeKey& other) const { return a == other.a && b == other.b; }
};

struct EdgeHash {
  std::size_t operator()(const EdgeKey& edge) const {
    return edge.a ^ (edge.b + 0x9e3779b9 + (edge.a << 6) + (edge.a >> 2));
  }
};

bool AngleBefore(const CanonicalPoint& a, const CanonicalPoint& b) {
  const bool first_half = a.y > 0 || (a.y == 0 && a.x >= 0);
  const bool second_half = b.y > 0 || (b.y == 0 && b.x >= 0);
  if (first_half != second_half) return first_half;
  const auto cross = Cross(a, b);
  if (cross != 0) return cross > 0;
  return a.x * a.x + a.y * a.y < b.x * b.x + b.y * b.y;
}

// A shared edge fixes the integer winding difference between its adjacent
// faces. Propagate that relation instead of sampling arbitrarily close to an
// edge, which would make tiny positive faces depend on a numeric epsilon.
std::vector<EdgeKey> PositiveFaceEdges(
    const std::vector<CanonicalPoint>& nodes,
    const std::unordered_map<EdgeKey, int, EdgeHash>& weights) {
  std::vector<EdgeKey> halves;
  std::vector<int> winding_deltas;
  std::vector<std::vector<std::size_t>> outgoing(nodes.size());
  for (const auto& [edge, weight] : weights) {
    if (weight == 0) continue;
    outgoing[edge.a].push_back(halves.size());
    halves.push_back(edge);
    winding_deltas.push_back(weight);
    outgoing[edge.b].push_back(halves.size());
    halves.push_back({edge.b, edge.a});
    winding_deltas.push_back(-weight);
  }
  std::vector<std::size_t> next(halves.size());
  for (std::size_t node = 0; node < outgoing.size(); ++node) {
    auto& edges = outgoing[node];
    std::sort(edges.begin(), edges.end(), [&](std::size_t a, std::size_t b) {
      return AngleBefore(nodes[halves[a].b] - nodes[node], nodes[halves[b].b] - nodes[node]);
    });
    for (std::size_t index = 0; index < edges.size(); ++index) {
      next[edges[index] ^ 1] = edges[(index + edges.size() - 1) % edges.size()];
    }
  }
  std::vector<std::size_t> components(nodes.size(), BoundsIndex::kMissing);
  std::vector<std::size_t> seeds;
  for (std::size_t first = 0; first < nodes.size(); ++first) {
    if (outgoing[first].empty() || components[first] != BoundsIndex::kMissing) continue;
    const auto component = seeds.size();
    seeds.push_back(first);
    std::vector<std::size_t> pending{first};
    components[first] = component;
    while (!pending.empty()) {
      const auto node = pending.back();
      pending.pop_back();
      for (const auto edge : outgoing[node]) {
        const auto other = halves[edge].b;
        if (components[other] != BoundsIndex::kMissing) continue;
        components[other] = component;
        pending.push_back(other);
      }
    }
  }
  std::vector<std::vector<std::size_t>> faces;
  std::vector<std::size_t> face_of(halves.size(), BoundsIndex::kMissing);
  std::vector<std::size_t> outer_faces(seeds.size(), BoundsIndex::kMissing);
  std::vector<long double> outer_areas(seeds.size(), std::numeric_limits<long double>::infinity());
  for (std::size_t first = 0; first < halves.size(); ++first) {
    if (face_of[first] != BoundsIndex::kMissing) continue;
    const auto face = faces.size();
    faces.emplace_back();
    CanonicalPath path;
    auto edge = first;
    do {
      face_of[edge] = face;
      faces.back().push_back(edge);
      path.push_back(nodes[halves[edge].a]);
      edge = next[edge];
    } while (edge != first);
    const auto component = components[halves[first].a];
    const auto area = SignedArea(path);
    if (area < outer_areas[component]) {
      outer_areas[component] = area;
      outer_faces[component] = face;
    }
  }
  std::vector<CanonicalBounds> edge_bounds;
  long double ray_right = -std::numeric_limits<long double>::infinity();
  for (std::size_t edge = 0; edge < halves.size(); edge += 2) {
    const auto bounds = clipper::GetBounds(CanonicalPath{nodes[halves[edge].a], nodes[halves[edge].b]});
    edge_bounds.push_back(bounds);
    ray_right = std::max(ray_right, bounds.right);
  }
  const BoundsIndex edge_index(edge_bounds);
  std::vector<int> windings(faces.size(), std::numeric_limits<int>::min());
  for (std::size_t component = 0; component < seeds.size(); ++component) {
    const auto& point = nodes[seeds[component]];
    int baseline = 0;
    // Components do not touch, so this vertex is strictly off every other
    // component's boundary; their contributions establish the enclosing fill.
    edge_index.Query(CanonicalBounds(point.x, point.y, ray_right, point.y), false,
                     [&](std::size_t candidate) {
      const auto edge = 2 * candidate;
      if (components[halves[edge].a] == component) return;
      const auto& a = nodes[halves[edge].a];
      const auto& b = nodes[halves[edge].b];
      const auto cross = Cross(b - a, point - a);
      if (a.y <= point.y && b.y > point.y && cross > 0) baseline += winding_deltas[edge];
      else if (a.y > point.y && b.y <= point.y && cross < 0) baseline -= winding_deltas[edge];
    });
    std::vector<std::size_t> pending{outer_faces[component]};
    windings[pending.back()] = baseline;
    while (!pending.empty()) {
      const auto face = pending.back();
      pending.pop_back();
      for (const auto edge : faces[face]) {
        const auto other = face_of[edge ^ 1];
        if (windings[other] != std::numeric_limits<int>::min()) continue;
        windings[other] = windings[face] - winding_deltas[edge];
        pending.push_back(other);
      }
    }
  }
  std::vector<EdgeKey> boundary;
  for (std::size_t edge = 0; edge < halves.size(); edge += 2) {
    const bool left = windings[face_of[edge]] > 0;
    const bool right = windings[face_of[edge ^ 1]] > 0;
    if (left != right) boundary.push_back(halves[left ? edge : edge ^ 1]);
  }
  return boundary;
}

// All paths are noded and oriented with the represented area on their left.
// At a contact, follow the next clockwise edge from the incoming reverse edge:
// this traces the same filled face instead of joining disconnected interiors.
std::vector<SimpleRing> TraceBoundaryFaces(const std::vector<CanonicalPath>& paths) {
  std::vector<CanonicalPoint> nodes;
  std::unordered_map<CanonicalPoint, std::size_t, PointHash> node_ids;
  std::unordered_map<EdgeKey, int, EdgeHash> weights;
  const auto node_for = [&](const CanonicalPoint& point) {
    const auto [entry, inserted] = node_ids.emplace(point, nodes.size());
    if (inserted) nodes.push_back(point);
    return entry->second;
  };
  for (const auto& path : paths) {
    for (std::size_t index = 0; index < path.size(); ++index) {
      const auto a = node_for(path[index]);
      const auto b = node_for(path[(index + 1) % path.size()]);
      if (a != b) weights[{std::min(a, b), std::max(a, b)}] += a < b ? 1 : -1;
    }
  }
  const auto edges = PositiveFaceEdges(nodes, weights);
  std::vector<std::vector<std::size_t>> outgoing(nodes.size());
  for (std::size_t index = 0; index < edges.size(); ++index) {
    outgoing[edges[index].a].push_back(index);
  }
  std::vector<std::size_t> next(edges.size());
  const long double full_turn = 2 * std::acos(-1.0L);
  for (std::size_t index = 0; index < edges.size(); ++index) {
    const auto& edge = edges[index];
    const auto reverse = nodes[edge.a] - nodes[edge.b];
    long double best = std::numeric_limits<long double>::infinity();
    next[index] = BoundsIndex::kMissing;
    for (const auto candidate : outgoing[edge.b]) {
      const auto direction = nodes[edges[candidate].b] - nodes[edge.b];
      const auto angle = std::atan2(Cross(reverse, direction),
                                   reverse.x * direction.x + reverse.y * direction.y);
      const auto clockwise = angle <= 0 ? -angle : full_turn - angle;
      if (clockwise < best) {
        next[index] = candidate;
        best = clockwise;
      }
    }
  }
  std::vector<SimpleRing> rings;
  std::vector<bool> visited(edges.size(), false);
  for (std::size_t first = 0; first < edges.size(); ++first) {
    if (visited[first]) continue;
    CanonicalPath path;
    auto edge = first;
    while (edge != BoundsIndex::kMissing && !visited[edge]) {
      visited[edge] = true;
      path.push_back(nodes[edges[edge].a]);
      edge = next[edge];
    }
    if (edge != first) {
      throw std::runtime_error("SVG compensation boundary did not close: paths=" +
          std::to_string(paths.size()) +
          " at=" + std::to_string(path.back().x / kClipperScale) + "," +
          std::to_string(path.back().y / kClipperScale));
    }
    SplitTouchingRing(path, rings);
  }
  return rings;
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
