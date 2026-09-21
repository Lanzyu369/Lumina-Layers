#ifndef LUMINA_SVG_CORE_CLIPPER_SAFETY_H
#define LUMINA_SVG_CORE_CLIPPER_SAFETY_H

#include "complexity_budget.h"
#include <clipper2/clipper.h>
#include <algorithm>
#include <cmath>
#include <utility>

namespace lumina_svg_core {

// Count actual input points with the shared size_t overflow check. This helper
// is used for diagnostics and numeric safety; it is not an admission policy.
inline size_t clipperPathPointCount(const Clipper2Lib::Paths64& paths)
{
    size_t count = 0;
    for(const auto& path : paths)
        count = checkedSizeSum(count, path.size());
    return count;
}

struct SegmentBounds {
    int64_t min_x{0};
    int64_t min_y{0};
    int64_t max_x{0};
    int64_t max_y{0};

    bool intersects(const SegmentBounds& other) const
    {
        return min_x <= other.max_x && max_x >= other.min_x
            && min_y <= other.max_y && max_y >= other.min_y;
    }
};

struct IndexedSegment {
    SegmentBounds bounds;
    Clipper2Lib::Point64 first;
    Clipper2Lib::Point64 second;
    size_t path_id{0};
    size_t operand_id{0};
    size_t edge_index{0};
    size_t edge_count{0};
    bool closed{true};
};

inline bool segmentsIntersect(
    const IndexedSegment& first, const IndexedSegment& second)
{
    const int firstStart = Clipper2Lib::CrossProductSign(
        first.first, first.second, second.first);
    const int firstEnd = Clipper2Lib::CrossProductSign(
        first.first, first.second, second.second);
    const int secondStart = Clipper2Lib::CrossProductSign(
        second.first, second.second, first.first);
    const int secondEnd = Clipper2Lib::CrossProductSign(
        second.first, second.second, first.second);
    const auto straddles = [](int left, int right) {
        return left == 0 || right == 0 || left != right;
    };
    return straddles(firstStart, firstEnd)
        && straddles(secondStart, secondEnd);
}

inline bool segmentsHavePositiveLengthCollinearOverlap(
    const IndexedSegment& first, const IndexedSegment& second)
{
    if(Clipper2Lib::CrossProductSign(
            first.first, first.second, second.first) != 0
            || Clipper2Lib::CrossProductSign(
                first.first, first.second, second.second) != 0)
        return false;
    const long double dx = static_cast<long double>(first.second.x)
        - static_cast<long double>(first.first.x);
    const long double dy = static_cast<long double>(first.second.y)
        - static_cast<long double>(first.first.y);
    const auto extent = [&](bool use_x) {
        const int64_t first_start = use_x ? first.first.x : first.first.y;
        const int64_t first_end = use_x ? first.second.x : first.second.y;
        const int64_t second_start = use_x ? second.first.x : second.first.y;
        const int64_t second_end = use_x ? second.second.x : second.second.y;
        return std::pair<int64_t, int64_t>{
            std::max(std::min(first_start, first_end),
                     std::min(second_start, second_end)),
            std::min(std::max(first_start, first_end),
                     std::max(second_start, second_end)),
        };
    };
    const auto range = extent(std::abs(dx) >= std::abs(dy));
    return range.first < range.second;
}

inline long double squaredPointSegmentDistance(
    const Clipper2Lib::Point64& point, const IndexedSegment& segment)
{
    const long double dx = static_cast<long double>(segment.second.x)
        - static_cast<long double>(segment.first.x);
    const long double dy = static_cast<long double>(segment.second.y)
        - static_cast<long double>(segment.first.y);
    const long double length_squared = dx * dx + dy * dy;
    if(!(length_squared > 0.0L))
        return std::numeric_limits<long double>::infinity();
    const long double from_x = static_cast<long double>(point.x)
        - static_cast<long double>(segment.first.x);
    const long double from_y = static_cast<long double>(point.y)
        - static_cast<long double>(segment.first.y);
    const long double projection = std::clamp(
        (from_x * dx + from_y * dy) / length_squared, 0.0L, 1.0L);
    const long double offset_x = from_x - projection * dx;
    const long double offset_y = from_y - projection * dy;
    return offset_x * offset_x + offset_y * offset_y;
}

inline bool segmentsWithinDistance(
    const IndexedSegment& first, const IndexedSegment& second,
    long double distance_squared)
{
    if(segmentsIntersect(first, second))
        return true;
    return std::min({
        squaredPointSegmentDistance(first.first, second),
        squaredPointSegmentDistance(first.second, second),
        squaredPointSegmentDistance(second.first, first),
        squaredPointSegmentDistance(second.second, first),
    }) <= distance_squared;
}

inline void validateClipperOffsetRange(
    double offsetDistance, double miterLimit)
{
    const double extension = std::abs(offsetDistance)
        * 2.0 * std::max(2.0, std::abs(miterLimit));
    // INT64_MAX rounds to 2^63 when converted to double. Keep the explicit
    // representability check before Clipper receives the integer distance.
    if(!std::isfinite(extension) || extension >= 0x1p63)
        throw ComplexityLimitError("clipper_offset_range");
}

} // namespace lumina_svg_core

#endif // LUMINA_SVG_CORE_CLIPPER_SAFETY_H
