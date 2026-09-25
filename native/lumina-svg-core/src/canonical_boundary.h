// Copyright 2025 neroued (ChromaPrint3D), Apache-2.0.
// Modified for Lumina Studio: one canonical boundary rule shared by every
// consumer of the engine's area output.
//
// The rule: a painted region is expressed as simple rings with a shell/hole
// hierarchy rebuilt from containment and nesting parity. The region itself is
// taken from the integer linework, so noded re-expression cannot move filled
// area - it only removes self-contact that downstream OGC/GEOS consumers reject.
//
// Boundary forms with defined handling:
//   * a ring that visits one vertex twice (two lobes joined at a point),
//   * a vertex lying on a non-adjacent edge (T contact),
//   * collinear or reversed overlapping edge runs,
//   * a genuine non-adjacent edge crossing,
//   * the same forms on hole rings, and a hole that touches its shell.
//
// See THIRD_PARTY_NOTICES.md and THIRD_PARTY_LICENSES/ChromaPrint3D.txt.
#ifndef LUMINA_SVG_CORE_CANONICAL_BOUNDARY_H
#define LUMINA_SVG_CORE_CANONICAL_BOUNDARY_H

#include <clipper2/clipper.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <memory>
#include <numeric>
#include <unordered_map>
#include <utility>
#include <vector>

namespace lumina::canonical {

// The engine's own alias for Clipper2, so both translation units that use this
// header see the same spelling.
namespace clipper = Clipper2Lib;

// Coordinate-domain policy. Integral coordinates are the engine's authoritative
// grid: predicates there must be exact, and computed intersections land on the
// grid exactly like every other result coordinate. Floating domains (the
// hole-compensation surface) keep their own arithmetic.
template <typename Coord>
struct Domain {
  using Point = clipper::Point<Coord>;
  using Path = clipper::Path<Coord>;
  using Bounds = clipper::Rect<Coord>;

  // Exact "u x v == 0".
  static bool CrossIsZero(const Point& u, const Point& v) {
    return u.x * v.y == u.y * v.x;
  }

  // Place a computed coordinate on the domain's grid.
  static Coord Quantize(long double value) { return static_cast<Coord>(value); }
};

template <>
struct Domain<int64_t> {
  using Point = clipper::Point<int64_t>;
  using Path = clipper::Path<int64_t>;
  using Bounds = clipper::Rect<int64_t>;

  // Clipper2's carry-aware product test keeps this exact without __int128,
  // which MSVC does not provide.
  static bool CrossIsZero(const Point& u, const Point& v) {
    return Clipper2Lib::ProductsAreEqual(u.x, v.y, u.y, v.x);
  }

  static int64_t Quantize(long double value) {
    return static_cast<int64_t>(std::llround(value));
  }
};

template <typename Coord>
using PointOf = typename Domain<Coord>::Point;
template <typename Coord>
using PathOf = typename Domain<Coord>::Path;
template <typename Coord>
using BoundsOf = typename Domain<Coord>::Bounds;

// Exact 128-bit products of grid coordinates, so every question about an
// intersection - is the contact an endpoint, does it lie inside both segments,
// which cut comes first - is answered by integers. A floating parameter rounds
// a shared endpoint to just short of it (a segment meeting another at its own
// end reads as 0.9999999968), which invents a node several grid units away and
// turns a legal shared vertex into a coincident edge. MSVC has no __int128, so
// the product is assembled from 32-bit halves.
namespace wide {

struct Product {
  int64_t high;
  uint64_t low;

  int Sign() const {
    if (high != 0) return high < 0 ? -1 : 1;
    return low != 0 ? 1 : 0;
  }
};

inline int Compare(const Product& left, const Product& right) {
  if (left.high != right.high) return left.high < right.high ? -1 : 1;
  if (left.low != right.low) return left.low < right.low ? -1 : 1;
  return 0;
}

inline Product Multiply(int64_t left, int64_t right) {
  const bool negative = (left < 0) != (right < 0);
  const auto a = left < 0 ? ~static_cast<uint64_t>(left) + 1
                          : static_cast<uint64_t>(left);
  const auto b = right < 0 ? ~static_cast<uint64_t>(right) + 1
                           : static_cast<uint64_t>(right);
  const auto a0 = a & 0xffffffffULL;
  const auto a1 = a >> 32;
  const auto b0 = b & 0xffffffffULL;
  const auto b1 = b >> 32;
  const auto p00 = a0 * b0;
  const auto p01 = a0 * b1;
  const auto p10 = a1 * b0;
  const auto p11 = a1 * b1;
  const auto middle =
      (p00 >> 32) + (p01 & 0xffffffffULL) + (p10 & 0xffffffffULL);
  const auto low = (middle << 32) | (p00 & 0xffffffffULL);
  const auto high = p11 + (p01 >> 32) + (p10 >> 32) + (middle >> 32);
  if (!negative) return {static_cast<int64_t>(high), low};
  const auto negated = ~low + 1;
  return {static_cast<int64_t>(~high + (negated == 0 ? 1 : 0)), negated};
}

inline Product Negated(const Product& value) {
  const auto negated = ~value.low + 1;
  return {static_cast<int64_t>(~value.high + (negated == 0 ? 1 : 0)),
          negated};
}

// Sum of two products: the dot product that places a cut along a segment.
inline Product Add(const Product& left, const Product& right) {
  const auto low = left.low + right.low;
  const auto carry = low < left.low ? 1 : 0;
  return {left.high + right.high + static_cast<int64_t>(carry), low};
}

inline long double Value(const Product& value) {
  return static_cast<long double>(value.high) * 18446744073709551616.0L
      + static_cast<long double>(value.low);
}

}  // namespace wide

// Cross product magnitude of two vectors. Returned wide because the product of
// two grid coordinates does not fit the coordinate type.
template <typename Coord>
inline long double Cross(const PointOf<Coord>& a, const PointOf<Coord>& b) {
  return static_cast<long double>(a.x) * static_cast<long double>(b.y)
      - static_cast<long double>(a.y) * static_cast<long double>(b.x);
}

// The arithmetic the noder classifies intersections with: exact on the integer
// grid, floating on the continuous domains that share the rule.
template <typename Coord>
struct IntersectionMath {
  using Wide = long double;

