#ifndef LUMINA_SVG_CORE_CLIPPER_SAFETY_H
#define LUMINA_SVG_CORE_CLIPPER_SAFETY_H

#include "complexity_budget.h"

#include <clipper2/clipper.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cmath>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <utility>
#include <vector>

namespace lumina_svg_core {

namespace clipper_safety_detail {

inline constexpr size_t MAX_CANDIDATES_PER_OPERATION = 2'000'000;
inline constexpr size_t DIRECT_CANDIDATE_THRESHOLD = 4'096;

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

    void include(const SegmentBounds& other)
    {
        min_x = std::min(min_x, other.min_x);
        min_y = std::min(min_y, other.min_y);
        max_x = std::max(max_x, other.max_x);
        max_y = std::max(max_y, other.max_y);
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

inline bool segmentsIntersect(const IndexedSegment& first,
                              const IndexedSegment& second)
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

inline long double squaredPointSegmentDistance(
    const Clipper2Lib::Point64& point,
    const IndexedSegment& segment)
{
    const long double dx = static_cast<long double>(segment.second.x)
        - static_cast<long double>(segment.first.x);
    const long double dy = static_cast<long double>(segment.second.y)
        - static_cast<long double>(segment.first.y);
    const long double lengthSquared = dx * dx + dy * dy;
    if(!(lengthSquared > 0.0L))
        return std::numeric_limits<long double>::infinity();
    const long double fromStartX = static_cast<long double>(point.x)
        - static_cast<long double>(segment.first.x);
    const long double fromStartY = static_cast<long double>(point.y)
        - static_cast<long double>(segment.first.y);
    const long double projection = std::clamp(
        (fromStartX * dx + fromStartY * dy) / lengthSquared,
        0.0L, 1.0L);
    const long double offsetX = fromStartX - projection * dx;
    const long double offsetY = fromStartY - projection * dy;
    return offsetX * offsetX + offsetY * offsetY;
}

inline bool segmentsWithinDistance(const IndexedSegment& first,
                                   const IndexedSegment& second,
                                   long double distanceSquared)
{
    if(segmentsIntersect(first, second))
        return true;
    return std::min({
        squaredPointSegmentDistance(first.first, second),
        squaredPointSegmentDistance(first.second, second),
        squaredPointSegmentDistance(second.first, first),
        squaredPointSegmentDistance(second.second, first),
    }) <= distanceSquared;
}

inline int64_t saturatingSubtract(int64_t value, int64_t distance)
{
    return value < std::numeric_limits<int64_t>::min() + distance
        ? std::numeric_limits<int64_t>::min() : value - distance;
}

inline int64_t saturatingAdd(int64_t value, int64_t distance)
{
    return value > std::numeric_limits<int64_t>::max() - distance
        ? std::numeric_limits<int64_t>::max() : value + distance;
}

inline SegmentBounds expandedBounds(const SegmentBounds& bounds,
                                    int64_t distance)
{
    return {
        saturatingSubtract(bounds.min_x, distance),
        saturatingSubtract(bounds.min_y, distance),
        saturatingAdd(bounds.max_x, distance),
        saturatingAdd(bounds.max_y, distance),
    };
}

inline SegmentBounds segmentBounds(const Clipper2Lib::Point64& first,
                                   const Clipper2Lib::Point64& second)
{
    return {
        std::min(first.x, second.x),
        std::min(first.y, second.y),
        std::max(first.x, second.x),
        std::max(first.y, second.y),
    };
}

inline bool adjacentEdges(const IndexedSegment& first,
                          const IndexedSegment& second)
{
    if(first.path_id != second.path_id)
        return false;
    const size_t difference = first.edge_index > second.edge_index
        ? first.edge_index - second.edge_index
        : second.edge_index - first.edge_index;
    return difference == 1
        || (first.closed && difference + 1 == first.edge_count);
}

class BoundedIntersectionIndex {
public:
    explicit BoundedIntersectionIndex(
        std::vector<IndexedSegment> segments,
        ComplexityBudget& complexityBudget,
        bool crossOperandsOnly = false)
        : m_segments(std::move(segments)),
          m_complexityBudget(complexityBudget),
          m_crossOperandsOnly(crossOperandsOnly)
    {
        m_indices.resize(m_segments.size());
        std::iota(m_indices.begin(), m_indices.end(), size_t{0});
        if(!m_indices.empty())
            buildNode(0, m_indices.size());
    }

    void requireBoundedCandidates()
    {
        for(size_t index = 0; index < m_segments.size(); ++index)
            queryNode(0, index, m_segments[index].bounds);
        m_complexityBudget.consumeClipperIntersectionCandidates(
            m_candidateCount);
    }

    bool hasNonAdjacentSegmentsWithinDistance(int64_t distance)
    {
        if(distance < 0)
            throw std::invalid_argument("negative proximity distance");
        const long double distanceSquared =
            static_cast<long double>(distance) * distance;
        size_t queryWork = 0;
        size_t candidateCount = 0;
        for(size_t index = 0; index < m_segments.size(); ++index) {
            if(queryNearbyNode(
                    0, index,
                    expandedBounds(m_segments[index].bounds, distance),
                    distanceSquared, queryWork, candidateCount)) {
                m_complexityBudget.consumeClipperIntersectionCandidates(
                    candidateCount);
                return true;
            }
        }
        m_complexityBudget.consumeClipperIntersectionCandidates(
            candidateCount);
        return false;
    }

private:
    static constexpr size_t LEAF_SIZE = 12;
    static constexpr size_t MAX_INDEX_QUERY_WORK = 8'000'000;

    struct Node {
        SegmentBounds bounds;
        size_t begin{0};
        size_t end{0};
        size_t left{0};
        size_t right{0};
        bool leaf{false};
    };

    size_t buildNode(size_t begin, size_t end)
    {
        const size_t nodeIndex = m_nodes.size();
        m_nodes.emplace_back();
        SegmentBounds bounds = m_segments[m_indices[begin]].bounds;
        for(size_t offset = begin + 1; offset < end; ++offset)
            bounds.include(m_segments[m_indices[offset]].bounds);
        m_nodes[nodeIndex].bounds = bounds;
        m_nodes[nodeIndex].begin = begin;
        m_nodes[nodeIndex].end = end;
        if(end - begin <= LEAF_SIZE) {
            m_nodes[nodeIndex].leaf = true;
            return nodeIndex;
        }

        const long double width = static_cast<long double>(bounds.max_x)
            - static_cast<long double>(bounds.min_x);
        const long double height = static_cast<long double>(bounds.max_y)
            - static_cast<long double>(bounds.min_y);
        const bool splitX = width >= height;
        const size_t middle = begin + (end - begin) / 2;
        std::nth_element(
            m_indices.begin() + static_cast<std::ptrdiff_t>(begin),
            m_indices.begin() + static_cast<std::ptrdiff_t>(middle),
            m_indices.begin() + static_cast<std::ptrdiff_t>(end),
            [&](size_t left, size_t right) {
                const auto& leftBounds = m_segments[left].bounds;
                const auto& rightBounds = m_segments[right].bounds;
                const long double leftCenter = splitX
                    ? static_cast<long double>(leftBounds.min_x)
                        + static_cast<long double>(leftBounds.max_x)
                    : static_cast<long double>(leftBounds.min_y)
                        + static_cast<long double>(leftBounds.max_y);
                const long double rightCenter = splitX
                    ? static_cast<long double>(rightBounds.min_x)
                        + static_cast<long double>(rightBounds.max_x)
                    : static_cast<long double>(rightBounds.min_y)
                        + static_cast<long double>(rightBounds.max_y);
                return leftCenter == rightCenter
                    ? left < right : leftCenter < rightCenter;
            });
        const size_t left = buildNode(begin, middle);
        const size_t right = buildNode(middle, end);
        m_nodes[nodeIndex].left = left;
        m_nodes[nodeIndex].right = right;
        return nodeIndex;
    }

    void queryNode(size_t nodeIndex, size_t segmentIndex,
                   const SegmentBounds& query)
    {
        if(++m_queryWork > MAX_INDEX_QUERY_WORK)
            throw ComplexityLimitError("clipper_index_query_work");
        const auto& node = m_nodes[nodeIndex];
        if(!node.bounds.intersects(query))
            return;
        if(node.leaf) {
            for(size_t offset = node.begin; offset < node.end; ++offset) {
                const size_t candidateIndex = m_indices[offset];
                if(candidateIndex <= segmentIndex)
                    continue;
                const auto& segment = m_segments[segmentIndex];
                const auto& candidate = m_segments[candidateIndex];
                if((m_crossOperandsOnly
                        && segment.operand_id == candidate.operand_id)
                    || adjacentEdges(segment, candidate)
                    || !candidate.bounds.intersects(query)
                    || !segmentsIntersect(segment, candidate))
                    continue;
                if(++m_candidateCount
                        > clipper_safety_detail::MAX_CANDIDATES_PER_OPERATION)
                    throw ComplexityLimitError(
                        "clipper_candidates_per_operation:"
                        + std::to_string(m_candidateCount));
            }
            return;
        }
        queryNode(node.left, segmentIndex, query);
        queryNode(node.right, segmentIndex, query);
    }

    bool queryNearbyNode(size_t nodeIndex, size_t segmentIndex,
                         const SegmentBounds& query,
                         long double distanceSquared,
                         size_t& queryWork,
                         size_t& candidateCount) const
    {
        if(++queryWork > MAX_INDEX_QUERY_WORK)
            throw ComplexityLimitError("clipper_index_query_work");
        const auto& node = m_nodes[nodeIndex];
        if(!node.bounds.intersects(query))
            return false;
        if(node.leaf) {
            for(size_t offset = node.begin; offset < node.end; ++offset) {
                const size_t candidateIndex = m_indices[offset];
                if(candidateIndex <= segmentIndex)
                    continue;
                const auto& segment = m_segments[segmentIndex];
                const auto& candidate = m_segments[candidateIndex];
                if(adjacentEdges(segment, candidate)
                        || !candidate.bounds.intersects(query))
                    continue;
                if(++candidateCount > MAX_CANDIDATES_PER_OPERATION)
                    throw ComplexityLimitError(
                        "clipper_proximity_candidates");
                if(segmentsWithinDistance(
                        segment, candidate, distanceSquared))
                    return true;
            }
            return false;
        }
        return queryNearbyNode(
                   node.left, segmentIndex, query, distanceSquared,
                   queryWork, candidateCount)
            || queryNearbyNode(
                   node.right, segmentIndex, query, distanceSquared,
                   queryWork, candidateCount);
    }

    std::vector<IndexedSegment> m_segments;
    std::vector<size_t> m_indices;
    std::vector<Node> m_nodes;
    ComplexityBudget& m_complexityBudget;
    bool m_crossOperandsOnly{false};
    size_t m_queryWork{0};
    size_t m_candidateCount{0};
};

inline void appendSegments(const Clipper2Lib::Paths64& paths,
                           bool closed, size_t operandId,
                           size_t& nextPathId,
                           std::vector<IndexedSegment>& segments)
{
    for(const auto& path : paths) {
        if(path.size() < 2) {
            ++nextPathId;
            continue;
        }
        const size_t edgeCount = closed ? path.size() : path.size() - 1;
        for(size_t edgeIndex = 0; edgeIndex < edgeCount; ++edgeIndex) {
            const auto& first = path[edgeIndex];
            const auto& second = path[(edgeIndex + 1) % path.size()];
            if(first == second)
                continue;
            segments.push_back({
                segmentBounds(first, second),
                first,
                second,
                nextPathId,
                operandId,
                edgeIndex,
                edgeCount,
                closed,
            });
        }
        ++nextPathId;
    }
}

inline size_t segmentCount(const Clipper2Lib::Paths64& paths, bool closed)
{
    size_t count = 0;
    for(const auto& path : paths) {
        if(path.size() < 2)
            continue;
        count = checkedSizeSum(count, closed ? path.size() : path.size() - 1);
    }
    return count;
}

inline bool isConvexClosedPath(const Clipper2Lib::Path64& path)
{
    if(path.size() < 3)
        return false;

    Clipper2Lib::Path64 corners;
    corners.reserve(path.size());
    int orientation = 0;
    for(size_t index = 0; index < path.size(); ++index) {
        const auto& previous = path[
            (index + path.size() - 1) % path.size()];
        const auto& current = path[index];
        const auto& next = path[(index + 1) % path.size()];
        const int cross = Clipper2Lib::CrossProductSign(
            previous, current, next);
        if(cross == 0)
            continue;
        if(orientation != 0 && orientation != cross)
            return false;
        orientation = cross;
        corners.push_back(current);
    }
    if(corners.size() < 3)
        return false;

    auto sorted = path;
    std::sort(sorted.begin(), sorted.end(), [](const auto& left,
                                                const auto& right) {
        return left.x == right.x ? left.y < right.y : left.x < right.x;
    });
    sorted.erase(std::unique(sorted.begin(), sorted.end()), sorted.end());
    if(sorted.size() < 3)
        return false;
    Clipper2Lib::Path64 hull;
    hull.reserve(checkedSizeProduct(sorted.size(), size_t{2}));
    for(const auto& point : sorted) {
        while(hull.size() >= 2
                && Clipper2Lib::CrossProductSign(
                    hull[hull.size() - 2], hull.back(), point) <= 0)
            hull.pop_back();
        hull.push_back(point);
    }
    const size_t lowerSize = hull.size();
    for(size_t index = sorted.size() - 1; index > 0; --index) {
        const auto& point = sorted[index - 1];
        while(hull.size() > lowerSize
                && Clipper2Lib::CrossProductSign(
                    hull[hull.size() - 2], hull.back(), point) <= 0)
            hull.pop_back();
        hull.push_back(point);
    }
    if(!hull.empty())
        hull.pop_back();
    if(hull.size() != corners.size())
        return false;

    const auto start = std::find(hull.begin(), hull.end(), corners.front());
    if(start == hull.end())
        return false;
    const size_t startIndex = static_cast<size_t>(start - hull.begin());
    bool forward = true;
    bool reverse = true;
    for(size_t index = 0; index < corners.size(); ++index) {
        forward = forward
            && corners[index] == hull[(startIndex + index) % hull.size()];
        reverse = reverse
            && corners[index] == hull[
                (startIndex + hull.size() - index) % hull.size()];
    }
    return forward || reverse;
}

inline bool isSingleConvexClosedPath(const Clipper2Lib::Paths64& paths)
{
    return paths.size() == 1 && isConvexClosedPath(paths.front());
}

inline size_t allPairCount(size_t count)
{
    if(count < 2)
        return 0;
    return count % 2 == 0
        ? checkedSizeProduct(count / 2, count - 1)
        : checkedSizeProduct(count, (count - 1) / 2);
}

inline void requireBoundedDirectCandidates(
    size_t candidateCount, ComplexityBudget& complexityBudget)
{
    if(candidateCount > MAX_CANDIDATES_PER_OPERATION)
        throw ComplexityLimitError("clipper_candidates_per_operation");
    complexityBudget.consumeClipperIntersectionCandidates(candidateCount);
}

} // namespace clipper_safety_detail

inline void requireBoundedClipperIntersections(
    const Clipper2Lib::Paths64& paths,
    ComplexityBudget& complexityBudget,
    bool closed = true)
{
    const size_t count =
        clipper_safety_detail::segmentCount(paths, closed);
    complexityBudget.ensureClipperIndexSegmentCapacity(count);
    if(closed
            && clipper_safety_detail::isSingleConvexClosedPath(paths)) {
        clipper_safety_detail::requireBoundedDirectCandidates(
            count, complexityBudget);
        return;
    }
    // A direct all-pairs upper bound is cheap only for small inputs. Charging
    // that pessimistic bound for every medium-sized paint can exhaust the
    // document budget even when the segment boxes are disjoint. Larger
    // inputs therefore use the bounded index and charge actual box-overlap
    // candidates before Clipper receives them.
    const size_t directCandidates =
        clipper_safety_detail::allPairCount(count);
    if(directCandidates
            <= clipper_safety_detail::DIRECT_CANDIDATE_THRESHOLD) {
        clipper_safety_detail::requireBoundedDirectCandidates(
            directCandidates, complexityBudget);
        return;
    }
    std::vector<clipper_safety_detail::IndexedSegment> segments;
    segments.reserve(count);
    size_t nextPathId = 0;
    clipper_safety_detail::appendSegments(
        paths, closed, 0, nextPathId, segments);
    clipper_safety_detail::BoundedIntersectionIndex index(
        std::move(segments), complexityBudget);
    index.requireBoundedCandidates();
}

inline void requireBoundedClipperIntersections(
    const Clipper2Lib::Paths64& first,
    const Clipper2Lib::Paths64& second,
    ComplexityBudget& complexityBudget)
{
    const size_t firstCount =
        clipper_safety_detail::segmentCount(first, true);
    const size_t secondCount =
        clipper_safety_detail::segmentCount(second, true);
    const size_t count = checkedSizeSum(firstCount, secondCount);
    complexityBudget.ensureClipperIndexSegmentCapacity(count);
    if(clipper_safety_detail::isSingleConvexClosedPath(first)
            && clipper_safety_detail::isSingleConvexClosedPath(second)) {
        // Two convex polygon boundaries have only linear crossing complexity.
        // Charge their combined edge count without turning
        // a proven-safe large convex pair into an all-pairs rejection.
        clipper_safety_detail::requireBoundedDirectCandidates(
            count, complexityBudget);
        return;
    }
    const size_t directCandidates = checkedSizeProduct(
        firstCount, secondCount);
    if(directCandidates
            <= clipper_safety_detail::DIRECT_CANDIDATE_THRESHOLD) {
        clipper_safety_detail::requireBoundedDirectCandidates(
            directCandidates, complexityBudget);
        return;
    }
    std::vector<clipper_safety_detail::IndexedSegment> segments;
    segments.reserve(count);
    size_t nextPathId = 0;
    clipper_safety_detail::appendSegments(
        first, true, 0, nextPathId, segments);
    clipper_safety_detail::appendSegments(
        second, true, 1, nextPathId, segments);
    clipper_safety_detail::BoundedIntersectionIndex index(
        std::move(segments), complexityBudget, true);
    index.requireBoundedCandidates();
}

inline void requireBoundedClipperIntersectionsAcrossGroups(
    const std::vector<const Clipper2Lib::Paths64*>& groups,
    ComplexityBudget& complexityBudget)
{
    size_t totalSegments = 0;
    size_t directCandidates = 0;
    for(const auto* group : groups) {
        if(group == nullptr)
            throw std::logic_error("missing_clipper_path_group");
        const size_t count =
            clipper_safety_detail::segmentCount(*group, true);
        directCandidates = checkedSizeSum(
            directCandidates,
            checkedSizeProduct(totalSegments, count));
        totalSegments = checkedSizeSum(totalSegments, count);
    }
    complexityBudget.ensureClipperIndexSegmentCapacity(totalSegments);
    if(directCandidates
            <= clipper_safety_detail::DIRECT_CANDIDATE_THRESHOLD) {
        clipper_safety_detail::requireBoundedDirectCandidates(
            directCandidates, complexityBudget);
        return;
    }

    std::vector<clipper_safety_detail::IndexedSegment> segments;
    segments.reserve(totalSegments);
    size_t nextPathId = 0;
    for(size_t index = 0; index < groups.size(); ++index) {
        clipper_safety_detail::appendSegments(
            *groups[index], true, index, nextPathId, segments);
    }
    clipper_safety_detail::BoundedIntersectionIndex index(
        std::move(segments), complexityBudget, true);
    index.requireBoundedCandidates();
}

inline void requireBoundedClipperOffset(
    const Clipper2Lib::Paths64& paths,
    ComplexityBudget& complexityBudget,
    bool closed = true)
{
    const size_t count =
        clipper_safety_detail::segmentCount(paths, closed);
    complexityBudget.ensureClipperIndexSegmentCapacity(count);
    if(closed
            && clipper_safety_detail::isSingleConvexClosedPath(paths)) {
        clipper_safety_detail::requireBoundedDirectCandidates(
            count, complexityBudget);
        return;
    }
    // Offsetting can make two previously disjoint edges meet, so a spatial
    // intersection index over the input is not a safe upper bound. Limit and
    // charge the complete pair set before Clipper allocates the offset graph.
    clipper_safety_detail::requireBoundedDirectCandidates(
        clipper_safety_detail::allPairCount(count), complexityBudget);
}

inline bool hasNonAdjacentSegmentsWithinDistance(
    const Clipper2Lib::Paths64& paths,
    int64_t distance,
    ComplexityBudget& complexityBudget)
{
    const size_t count =
        clipper_safety_detail::segmentCount(paths, true);
    complexityBudget.ensureClipperIndexSegmentCapacity(count);
    if(count < 3)
        return false;
    std::vector<clipper_safety_detail::IndexedSegment> segments;
    segments.reserve(count);
    size_t nextPathId = 0;
    clipper_safety_detail::appendSegments(
        paths, true, 0, nextPathId, segments);
    clipper_safety_detail::BoundedIntersectionIndex index(
        std::move(segments), complexityBudget);
    return index.hasNonAdjacentSegmentsWithinDistance(distance);
}

} // namespace lumina_svg_core

#endif // LUMINA_SVG_CORE_CLIPPER_SAFETY_H
