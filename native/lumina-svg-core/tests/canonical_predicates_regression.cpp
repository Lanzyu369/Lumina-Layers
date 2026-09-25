// Release-build regression for the integer canonical-boundary predicates.
// This file includes the production header directly; it must never copy the
// predicate implementations into a test-only substitute.
#include "canonical_boundary.h"

#include <cstdint>
#include <iostream>
#include <string>

namespace {

using namespace lumina::canonical;
using Point = PointOf<int64_t>;
using Path = PathOf<int64_t>;

bool Require(bool condition, const char* label) {
  if (condition) return true;
  std::cerr << "FAIL " << label << '\n';
  return false;
}

}  // namespace

int main() {
  constexpr int64_t n = 1'000'000'000'000LL;
  const Point a{n, n + 1};
  const Point b{n - 1, n};
  const Path outer{
      Point{int64_t{0}, int64_t{0}},
      Point{n, n + 1},
      Point{int64_t{0}, n + 1},
  };
  const Point inside{n - 1, n};
  const Point boundary{int64_t{0}, int64_t{0}};
  const Point outside{n + 1, n};
  const Path reversed{outer.rbegin(), outer.rend()};
  const Point same_direction_near{int64_t{1}, int64_t{0}};
  const Point same_direction_far{int64_t{2}, int64_t{0}};

  bool ok = true;
  ok &= Require(AngleBefore<int64_t>(a, b), "angle-before");
  ok &= Require(!AngleBefore<int64_t>(b, a), "angle-reverse");
  ok &= Require(
      PointLocation<int64_t>(inside, outer) == 1, "point-inside");
  ok &= Require(
      PointLocation<int64_t>(inside, reversed) == 1, "point-reversed-ring");
  ok &= Require(
      PointLocation<int64_t>(boundary, outer) == 0, "point-boundary");
  ok &= Require(
      PointLocation<int64_t>(outside, outer) == -1, "point-outside");
  ok &= Require(
      AngleBefore<int64_t>(same_direction_near, same_direction_far),
      "collinear-distance");
  ok &= Require(
      !AngleBefore<int64_t>(same_direction_far, same_direction_near),
      "collinear-distance-reverse");

  const PointOf<long double> float_a{0.0L, 0.0L};
  const PointOf<long double> float_b{1.0L, 0.0L};
  const PointOf<long double> float_c{0.0L, 1.0L};
  const PathOf<long double> float_triangle{float_a, float_b, float_c};
  ok &= Require(
      PointLocation<long double>(PointOf<long double>{0.2L, 0.2L},
                                 float_triangle) == 1,
      "long-double-inside");
  ok &= Require(
      AngleBefore<long double>(float_b, float_c),
      "long-double-angle");

  std::cout << "canonical_predicates_regression "
            << (ok ? "PASS" : "FAIL") << '\n';
  return ok ? 0 : 1;
}