  static Wide Zero() { return 0.0L; }
  static Wide Cross(const PointOf<Coord>& u, const PointOf<Coord>& v) {
    return canonical::Cross<Coord>(u, v);
  }
  static Wide Dot(const PointOf<Coord>& u, const PointOf<Coord>& v) {
    return static_cast<long double>(u.x) * static_cast<long double>(v.x)
        + static_cast<long double>(u.y) * static_cast<long double>(v.y);
  }
  static Wide Negated(Wide value) { return -value; }
  static int Compare(Wide left, Wide right) {
    return left < right ? -1 : (right < left ? 1 : 0);
  }
  static int Sign(Wide value) { return value > 0 ? 1 : (value < 0 ? -1 : 0); }
  static long double Value(Wide value) { return value; }
};

template <>
struct IntersectionMath<int64_t> {
  using Wide = wide::Product;

  static Wide Zero() { return {0, 0}; }
  static Wide Cross(const PointOf<int64_t>& u, const PointOf<int64_t>& v) {
    return wide::Add(wide::Multiply(u.x, v.y),
                     wide::Negated(wide::Multiply(u.y, v.x)));
  }
  static Wide Dot(const PointOf<int64_t>& u, const PointOf<int64_t>& v) {
    return wide::Add(wide::Multiply(u.x, v.x), wide::Multiply(u.y, v.y));
  }
  static Wide Negated(Wide value) { return wide::Negated(value); }
  static int Compare(Wide left, Wide right) {
    return wide::Compare(left, right);
  }
  static int Sign(Wide value) { return value.Sign(); }
  static long double Value(Wide value) { return wide::Value(value); }
};

template <typename Coord>
inline long double SignedArea(const PathOf<Coord>& path) {
  if (path.size() < 3) return 0;
  long double area = 0;
  for (std::size_t index = 1; index + 1 < path.size(); ++index) {
    area += Cross<Coord>(path[index] - path[0], path[index + 1] - path[0]);
  }
  return area * 0.5L;
}

// Every vertex on one line: exactly zero area, whatever the area arithmetic
// rounds to.
template <typename Coord>
inline bool HasZeroArea(const PathOf<Coord>& path) {
  if (path.size() < 3) return true;
  for (std::size_t index = 0; index < path.size(); ++index) {
    const auto& a = path[(index + path.size() - 1) % path.size()];
    const auto& b = path[index];
    const auto& c = path[(index + 1) % path.size()];
    if (a == b) continue;
    if (Domain<Coord>::CrossIsZero(b - a, c - b)) continue;
    return false;
  }
  return true;
}

template <typename Coord>
struct PointHash {
  std::size_t operator()(const PointOf<Coord>& point) const {
    const auto x = std::hash<Coord>{}(point.x);
    const auto y = std::hash<Coord>{}(point.y);
    return x ^ (y + 0x9e3779b9 + (x << 6) + (x >> 2));
  }
};

template <typename Coord>
struct SimpleRing {
  PathOf<Coord> path;
  BoundsOf<Coord> bounds;
  long double signed_area;
};

// Split one noded path into simple cycles: a path that visits a vertex twice
// carries two lobes that only touch, and each lobe is its own ring.
template <typename Coord>
inline void SplitTouchingRing(const PathOf<Coord>& path,
                              std::vector<SimpleRing<Coord>>& rings) {
  if (path.empty()) return;
  PathOf<Coord> trace;
  trace.reserve(path.size());
  std::unordered_map<PointOf<Coord>, std::size_t, PointHash<Coord>> positions;
  for (std::size_t index = 0; index <= path.size(); ++index) {
    const auto& point = path[index % path.size()];
    const auto found = positions.find(point);
    if (found == positions.end()) {
      positions.emplace(point, trace.size());
      trace.push_back(point);
      continue;
    }
    const auto start = found->second;
    PathOf<Coord> cycle(trace.begin() + start, trace.end());
    const long double area = SignedArea<Coord>(cycle);
    if (area != 0 && !HasZeroArea<Coord>(cycle)) {
      const auto bounds = clipper::GetBounds(cycle);
      rings.push_back({std::move(cycle), bounds, area});
    }
    for (std::size_t removed = start + 1; removed < trace.size(); ++removed) {
      positions.erase(trace[removed]);
    }
    trace.resize(start + 1);
  }
}

template <typename Coord>
class BoundsIndex {
 public:
  static constexpr std::size_t kMissing =
      std::numeric_limits<std::size_t>::max();

  explicit BoundsIndex(const std::vector<BoundsOf<Coord>>& bounds)
      : bounds_(bounds) {
    order_.resize(bounds.size());
    std::iota(order_.begin(), order_.end(), 0);
    if (!bounds.empty()) Build(0, bounds.size());
  }

  template <typename Visitor>
  void Query(const BoundsOf<Coord>& bounds, bool containing,
             Visitor visit) const {
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
    BoundsOf<Coord> bounds;
    std::size_t begin;
    std::size_t end;
    std::size_t left = kMissing;
    std::size_t right = kMissing;
  };

  static bool Matches(const BoundsOf<Coord>& a, const BoundsOf<Coord>& b,
                      bool containing) {
    return containing ? a.Contains(b) : a.Intersects(b);
  }

  std::size_t Build(std::size_t begin, std::size_t end) {
    auto bounds = bounds_[order_[begin]];
    for (std::size_t index = begin + 1; index < end; ++index) {
      bounds += bounds_[order_[index]];
    }
    const auto node_index = nodes_.size();
    nodes_.push_back({bounds, begin, end});
    if (end - begin <= 8) return node_index;
    const bool split_x = bounds.Width() >= bounds.Height();
    const auto middle = begin + (end - begin) / 2;
    std::nth_element(
        order_.begin() + begin, order_.begin() + middle, order_.begin() + end,
        [&](std::size_t a, std::size_t b) {
          const auto& first = bounds_[a];
          const auto& second = bounds_[b];
          return split_x
              ? first.left + first.right < second.left + second.right
              : first.top + first.bottom < second.top + second.bottom;
        });
    const auto left = Build(begin, middle);
    const auto right = Build(middle, end);
    nodes_[node_index].left = left;
    nodes_[node_index].right = right;
    return node_index;
  }

  const std::vector<BoundsOf<Coord>>& bounds_;
  std::vector<std::size_t> order_;
  std::vector<Node> nodes_;
};

// Node a ring set: split every segment at each intersection it takes part in,
// including T contacts and collinear overlaps, so emitted paths meet only at
// shared endpoints. A computed crossing lands on the domain grid, so callers
// re-node the quantized result before using it (standard snap rounding).
template <typename Coord>
class BoundaryNoder {
 public:
  explicit BoundaryNoder(const std::vector<PathOf<Coord>>& paths) {
    for (std::size_t ring = 0; ring < paths.size(); ++ring) {
      const auto& path = paths[ring];
      const auto begin = segments_.size();
      for (std::size_t index = 0; index < path.size(); ++index) {
        const auto a = NodeFor(path[index]);
        NoteVertex(a, ring);
        const auto b = NodeFor(path[(index + 1) % path.size()]);
        if (a == b) continue;
        segments_.push_back({a, b, {{Math::Zero(), a}}, ring});
        bounds_.push_back(
            clipper::GetBounds(PathOf<Coord>{nodes_[a], nodes_[b]}));
      }
      ranges_.emplace_back(begin, segments_.size());
    }
  }

  // The input already met only at shared endpoints: nothing had to be split.
  bool AlreadyNoded() const { return already_noded_; }

  // Whether the ring set is already a legal boundary expression of the region
  // it encloses, so it can be exported as it stands. OGC consumers accept a
  // region exactly when every ring is simple and non-degenerate, every contact
  // between two rings is a vertex they share, and no two rings meet in more
  // than one such vertex. A vertex resting in the middle of another ring's
  // edge, two rings meeting twice, or a ring touching itself are all rejected,
  // and are the cases that get re-expressed as faces. Valid after Run().
  bool Canonical() const {
    return !self_revisit_ && !multi_contact_ && !unshared_contact_
        && !degenerate_;
  }

  std::vector<PathOf<Coord>> Run() {
    const BoundsIndex<Coord> index(bounds_);
    for (std::size_t first = 0; first < segments_.size(); ++first) {
      index.Query(bounds_[first], false, [&](std::size_t second) {
        if (second > first) Intersect(first, second);
      });
    }
    return Emit();
  }

 private:
  using Math = IntersectionMath<Coord>;
  using Wide = typename Math::Wide;

  // A cut carries the exact projection of its node onto the segment, so the
  // order of cuts along a segment never depends on a rounded parameter.
  struct Cut {
    Wide along;
    std::size_t node;
  };

  struct Segment {
    std::size_t a;
    std::size_t b;
    std::vector<Cut> cuts;
    std::size_t ring;
  };

  std::size_t NodeFor(const PointOf<Coord>& point) {
    const auto [entry, inserted] = node_ids_.emplace(point, nodes_.size());
    if (inserted) {
      nodes_.push_back(point);
      vertex_owner_.push_back(kNoRing);
      vertex_second_.push_back(kNoRing);
    }
    return entry->second;
  }

  // Remember which rings use a point as one of their own vertices, so a cut
  // landing in the middle of a segment can tell whether that point arrived
  // from another ring rather than from this one.
  void NoteVertex(std::size_t node, std::size_t ring) {
    auto& owner = vertex_owner_[node];
    if (owner == kNoRing) {
      owner = ring;
    } else if (owner != ring && vertex_second_[node] == kNoRing) {
      vertex_second_[node] = ring;
    }
  }

  // Where a node sits along a segment, exactly: the projection of its offset
  // onto the segment's direction grows monotonically from one end to the other.
  Wide Along(const Segment& segment, std::size_t node) const {
    return Math::Dot(nodes_[node] - nodes_[segment.a],
                     nodes_[segment.b] - nodes_[segment.a]);
  }

  // Split a segment at a node that its interior meets. Cuts at its own ends
  // add nothing: the emitted path already carries every segment's start.
  void AddCut(Segment& segment, std::size_t node) {
    if (node == segment.a || node == segment.b) return;
    segment.cuts.push_back({Along(segment, node), node});
    already_noded_ = false;
    // The point is inside this segment but is not one of its ends: the ring
    // either touches another ring, or itself, at a spot that is not a shared
    // vertex - a form no consumer accepts.
    if (vertex_owner_[node] != segment.ring
        || vertex_second_[node] != kNoRing) {
      unshared_contact_ = true;
    }
  }

  // A collinear neighbour's endpoint that lands inside this segment splits it.
  void AddCollinearEndpoint(Segment& segment, std::size_t node) {
    const auto direction = nodes_[segment.b] - nodes_[segment.a];
    const auto relative = nodes_[node] - nodes_[segment.a];
    const auto along = Math::Dot(relative, direction);
    if (Math::Sign(along) < 0) return;
    if (Math::Compare(Math::Dot(direction, direction), along) < 0) return;
    AddCut(segment, node);
  }

  // Classify the contact between two segments on exact values: both crossing
  // parameters are compared against zero and against the denominator as
  // integers, so a segment that meets another exactly at its own end is
  // recognized as a shared endpoint instead of being rounded into an interior
  // crossing, and a genuine crossing is never missed. Only a crossing strictly
  // inside both segments creates a node, and it lands on the domain grid like
  // every other computed coordinate.
  void Intersect(std::size_t first, std::size_t second) {
    auto& a = segments_[first];
    auto& b = segments_[second];
    const auto origin = nodes_[a.a];
    const auto other = nodes_[b.a];
    const auto direction = nodes_[a.b] - origin;
    const auto other_direction = nodes_[b.b] - other;
    const auto offset = other - origin;
    auto denominator = Math::Cross(direction, other_direction);
    if (Math::Sign(denominator) == 0) {
      if (Math::Sign(Math::Cross(offset, direction)) != 0) return;
      AddCollinearEndpoint(a, b.a);
      AddCollinearEndpoint(a, b.b);
      AddCollinearEndpoint(b, a.a);
      AddCollinearEndpoint(b, a.b);
      return;
    }
    auto numerator_a = Math::Cross(offset, other_direction);
    auto numerator_b = Math::Cross(offset, direction);
    if (Math::Sign(denominator) < 0) {
      denominator = Math::Negated(denominator);
      numerator_a = Math::Negated(numerator_a);
      numerator_b = Math::Negated(numerator_b);
    }
    if (Math::Sign(numerator_a) < 0) return;
    if (Math::Compare(denominator, numerator_a) < 0) return;
    if (Math::Sign(numerator_b) < 0) return;
    if (Math::Compare(denominator, numerator_b) < 0) return;
    std::size_t node;
    if (Math::Sign(numerator_a) == 0) node = a.a;
    else if (Math::Compare(numerator_a, denominator) == 0) node = a.b;
    else if (Math::Sign(numerator_b) == 0) node = b.a;
    else if (Math::Compare(numerator_b, denominator) == 0) node = b.b;
    else {
      const auto t = Math::Value(numerator_a) / Math::Value(denominator);
      node = NodeFor(PointOf<Coord>{
          Domain<Coord>::Quantize(
              static_cast<long double>(origin.x)
              + t * static_cast<long double>(direction.x)),
          Domain<Coord>::Quantize(
              static_cast<long double>(origin.y)
              + t * static_cast<long double>(direction.y))});
      already_noded_ = false;
    }
    AddCut(a, node);
    AddCut(b, node);
  }

  std::vector<PathOf<Coord>> Emit() {
    std::vector<PathOf<Coord>> paths;
    paths.reserve(ranges_.size());
    last_ring_.assign(nodes_.size(), kNoRing);
    shared_uses_.clear();
    for (std::size_t ring = 0; ring < ranges_.size(); ++ring) {
      const auto [begin, end] = ranges_[ring];
      PathOf<Coord> path;
      std::vector<std::size_t> ids;
      for (std::size_t index = begin; index < end; ++index) {
        auto& cuts = segments_[index].cuts;
        std::sort(cuts.begin(), cuts.end(),
                  [](const Cut& left, const Cut& right) {
                    const auto order = Math::Compare(left.along, right.along);
                    if (order != 0) return order < 0;
                    return left.node < right.node;
                  });
        for (const auto& cut : cuts) {
          if (cut.node != segments_[index].b
              && (ids.empty() || ids.back() != cut.node)) {
            path.push_back(nodes_[cut.node]);
            ids.push_back(cut.node);
          }
        }
      }
      AuditRing(path, ids, ring);
      paths.push_back(std::move(path));
    }
    multi_contact_ = MultiContact();
    return paths;
  }

  // Judge one emitted ring: a vertex it visits twice is a self-touch, and a
  // vertex another ring also uses puts the two rings in contact there. Both
  // questions are read from records kept per node, and neither depends on which
  // ring happened to arrive first.
  void AuditRing(const PathOf<Coord>& path, const std::vector<std::size_t>& ids,
                 std::size_t ring) {
    if (HasZeroArea<Coord>(path)) degenerate_ = true;
    for (const auto node : ids) {
      auto& previous = last_ring_[node];
      // Neighbouring repeats are already gone, so the ring meets itself here:
      // two lobes joined at this point, which no consumer accepts. Whether
      // another ring had used the node before says nothing about this.
      if (previous == ring) {
        self_revisit_ = true;
        continue;
      }
      // Every ring that uses the node is recorded, so two rings meeting twice
      // are found whichever order they are audited in.
      auto& users = shared_uses_[node];
      if (previous != kNoRing
          && std::find(users.begin(), users.end(), previous) == users.end()) {
        users.push_back(previous);
      }
      if (std::find(users.begin(), users.end(), ring) == users.end()) {
        users.push_back(ring);
      }
      previous = ring;
    }
  }

  // Two rings sharing two or more points share an edge or cut the region
  // apart: a hole meeting its shell twice, or spanning between two holes.
  bool MultiContact() const {
    std::unordered_map<std::uint64_t, std::size_t> pairs;
    for (const auto& [node, users] : shared_uses_) {
      for (std::size_t first = 0; first < users.size(); ++first) {
        for (std::size_t second = first + 1; second < users.size(); ++second) {
          const auto low = std::min(users[first], users[second]);
          const auto high = std::max(users[first], users[second]);
          const std::uint64_t key =
              static_cast<std::uint64_t>(low) * ranges_.size() + high;
          if (++pairs[key] >= 2) return true;
        }
      }
    }
    return false;
  }

  std::vector<PointOf<Coord>> nodes_;
  std::unordered_map<PointOf<Coord>, std::size_t, PointHash<Coord>> node_ids_;
  std::vector<Segment> segments_;
  static constexpr std::size_t kNoRing = std::numeric_limits<std::size_t>::max();

  std::vector<BoundsOf<Coord>> bounds_;
  std::vector<std::pair<std::size_t, std::size_t>> ranges_;
  // Per node: the first two rings that own it as a vertex.
  std::vector<std::size_t> vertex_owner_;
  std::vector<std::size_t> vertex_second_;
  // Per node: the last emitted ring that visited it, cleared with the audit.
  // A repeat of the ring being audited is its own self-touch; the record,
  // together with `shared_uses_`, also tells which rings the node puts in
  // contact.
  std::vector<std::size_t> last_ring_;
  std::unordered_map<std::size_t, std::vector<std::size_t>> shared_uses_;
  bool already_noded_ = true;
  bool self_revisit_ = false;
  bool multi_contact_ = false;
  bool unshared_contact_ = false;
  bool degenerate_ = false;
};

template <typename Coord>
inline int PointLocation(const PointOf<Coord>& point,
                         const PathOf<Coord>& path) {
  bool inside = false;
  for (std::size_t index = 0; index < path.size(); ++index) {
    const auto& a = path[index];
    const auto& b = path[(index + 1) % path.size()];
    if (Domain<Coord>::CrossIsZero(b - a, point - a)
        && point.x >= std::min(a.x, b.x) && point.x <= std::max(a.x, b.x)
        && point.y >= std::min(a.y, b.y) && point.y <= std::max(a.y, b.y)) {
      return 0;
    }
    if ((a.y > point.y) != (b.y > point.y)) {
      // Compare the ray intersection by orientation, rather than dividing
      // large integer products into long double.  The sign of
      // cross(b-a, point-a) equals the sign of dy exactly when the point is
      // left of the edge intersection.  This keeps the int64 grid exact while
      // preserving the existing floating-domain rule through IntersectionMath.
      const auto cross = IntersectionMath<Coord>::Cross(
          b - a, point - a);
      const int cross_sign = IntersectionMath<Coord>::Sign(cross);
      const int edge_y_sign = b.y > a.y ? 1 : -1;
      if (cross_sign == edge_y_sign) inside = !inside;
    }
  }
  return inside ? 1 : -1;
}

template <typename Coord>
inline bool RingContains(const PathOf<Coord>& outer,
                         const PathOf<Coord>& inner) {
  for (const auto& point : inner) {
    const int location = PointLocation<Coord>(point, outer);
    if (location != 0) return location > 0;
  }
  for (std::size_t index = 0; index < inner.size(); ++index) {
    const auto& a = inner[index];
    const auto& b = inner[(index + 1) % inner.size()];
    const PointOf<Coord> middle{
        Domain<Coord>::Quantize(
            (static_cast<long double>(a.x) + static_cast<long double>(b.x))
            / 2.0L),
        Domain<Coord>::Quantize(
            (static_cast<long double>(a.y) + static_cast<long double>(b.y))
            / 2.0L)};
    const int location = PointLocation<Coord>(middle, outer);
    if (location != 0) return location > 0;
  }
  return false;
}

template <typename Coord>
struct CanonicalNode {
  PathOf<Coord> path;
  bool is_hole = false;
  std::vector<std::unique_ptr<CanonicalNode>> children;
};

// Rebuild shell/hole nesting from containment and parity: a ring directly
// inside filled coverage is a hole, a ring inside a hole is filled again.
// Orientation follows the engine's convention (filled rings positive, holes
// negative).
template <typename Coord>
inline void BuildRingTree(std::vector<SimpleRing<Coord>> rings,
                          CanonicalNode<Coord>& output) {
  std::vector<BoundsOf<Coord>> bounds;
  bounds.reserve(rings.size());
  for (const auto& ring : rings) bounds.push_back(ring.bounds);
  const BoundsIndex<Coord> index(bounds);
  std::vector<std::vector<std::size_t>> children(rings.size());
  struct Attachment {
    std::size_t ring;
    CanonicalNode<Coord>* parent;
    int parent_winding;
  };
  std::vector<Attachment> to_attach;
  for (std::size_t child = 0; child < rings.size(); ++child) {
    const auto& ring = rings[child];
    auto parent = BoundsIndex<Coord>::kMissing;
    long double parent_area = std::numeric_limits<long double>::infinity();
    index.Query(ring.bounds, true, [&](std::size_t candidate) {
      const auto& enclosing = rings[candidate];
      const long double area = std::abs(enclosing.signed_area);
      if (area > std::abs(ring.signed_area) && area < parent_area
          && RingContains<Coord>(enclosing.path, ring.path)) {
        parent = candidate;
        parent_area = area;
      }
    });
    if (parent == BoundsIndex<Coord>::kMissing) {
      to_attach.push_back({child, &output, 0});
    } else {
      children[parent].push_back(child);
    }
  }
  while (!to_attach.empty()) {
    auto [ring_index, parent, parent_winding] = to_attach.back();
    to_attach.pop_back();
    auto& ring = rings[ring_index];
    const int winding = parent_winding + (ring.signed_area > 0 ? 1 : -1);
    // A cycle wholly inside already-painted coverage is retained by that
    // coverage, not emitted as an overlapping duplicate polygon.
    if ((parent_winding == 0) != (winding == 0)) {
      const bool is_hole = winding == 0;
      if ((ring.signed_area > 0) == is_hole) {
        std::reverse(ring.path.begin(), ring.path.end());
      }
      auto node = std::make_unique<CanonicalNode<Coord>>();
      node->path = std::move(ring.path);
      node->is_hole = is_hole;
      auto* attached = node.get();
      parent->children.push_back(std::move(node));
      parent = attached;
    }
    for (const auto child : children[ring_index]) {
      to_attach.push_back({child, parent, winding});
    }
  }
}

// Node linework until it settles: quantized crossings can introduce contacts
// that the next pass splits, and two passes suffice for the engine grid.
// `already_canonical`, when asked for, reports that the input was already a
// legal boundary expression of its region, so a caller can keep emitting it as
// it stands instead of re-expressing it.
template <typename Coord>
inline std::vector<PathOf<Coord>> NodeToGrid(
    const std::vector<PathOf<Coord>>& paths,
    bool* already_canonical = nullptr) {
  std::vector<PathOf<Coord>> current = paths;
  for (int pass = 0; pass < 2; ++pass) {
    BoundaryNoder<Coord> noder(current);
    auto noded = noder.Run();
    if (pass == 0 && already_canonical != nullptr) {
      *already_canonical = noder.Canonical();
    }
    if (noder.AlreadyNoded()) return noded;
    current = std::move(noded);
  }
  return current;
}

// Canonical rings from an already noded path set.
template <typename Coord>
inline void BuildRingsFromNoded(const std::vector<PathOf<Coord>>& noded,
                                CanonicalNode<Coord>& output) {
  std::vector<SimpleRing<Coord>> rings;
  for (const auto& path : noded) SplitTouchingRing<Coord>(path, rings);
  BuildRingTree<Coord>(std::move(rings), output);
}

// The rule itself. Used by the engine's area output and by the
// hole-compensation surface, so both express boundaries the same way.
template <typename Coord>
inline void BuildCanonicalRings(const std::vector<PathOf<Coord>>& paths,
                                CanonicalNode<Coord>& output) {
  BuildRingsFromNoded<Coord>(NodeToGrid<Coord>(paths), output);
}

// Collect every polygon a PolyTree holds, outer rings and holes alike.
template <typename Coord>
inline std::vector<PathOf<Coord>> PolyTreePaths(const clipper::PolyTree64& tree) {
  std::vector<PathOf<Coord>> paths;
  std::vector<const clipper::PolyPath64*> pending{&tree};
  while (!pending.empty()) {
    const auto* node = pending.back();
    pending.pop_back();
    if (!node->Polygon().empty()) {
      PathOf<Coord> path;
      path.reserve(node->Polygon().size());
      for (const auto& point : node->Polygon()) path.emplace_back(point);
      paths.push_back(std::move(path));
    }
    for (const auto& child : *node) pending.push_back(child.get());
  }
  return paths;
}

template <typename Coord>
inline long double Dot(const PointOf<Coord>& a, const PointOf<Coord>& b) {
  return static_cast<long double>(a.x) * static_cast<long double>(b.x)
      + static_cast<long double>(a.y) * static_cast<long double>(b.y);
}

template <typename Coord>
inline long double SquaredLength(const PointOf<Coord>& value) {
  return Dot<Coord>(value, value);
}

template <typename Coord>
inline bool AngleBefore(const PointOf<Coord>& a, const PointOf<Coord>& b) {
  using Math = IntersectionMath<Coord>;
  const bool first_half = a.y > 0 || (a.y == 0 && a.x >= 0);
  const bool second_half = b.y > 0 || (b.y == 0 && b.x >= 0);
  if (first_half != second_half) return first_half;
  const int cross_sign = Math::Sign(Math::Cross(a, b));
  if (cross_sign != 0) return cross_sign > 0;
  return Math::Compare(Math::Dot(a, a), Math::Dot(b, b)) < 0;
}

template <typename Coord>
struct EdgeKey {
  std::size_t a;
  std::size_t b;
  bool operator==(const EdgeKey& other) const {
    return a == other.a && b == other.b;
  }
};

template <typename Coord>
struct EdgeHash {
  std::size_t operator()(const EdgeKey<Coord>& edge) const {
    return edge.a ^ (edge.b + 0x9e3779b9 + (edge.a << 6) + (edge.a >> 2));
  }
};

// The boundary edges of the filled faces: a shared edge fixes the winding
// difference between its two faces, so the winding is propagated across the
// arrangement instead of being sampled arbitrarily close to an edge, which
// would make tiny positive faces depend on a numeric epsilon.
template <typename Coord>
inline std::vector<EdgeKey<Coord>> PositiveFaceEdges(
    const std::vector<PointOf<Coord>>& nodes,
    const std::unordered_map<EdgeKey<Coord>, int, EdgeHash<Coord>>& weights) {
  std::vector<EdgeKey<Coord>> halves;
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
      return AngleBefore<Coord>(
          nodes[halves[a].b] - nodes[node], nodes[halves[b].b] - nodes[node]);
    });
    for (std::size_t index = 0; index < edges.size(); ++index) {
      next[edges[index] ^ 1] = edges[(index + edges.size() - 1) % edges.size()];
    }
  }
  std::vector<std::size_t> components(nodes.size(), BoundsIndex<Coord>::kMissing);
  std::vector<std::size_t> seeds;
  for (std::size_t first = 0; first < nodes.size(); ++first) {
    if (outgoing[first].empty()
        || components[first] != BoundsIndex<Coord>::kMissing) {
      continue;
    }
    const auto component = seeds.size();
    seeds.push_back(first);
    std::vector<std::size_t> pending{first};
    components[first] = component;
    while (!pending.empty()) {
      const auto node = pending.back();
      pending.pop_back();
      for (const auto edge : outgoing[node]) {
        const auto other = halves[edge].b;
        if (components[other] != BoundsIndex<Coord>::kMissing) continue;
        components[other] = component;
        pending.push_back(other);
      }
    }
  }
  std::vector<std::vector<std::size_t>> faces;
  std::vector<std::size_t> face_of(halves.size(), BoundsIndex<Coord>::kMissing);
  std::vector<std::size_t> outer_faces(seeds.size(), BoundsIndex<Coord>::kMissing);
  std::vector<long double> outer_areas(
      seeds.size(), std::numeric_limits<long double>::infinity());
  for (std::size_t first = 0; first < halves.size(); ++first) {
    if (face_of[first] != BoundsIndex<Coord>::kMissing) continue;
    const auto face = faces.size();
    faces.emplace_back();
    PathOf<Coord> path;
    auto edge = first;
    do {
      face_of[edge] = face;
      faces.back().push_back(edge);
      path.push_back(nodes[halves[edge].a]);
      edge = next[edge];
    } while (edge != first);
    const auto component = components[halves[first].a];
    const auto area = SignedArea<Coord>(path);
    if (area < outer_areas[component]) {
      outer_areas[component] = area;
      outer_faces[component] = face;
    }
  }
  std::vector<BoundsOf<Coord>> edge_bounds;
  long double ray_right = -std::numeric_limits<long double>::infinity();
  for (std::size_t edge = 0; edge < halves.size(); edge += 2) {
    const auto bounds = clipper::GetBounds(
        PathOf<Coord>{nodes[halves[edge].a], nodes[halves[edge].b]});
    edge_bounds.push_back(bounds);
    ray_right = std::max(ray_right, static_cast<long double>(bounds.right));
  }
  const BoundsIndex<Coord> edge_index(edge_bounds);
  std::vector<int> windings(
      faces.size(), std::numeric_limits<int>::min());
  for (std::size_t component = 0; component < seeds.size(); ++component) {
    const auto& point = nodes[seeds[component]];
    int baseline = 0;
    // Components do not touch, so this vertex is strictly off every other
    // component's boundary; their contributions establish the enclosing fill.
    edge_index.Query(
        BoundsOf<Coord>(point.x, point.y, static_cast<Coord>(ray_right), point.y),
        false, [&](std::size_t candidate) {
          const auto edge = 2 * candidate;
          if (components[halves[edge].a] == component) return;
          const auto& a = nodes[halves[edge].a];
          const auto& b = nodes[halves[edge].b];
          const auto cross = Cross<Coord>(b - a, point - a);
          if (a.y <= point.y && b.y > point.y && cross > 0) {
            baseline += winding_deltas[edge];
          } else if (a.y > point.y && b.y <= point.y && cross < 0) {
            baseline -= winding_deltas[edge];
          }
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
  std::vector<EdgeKey<Coord>> boundary;
  for (std::size_t edge = 0; edge < halves.size(); edge += 2) {
    const bool left = windings[face_of[edge]] > 0;
    const bool right = windings[face_of[edge ^ 1]] > 0;
    if (left != right) {
      boundary.push_back(halves[left ? edge : edge ^ 1]);
    }
  }
  return boundary;
}

// Trace the filled faces of the arrangement. All paths must be noded and
// oriented with the represented area on one side (shells positive, holes
// negative). At a contact the walk follows the next clockwise edge from the
// incoming reverse edge, so it keeps to one face: two lobes joined at a vertex
// become two rings, and a hole that pinches the region splits it into the
// lobes that meet only along their boundaries.
template <typename Coord>
inline std::vector<SimpleRing<Coord>> TraceFilledFaces(
    const std::vector<PathOf<Coord>>& paths) {
  std::vector<PointOf<Coord>> nodes;
  std::unordered_map<PointOf<Coord>, std::size_t, PointHash<Coord>> node_ids;
  std::unordered_map<EdgeKey<Coord>, int, EdgeHash<Coord>> weights;
  const auto node_for = [&](const PointOf<Coord>& point) {
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
  const auto edges = PositiveFaceEdges<Coord>(nodes, weights);
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
    next[index] = BoundsIndex<Coord>::kMissing;
    for (const auto candidate : outgoing[edge.b]) {
      const auto direction = nodes[edges[candidate].b] - nodes[edge.b];
      const auto angle = std::atan2(
          Cross<Coord>(reverse, direction), Dot<Coord>(reverse, direction));
      const auto clockwise = angle <= 0 ? -angle : full_turn - angle;
      if (clockwise < best) {
        next[index] = candidate;
        best = clockwise;
      }
    }
  }
  std::vector<SimpleRing<Coord>> rings;
  std::vector<bool> visited(edges.size(), false);
  for (std::size_t first = 0; first < edges.size(); ++first) {
    if (visited[first]) continue;
    PathOf<Coord> path;
    auto edge = first;
    while (edge != BoundsIndex<Coord>::kMissing && !visited[edge]) {
      visited[edge] = true;
      path.push_back(nodes[edges[edge].a]);
      edge = next[edge];
    }
    if (edge != first) {
      throw std::runtime_error(
          "canonical_face_did_not_close:paths=" + std::to_string(paths.size()));
    }
    SplitTouchingRing<Coord>(path, rings);
  }
  return rings;
}

// Filled faces from already noded linework.
template <typename Coord>
inline void BuildFacesFromNoded(const std::vector<PathOf<Coord>>& noded,
                                CanonicalNode<Coord>& output) {
  BuildRingTree<Coord>(TraceFilledFaces<Coord>(noded), output);
}

// The output rule: the filled region of the linework, expressed as faces that
// meet only along their boundaries. It covers every boundary form the engine
// can meet - a ring touching itself, a vertex on a non-adjacent edge, a
// collinear overlap, a true crossing, a hole that touches its shell, and a
// hole that pinches the region in two.
template <typename Coord>
inline void BuildFilledFaces(const std::vector<PathOf<Coord>>& paths,
                             CanonicalNode<Coord>& output) {
  BuildFacesFromNoded<Coord>(NodeToGrid<Coord>(paths), output);
}

}  // namespace lumina::canonical

#endif  // LUMINA_SVG_CORE_CANONICAL_BOUNDARY_H
