#include "lumina_svg_core/geometry_kernel.h"

#include "lumina_svg_core/paint_command.h"
#include "lumina_svg_core/stroke_expander.h"

#include <clipper2/clipper.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <numeric>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace lumina_svg_core {
namespace {

using Clipper2Lib::ClipType;
using Clipper2Lib::Clipper64;
using Clipper2Lib::FillRule;
using Clipper2Lib::Path64;
using Clipper2Lib::Paths64;
using Clipper2Lib::Point64;
using Clipper2Lib::PolyPath64;
using Clipper2Lib::PolyTree64;

struct PointD {
    double x{0};
    double y{0};
};

struct SourceSegment {
    PointD start;
    PointD end;
    size_t contour_id{0};
    size_t edge_index{0};
    size_t edge_count{0};
    int64_t operation_id{0};
    double input_precision_error_source{0};
    double approximation_error_source{0};
};

struct TopologyTrace {
    std::vector<SourceSegment> segments;
    size_t next_contour_id{0};
};

struct PhysicalDomain {
    double bbox_x{0};
    double bbox_y{0};
    double source_to_mm{0};
    double grid_step_mm{0};
    double flatten_budget_mm{0};
    double stroke_quantization_budget_mm{0};
    TopologyTrace* topology_trace{nullptr};
};

struct GridBounds {
    int64_t min_x{0};
    int64_t min_y{0};
    int64_t max_x{0};
    int64_t max_y{0};
    bool valid{false};

    void include(const Point64& point)
    {
        if(!valid) {
            min_x = max_x = point.x;
            min_y = max_y = point.y;
            valid = true;
            return;
        }
        min_x = std::min(min_x, point.x);
        min_y = std::min(min_y, point.y);
        max_x = std::max(max_x, point.x);
        max_y = std::max(max_y, point.y);
    }

    void include(const GridBounds& other)
    {
        if(!other.valid)
            return;
        include(Point64(other.min_x, other.min_y));
        include(Point64(other.max_x, other.max_y));
    }

    bool intersects(const GridBounds& other) const
    {
        return valid && other.valid
            && min_x <= other.max_x && max_x >= other.min_x
            && min_y <= other.max_y && max_y >= other.min_y;
    }
};

struct PaintGeometry {
    Paths64 paths;
    GridBounds bounds;
    std::array<uint8_t, 4> rgba{{0, 0, 0, 0}};
    int32_t draw_index{-1};
    int32_t source_index{-1};
    SourceKind source_kind{SourceKind::Fill};
};

GridBounds pathsBounds(const Paths64& paths)
{
    GridBounds bounds;
    for(const auto& path : paths) {
        for(const auto& point : path)
            bounds.include(point);
    }
    return bounds;
}

class PackedBoundsIndex {
public:
    explicit PackedBoundsIndex(const std::vector<PaintGeometry>& paints)
        : m_paints(paints)
    {
        m_indices.reserve(paints.size());
        for(size_t index = 0; index < paints.size(); ++index) {
            if(paints[index].bounds.valid)
                m_indices.push_back(index);
        }
        if(!m_indices.empty())
            buildNode(0, m_indices.size());
    }

    std::vector<size_t> laterOverlaps(
        size_t paintIndex,
        size_t maxMatches = std::numeric_limits<size_t>::max()) const
    {
        std::vector<size_t> matches;
        if(m_nodes.empty() || !m_paints[paintIndex].bounds.valid
                || maxMatches == 0)
            return matches;
        queryNode(
            0, paintIndex, m_paints[paintIndex].bounds,
            maxMatches, matches);
        std::sort(matches.begin(), matches.end());
        return matches;
    }

    bool hasLaterOverlap(size_t paintIndex) const
    {
        return !laterOverlaps(paintIndex, 1).empty();
    }

private:
    static constexpr size_t LEAF_SIZE = 16;

    struct Node {
        GridBounds bounds;
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
        GridBounds bounds;
        for(size_t offset = begin; offset < end; ++offset)
            bounds.include(m_paints[m_indices[offset]].bounds);
        m_nodes[nodeIndex].bounds = bounds;
        m_nodes[nodeIndex].begin = begin;
        m_nodes[nodeIndex].end = end;
        if(end - begin <= LEAF_SIZE) {
            m_nodes[nodeIndex].leaf = true;
            return nodeIndex;
        }

        const auto width = static_cast<long double>(bounds.max_x)
            - static_cast<long double>(bounds.min_x);
        const auto height = static_cast<long double>(bounds.max_y)
            - static_cast<long double>(bounds.min_y);
        const bool splitX = width >= height;
        std::sort(
            m_indices.begin() + static_cast<std::ptrdiff_t>(begin),
            m_indices.begin() + static_cast<std::ptrdiff_t>(end),
            [&](size_t left, size_t right) {
                const auto& leftBounds = m_paints[left].bounds;
                const auto& rightBounds = m_paints[right].bounds;
                const auto leftCenter = splitX
                    ? static_cast<long double>(leftBounds.min_x)
                        + static_cast<long double>(leftBounds.max_x)
                    : static_cast<long double>(leftBounds.min_y)
                        + static_cast<long double>(leftBounds.max_y);
                const auto rightCenter = splitX
                    ? static_cast<long double>(rightBounds.min_x)
                        + static_cast<long double>(rightBounds.max_x)
                    : static_cast<long double>(rightBounds.min_y)
                        + static_cast<long double>(rightBounds.max_y);
                return leftCenter == rightCenter
                    ? left < right : leftCenter < rightCenter;
            });
        const size_t middle = begin + (end - begin) / 2;
        const size_t left = buildNode(begin, middle);
        const size_t right = buildNode(middle, end);
        m_nodes[nodeIndex].left = left;
        m_nodes[nodeIndex].right = right;
        return nodeIndex;
    }

    void queryNode(size_t nodeIndex, size_t paintIndex,
                   const GridBounds& query, size_t maxMatches,
                   std::vector<size_t>& matches) const
    {
        if(matches.size() >= maxMatches)
            return;
        const auto& node = m_nodes[nodeIndex];
        if(!node.bounds.intersects(query))
            return;
        if(node.leaf) {
            for(size_t offset = node.begin;
                    offset < node.end && matches.size() < maxMatches;
                    ++offset) {
                const size_t candidate = m_indices[offset];
                if(candidate > paintIndex
                        && m_paints[candidate].bounds.intersects(query))
                    matches.push_back(candidate);
            }
            return;
        }
        queryNode(
            node.left, paintIndex, query, maxMatches, matches);
        queryNode(
            node.right, paintIndex, query, maxMatches, matches);
    }

    const std::vector<PaintGeometry>& m_paints;
    std::vector<size_t> m_indices;
    std::vector<Node> m_nodes;
};

struct SourceBounds {
    double min_x{std::numeric_limits<double>::infinity()};
    double min_y{std::numeric_limits<double>::infinity()};
    double max_x{-std::numeric_limits<double>::infinity()};
    double max_y{-std::numeric_limits<double>::infinity()};

    bool valid() const
    {
        return std::isfinite(min_x) && std::isfinite(min_y)
            && max_x > min_x && max_y > min_y;
    }

    void include(const PointD& point)
    {
        min_x = std::min(min_x, point.x);
        min_y = std::min(min_y, point.y);
        max_x = std::max(max_x, point.x);
        max_y = std::max(max_y, point.y);
    }

    void include(const SourceBounds& other)
    {
        if(!other.valid())
            return;
        include(PointD{other.min_x, other.min_y});
        include(PointD{other.max_x, other.max_y});
    }

    SourceBounds intersected(const SourceBounds& other) const
    {
        SourceBounds intersection;
        if(!valid() || !other.valid())
            return intersection;
        intersection.min_x = std::max(min_x, other.min_x);
        intersection.min_y = std::max(min_y, other.min_y);
        intersection.max_x = std::min(max_x, other.max_x);
        intersection.max_y = std::min(max_y, other.max_y);
        if(!intersection.valid())
            return {};
        return intersection;
    }
};

class TopologyCollapseError : public std::runtime_error {
public:
    TopologyCollapseError()
        : std::runtime_error("topology_collapse")
    {}
};

class InputPrecisionError : public std::runtime_error {
public:
    InputPrecisionError()
        : std::runtime_error("input_precision")
    {}
};

bool isPositiveFinite(double value)
{
    return std::isfinite(value) && value > 0;
}

double maximumSingularValue(const lunasvg::Matrix& matrix)
{
    const double aa = matrix.a * matrix.a + matrix.b * matrix.b;
    const double bb = matrix.c * matrix.c + matrix.d * matrix.d;
    const double cross = matrix.a * matrix.c + matrix.b * matrix.d;
    const double discriminant = std::sqrt(
        std::max(0.0, (aa - bb) * (aa - bb) + 4.0 * cross * cross));
    return std::sqrt(std::max(0.0, (aa + bb + discriminant) * 0.5));
}

PointD transformPoint(const lunasvg::Matrix& matrix, const PointD& point)
{
    return {
        matrix.a * point.x + matrix.c * point.y + matrix.e,
        matrix.b * point.x + matrix.d * point.y + matrix.f,
    };
}

double floatUlp(float value)
{
    if(!std::isfinite(value))
        return std::numeric_limits<double>::infinity();
    const float upward = std::nextafter(
        value, std::numeric_limits<float>::infinity());
    const float downward = std::nextafter(
        value, -std::numeric_limits<float>::infinity());
    return std::max(
        std::abs(static_cast<double>(upward) - value),
        std::abs(static_cast<double>(value) - downward));
}

bool isIdentityMatrix(const lunasvg::Matrix& matrix)
{
    return matrix.a == 1.0f && matrix.b == 0.0f
        && matrix.c == 0.0f && matrix.d == 1.0f
        && matrix.e == 0.0f && matrix.f == 0.0f;
}

struct CoordinatePrecisionError {
    double x{0};
    double y{0};
};

CoordinatePrecisionError transformedPointPrecisionError(
    const lunasvg::PaintCommand& command,
    const PointD& point)
{
    const double pathOperationUlps = 4.0
        + static_cast<double>(command.relative_path_operation_count);
    const double transformOperationUlps = 4.0 * std::max(
        1.0, static_cast<double>(command.transform_operation_count));
    const auto& matrix = command.transform;
    const double pointErrorX = floatUlp(static_cast<float>(point.x))
        * pathOperationUlps;
    const double pointErrorY = floatUlp(static_cast<float>(point.y))
        * pathOperationUlps;
    if(isIdentityMatrix(matrix))
        return {pointErrorX, pointErrorY};

    const double errorA = floatUlp(matrix.a) * transformOperationUlps;
    const double errorB = floatUlp(matrix.b) * transformOperationUlps;
    const double errorC = floatUlp(matrix.c) * transformOperationUlps;
    const double errorD = floatUlp(matrix.d) * transformOperationUlps;
    const double errorE = floatUlp(matrix.e) * transformOperationUlps;
    const double errorF = floatUlp(matrix.f) * transformOperationUlps;
    const double errorX = std::abs(static_cast<double>(matrix.a))
            * pointErrorX
        + std::abs(point.x) * errorA + pointErrorX * errorA
        + std::abs(static_cast<double>(matrix.c)) * pointErrorY
        + std::abs(point.y) * errorC + pointErrorY * errorC
        + errorE;
    const double errorY = std::abs(static_cast<double>(matrix.b))
            * pointErrorX
        + std::abs(point.x) * errorB + pointErrorX * errorB
        + std::abs(static_cast<double>(matrix.d)) * pointErrorY
        + std::abs(point.y) * errorD + pointErrorY * errorD
        + errorF;
    return {errorX, errorY};
}

CoordinatePrecisionError commandPrecisionError(
    const lunasvg::PaintCommand& command)
{
    constexpr double STROKE_OPERATION_ULPS = 4.0;
    CoordinatePrecisionError error;
    for(const auto& point : command.path_points) {
        const auto pointError = transformedPointPrecisionError(
            command, {point.x, point.y});
        error.x = std::max(error.x, pointError.x);
        error.y = std::max(error.y, pointError.y);
    }
    if(command.kind == lunasvg::PaintCommandKind::Stroke) {
        const double strokeError = floatUlp(command.stroke.width)
            * STROKE_OPERATION_ULPS
            * maximumSingularValue(command.transform);
        error.x = std::max(error.x, strokeError);
        error.y = std::max(error.y, strokeError);
    }
    return error;
}

double cubicCoordinate(double start, double control1, double control2,
                       double end, double t)
{
    const double oneMinusT = 1.0 - t;
    return oneMinusT * oneMinusT * oneMinusT * start
        + 3.0 * oneMinusT * oneMinusT * t * control1
        + 3.0 * oneMinusT * t * t * control2
        + t * t * t * end;
}

void includeCubicExtrema(const PointD& start, const PointD& control1,
                         const PointD& control2, const PointD& end,
                         SourceBounds& bounds)
{
    bounds.include(start);
    bounds.include(end);
    auto includeCoordinateExtrema = [&](double p0, double p1, double p2,
                                        double p3, bool xCoordinate) {
        const double a = -p0 + 3.0 * p1 - 3.0 * p2 + p3;
        const double b = 2.0 * (p0 - 2.0 * p1 + p2);
        const double c = p1 - p0;
        std::array<double, 2> roots{{-1, -1}};
        size_t rootCount = 0;
        if(std::abs(a) <= std::numeric_limits<double>::epsilon()) {
            if(std::abs(b) > std::numeric_limits<double>::epsilon())
                roots[rootCount++] = -c / b;
        } else {
            const double discriminant = b * b - 4.0 * a * c;
            if(discriminant >= 0) {
                const double root = std::sqrt(discriminant);
                roots[rootCount++] = (-b + root) / (2.0 * a);
                roots[rootCount++] = (-b - root) / (2.0 * a);
            }
        }
        for(size_t index = 0; index < rootCount; ++index) {
            const double t = roots[index];
            if(t <= 0 || t >= 1)
                continue;
            PointD point;
            if(xCoordinate) {
                point.x = cubicCoordinate(p0, p1, p2, p3, t);
                point.y = cubicCoordinate(start.y, control1.y, control2.y,
                                          end.y, t);
            } else {
                point.x = cubicCoordinate(start.x, control1.x, control2.x,
                                          end.x, t);
                point.y = cubicCoordinate(p0, p1, p2, p3, t);
            }
            bounds.include(point);
        }
    };
    includeCoordinateExtrema(start.x, control1.x, control2.x, end.x, true);
    includeCoordinateExtrema(start.y, control1.y, control2.y, end.y, false);
}

SourceBounds exactFillBounds(
    const lunasvg::PaintCommand& command,
    std::vector<SourceBounds>* collectedSubpathBounds = nullptr)
{
    SourceBounds bounds;
    if(command.kind == lunasvg::PaintCommandKind::Fill
            || command.kind == lunasvg::PaintCommandKind::ClipBegin) {
        size_t pointIndex = 0;
        PointD current;
        PointD subpathStart;
        bool hasCurrentPoint = false;
        SourceBounds subpathBounds;
        std::vector<PointD> supportPoints;
        auto finishSubpath = [&]() {
            bool hasNonCollinearPoints = false;
            if(supportPoints.size() >= 3) {
                const auto& first = supportPoints.front();
                size_t secondIndex = 1;
                while(secondIndex < supportPoints.size()
                        && supportPoints[secondIndex].x == first.x
                        && supportPoints[secondIndex].y == first.y)
                    ++secondIndex;
                if(secondIndex < supportPoints.size()) {
                    const auto& second = supportPoints[secondIndex];
                    for(size_t index = secondIndex + 1;
                            index < supportPoints.size(); ++index) {
                        const auto& third = supportPoints[index];
                        const long double cross =
                            static_cast<long double>(second.x - first.x)
                                * static_cast<long double>(third.y - first.y)
                            - static_cast<long double>(second.y - first.y)
                                * static_cast<long double>(third.x - first.x);
                        if(cross != 0.0L) {
                            hasNonCollinearPoints = true;
                            break;
                        }
                    }
                }
            }
            if(hasNonCollinearPoints) {
                bounds.include(subpathBounds);
                if(collectedSubpathBounds != nullptr)
                    collectedSubpathBounds->push_back(subpathBounds);
            }
            subpathBounds = {};
            supportPoints.clear();
        };
        auto beginSubpath = [&](const PointD& point) {
            const auto transformed = transformPoint(command.transform, point);
            subpathBounds.include(transformed);
            supportPoints.push_back(transformed);
        };
        for(const auto verb : command.path_verbs) {
            switch(verb) {
            case lunasvg::PaintPathVerb::MoveTo: {
                finishSubpath();
                const auto& point = command.path_points.at(pointIndex++);
                current = {point.x, point.y};
                subpathStart = current;
                hasCurrentPoint = true;
                beginSubpath(current);
                break;
            }
            case lunasvg::PaintPathVerb::LineTo: {
                const auto& point = command.path_points.at(pointIndex++);
                if(supportPoints.empty() && hasCurrentPoint)
                    beginSubpath(current);
                current = {point.x, point.y};
                const auto transformed = transformPoint(
                    command.transform, current);
                subpathBounds.include(transformed);
                supportPoints.push_back(transformed);
                break;
            }
            case lunasvg::PaintPathVerb::CubicTo: {
                const auto& first = command.path_points.at(pointIndex++);
                const auto& second = command.path_points.at(pointIndex++);
                const auto& last = command.path_points.at(pointIndex++);
                const auto transformedStart = transformPoint(command.transform,
                                                              current);
                const auto transformedFirst = transformPoint(
                    command.transform, {first.x, first.y});
                const auto transformedSecond = transformPoint(
                    command.transform, {second.x, second.y});
                const auto transformedLast = transformPoint(
                    command.transform, {last.x, last.y});
                if(supportPoints.empty() && hasCurrentPoint)
                    beginSubpath(current);
                includeCubicExtrema(transformedStart, transformedFirst,
                                    transformedSecond, transformedLast,
                                    subpathBounds);
                supportPoints.push_back(transformedFirst);
                supportPoints.push_back(transformedSecond);
                supportPoints.push_back(transformedLast);
                current = {last.x, last.y};
                break;
            }
            case lunasvg::PaintPathVerb::Close:
                finishSubpath();
                if(hasCurrentPoint)
                    current = subpathStart;
                break;
            }
        }
        finishSubpath();
    }
    return bounds;
}

SourceBounds exactFillBounds(
    const std::vector<lunasvg::PaintCommand>& commands)
{
    SourceBounds bounds;
    for(const auto& command : commands) {
        if(command.kind == lunasvg::PaintCommandKind::Fill)
            bounds.include(exactFillBounds(command));
    }
    return bounds;
}

SourceBounds exactPaintBounds(const lunasvg::PaintCommand& command)
{
    auto bounds = exactFillBounds(command);
    if(command.kind == lunasvg::PaintCommandKind::Stroke) {
        const double singularValue = maximumSingularValue(command.transform);
        if(!isPositiveFinite(singularValue))
            return bounds;
        double magnitude = std::max(1.0, static_cast<double>(command.stroke.width));
        for(const auto& point : command.path_points) {
            magnitude = std::max(magnitude, std::abs(static_cast<double>(point.x)));
            magnitude = std::max(magnitude, std::abs(static_cast<double>(point.y)));
        }
        const double sourcePrecision = std::max(1.0e-7, magnitude * 1.0e-10);
        const double localGridStep = std::max(
            sourcePrecision * std::sqrt(2.0) / singularValue,
            magnitude / 1.0e14);
        const double localFlattenTolerance = std::max(
            sourcePrecision / singularValue, localGridStep);
        for(const auto& ring : expandStrokeLocal(
                command, localFlattenTolerance, localGridStep)) {
            for(const auto& point : ring) {
                bounds.include(transformPoint(command.transform,
                                              {point.x, point.y}));
            }
        }
    }
    return bounds;
}

SourceBounds exactPaintBounds(
    const std::vector<lunasvg::PaintCommand>& commands)
{
    SourceBounds bounds;
    for(const auto& command : commands) {
        if(command.kind == lunasvg::PaintCommandKind::Fill
                || command.kind == lunasvg::PaintCommandKind::Stroke)
            bounds.include(exactPaintBounds(command));
    }
    return bounds;
}

struct ClipBoundsPlan {
    SourceBounds coordinate_bounds;
    SourceBounds clipped_paint_bounds;
    std::vector<SourceBounds> paint_bounds;
    double minimum_paint_extent{std::numeric_limits<double>::infinity()};
};

ClipBoundsPlan buildClipBoundsPlan(
    const std::vector<lunasvg::PaintCommand>& commands)
{
    ClipBoundsPlan plan;
    std::vector<SourceBounds> activeClips;
    for(const auto& command : commands) {
        if(command.kind == lunasvg::PaintCommandKind::ClipBegin) {
            auto bounds = exactFillBounds(command);
            plan.coordinate_bounds.include(bounds);
            activeClips.push_back(bounds);
            continue;
        }
        if(command.kind == lunasvg::PaintCommandKind::ClipEnd) {
            if(!activeClips.empty())
                activeClips.pop_back();
            continue;
        }
        if(command.kind != lunasvg::PaintCommandKind::Fill
                && command.kind != lunasvg::PaintCommandKind::Stroke)
            continue;

        auto bounds = command.kind == lunasvg::PaintCommandKind::Fill
            ? exactFillBounds(command)
            : exactPaintBounds(command);
        plan.coordinate_bounds.include(bounds);
        for(const auto& clip : activeClips)
            bounds = bounds.intersected(clip);
        plan.paint_bounds.push_back(bounds);
        if(!bounds.valid())
            continue;
        plan.clipped_paint_bounds.include(bounds);
        plan.minimum_paint_extent = std::min(
            plan.minimum_paint_extent,
            std::min(
                bounds.max_x - bounds.min_x,
                bounds.max_y - bounds.min_y));
    }
    return plan;
}

double pointSegmentDistance(const PointD& point,
                            const PointD& segmentStart,
                            const PointD& segmentEnd)
{
    const double dx = segmentEnd.x - segmentStart.x;
    const double dy = segmentEnd.y - segmentStart.y;
    const double lengthSquared = dx * dx + dy * dy;
    if(lengthSquared == 0.0)
        return std::hypot(point.x - segmentStart.x,
                          point.y - segmentStart.y);
    const double projection = std::clamp(
        ((point.x - segmentStart.x) * dx
         + (point.y - segmentStart.y) * dy) / lengthSquared,
        0.0, 1.0);
    return std::hypot(
        point.x - (segmentStart.x + projection * dx),
        point.y - (segmentStart.y + projection * dy));
}

SourceBounds segmentBounds(const SourceSegment& segment)
{
    SourceBounds bounds;
    bounds.include(segment.start);
    bounds.include(segment.end);
    return bounds;
}

bool boundsWithinDistance(const SourceBounds& left,
                          const SourceBounds& right,
                          double distance)
{
    return left.min_x <= right.max_x + distance
        && left.max_x + distance >= right.min_x
        && left.min_y <= right.max_y + distance
        && left.max_y + distance >= right.min_y;
}

long double orientation(const PointD& first, const PointD& second,
                        const PointD& third)
{
    return static_cast<long double>(second.x - first.x)
            * static_cast<long double>(third.y - first.y)
        - static_cast<long double>(second.y - first.y)
            * static_cast<long double>(third.x - first.x);
}

enum class SegmentIntersection {
    None,
    Proper,
    TouchingOrOverlapping,
};

bool pointOnSegment(const PointD& point, const SourceSegment& segment)
{
    return orientation(segment.start, segment.end, point) == 0.0L
        && point.x >= std::min(segment.start.x, segment.end.x)
        && point.x <= std::max(segment.start.x, segment.end.x)
        && point.y >= std::min(segment.start.y, segment.end.y)
        && point.y <= std::max(segment.start.y, segment.end.y);
}

SegmentIntersection segmentIntersection(const SourceSegment& left,
                                        const SourceSegment& right)
{
    const long double leftStart = orientation(
        left.start, left.end, right.start);
    const long double leftEnd = orientation(
        left.start, left.end, right.end);
    const long double rightStart = orientation(
        right.start, right.end, left.start);
    const long double rightEnd = orientation(
        right.start, right.end, left.end);
    if(((leftStart > 0 && leftEnd < 0)
            || (leftStart < 0 && leftEnd > 0))
            && ((rightStart > 0 && rightEnd < 0)
                || (rightStart < 0 && rightEnd > 0)))
        return SegmentIntersection::Proper;
    if((leftStart == 0.0L && pointOnSegment(right.start, left))
            || (leftEnd == 0.0L && pointOnSegment(right.end, left))
            || (rightStart == 0.0L && pointOnSegment(left.start, right))
            || (rightEnd == 0.0L && pointOnSegment(left.end, right)))
        return SegmentIntersection::TouchingOrOverlapping;
    return SegmentIntersection::None;
}

double segmentDistance(const SourceSegment& left,
                       const SourceSegment& right)
{
    if(segmentIntersection(left, right) != SegmentIntersection::None)
        return 0.0;
    return std::min({
        pointSegmentDistance(left.start, right.start, right.end),
        pointSegmentDistance(left.end, right.start, right.end),
        pointSegmentDistance(right.start, left.start, left.end),
        pointSegmentDistance(right.end, left.start, left.end),
    });
}

bool adjacentContourEdges(const SourceSegment& left,
                          const SourceSegment& right)
{
    if(left.contour_id != right.contour_id)
        return false;
    const size_t difference = left.edge_index > right.edge_index
        ? left.edge_index - right.edge_index
        : right.edge_index - left.edge_index;
    return difference == 1
        || difference + 1 == left.edge_count;
}

class SourceSegmentIndex {
public:
    explicit SourceSegmentIndex(const std::vector<SourceSegment>& segments)
    {
        buildUniqueSegments(segments);
        m_indices.resize(m_segments.size());
        std::iota(m_indices.begin(), m_indices.end(), size_t{0});
        if(!m_indices.empty())
            buildNode(0, m_indices.size());
    }

    bool hasUnstableSegments(
        double quantizationErrorSource,
        double maximumIntersectionDisplacementSource,
        double minimumSignificantGapSource,
        double minimumSignificantIntersectionMarginSource) const
    {
        if(m_unstableDuplicate)
            return true;
        if(!std::isfinite(quantizationErrorSource)
                || quantizationErrorSource < 0
                || !std::isfinite(maximumIntersectionDisplacementSource)
                || maximumIntersectionDisplacementSource <= 0
                || !std::isfinite(minimumSignificantGapSource)
                || minimumSignificantGapSource <= 0
                || !std::isfinite(
                    minimumSignificantIntersectionMarginSource)
                || minimumSignificantIntersectionMarginSource <= 0)
            return true;
        size_t candidateChecks = 0;
        for(size_t index = 0; index < m_segments.size(); ++index) {
            if(queryNode(
                    0, index, segmentBounds(m_segments[index]),
                    quantizationErrorSource,
                    maximumIntersectionDisplacementSource,
                    minimumSignificantGapSource,
                    minimumSignificantIntersectionMarginSource,
                    candidateChecks))
                return true;
        }
        return false;
    }

private:
    static constexpr size_t LEAF_SIZE = 12;
    static constexpr size_t MAX_CANDIDATE_CHECKS = 2'000'000;

    struct Node {
        SourceBounds bounds;
        size_t begin{0};
        size_t end{0};
        size_t left{0};
        size_t right{0};
        double maximum_boundary_error{0};
        bool leaf{false};
    };

    static bool pointLess(const PointD& left, const PointD& right)
    {
        return left.x < right.x
            || (left.x == right.x && left.y < right.y);
    }

    static std::pair<PointD, PointD> canonicalEndpoints(
        const SourceSegment& segment)
    {
        return pointLess(segment.end, segment.start)
            ? std::make_pair(segment.end, segment.start)
            : std::make_pair(segment.start, segment.end);
    }

    static bool sameUndirectedSegment(const SourceSegment& left,
                                      const SourceSegment& right)
    {
        const auto leftEndpoints = canonicalEndpoints(left);
        const auto rightEndpoints = canonicalEndpoints(right);
        return leftEndpoints.first.x == rightEndpoints.first.x
            && leftEndpoints.first.y == rightEndpoints.first.y
            && leftEndpoints.second.x == rightEndpoints.second.x
            && leftEndpoints.second.y == rightEndpoints.second.y;
    }

    void buildUniqueSegments(const std::vector<SourceSegment>& segments)
    {
        std::vector<size_t> sortedIndices(segments.size());
        std::iota(sortedIndices.begin(), sortedIndices.end(), size_t{0});
        std::sort(
            sortedIndices.begin(), sortedIndices.end(),
            [&](size_t leftIndex, size_t rightIndex) {
                const auto left = canonicalEndpoints(segments[leftIndex]);
                const auto right = canonicalEndpoints(segments[rightIndex]);
                if(pointLess(left.first, right.first))
                    return true;
                if(pointLess(right.first, left.first))
                    return false;
                if(pointLess(left.second, right.second))
                    return true;
                if(pointLess(right.second, left.second))
                    return false;
                return leftIndex < rightIndex;
            });
        size_t begin = 0;
        while(begin < sortedIndices.size()) {
            size_t end = begin + 1;
            while(end < sortedIndices.size()
                    && sameUndirectedSegment(
                        segments[sortedIndices[begin]],
                        segments[sortedIndices[end]]))
                ++end;
            std::vector<int64_t> operationIds;
            operationIds.reserve(end - begin);
            SourceSegment representative = segments[sortedIndices[begin]];
            for(size_t offset = begin; offset < end; ++offset) {
                const auto& segment = segments[sortedIndices[offset]];
                operationIds.push_back(segment.operation_id);
                representative.input_precision_error_source = std::max(
                    representative.input_precision_error_source,
                    segment.input_precision_error_source);
                representative.approximation_error_source = std::max(
                    representative.approximation_error_source,
                    segment.approximation_error_source);
            }
            std::sort(operationIds.begin(), operationIds.end());
            if(std::adjacent_find(operationIds.begin(), operationIds.end())
                    != operationIds.end())
                m_unstableDuplicate = true;
            m_segments.emplace_back(std::move(representative));
            begin = end;
        }
    }

    static bool robustProperCrossing(const SourceSegment& left,
                                     const SourceSegment& right,
                                     double errorDistance,
                                     double inputErrorDistance,
                                     double maximumDisplacement)
    {
        const double leftDx = left.end.x - left.start.x;
        const double leftDy = left.end.y - left.start.y;
        const double rightDx = right.end.x - right.start.x;
        const double rightDy = right.end.y - right.start.y;
        const double lengthProduct = std::hypot(leftDx, leftDy)
            * std::hypot(rightDx, rightDy);
        if(!(lengthProduct > 0))
            return false;
        const double sineAngle = std::abs(
            leftDx * rightDy - leftDy * rightDx) / lengthProduct;
        if(!(sineAngle > 0)
                || inputErrorDistance / sineAngle > maximumDisplacement)
            return false;
        return pointSegmentDistance(
                   left.start, right.start, right.end) > errorDistance
            && pointSegmentDistance(
                   left.end, right.start, right.end) > errorDistance
            && pointSegmentDistance(
                   right.start, left.start, left.end) > errorDistance
            && pointSegmentDistance(
                   right.end, left.start, left.end) > errorDistance;
    }

    static bool sharedEndpoint(const SourceSegment& left,
                               const SourceSegment& right)
    {
        auto samePoint = [](const PointD& first, const PointD& second) {
            return first.x == second.x && first.y == second.y;
        };
        return samePoint(left.start, right.start)
            || samePoint(left.start, right.end)
            || samePoint(left.end, right.start)
            || samePoint(left.end, right.end);
    }

    static double minimumEndpointMargin(const SourceSegment& left,
                                        const SourceSegment& right)
    {
        return std::min({
            pointSegmentDistance(left.start, right.start, right.end),
            pointSegmentDistance(left.end, right.start, right.end),
            pointSegmentDistance(right.start, left.start, left.end),
            pointSegmentDistance(right.end, left.start, left.end),
        });
    }

    static bool robustNonCollinearTouch(
        const SourceSegment& left, const SourceSegment& right,
        double errorDistance, double inputErrorDistance,
        double maximumDisplacement)
    {
        const double leftDx = left.end.x - left.start.x;
        const double leftDy = left.end.y - left.start.y;
        const double rightDx = right.end.x - right.start.x;
        const double rightDy = right.end.y - right.start.y;
        const double lengthProduct = std::hypot(leftDx, leftDy)
            * std::hypot(rightDx, rightDy);
        if(!(lengthProduct > 0))
            return false;
        const double sineAngle = std::abs(
            leftDx * rightDy - leftDy * rightDx) / lengthProduct;
        if(!(sineAngle > 0)
                || inputErrorDistance / sineAngle > maximumDisplacement)
            return false;
        const double leftMargin = std::max(
            pointSegmentDistance(left.start, right.start, right.end),
            pointSegmentDistance(left.end, right.start, right.end));
        const double rightMargin = std::max(
            pointSegmentDistance(right.start, left.start, left.end),
            pointSegmentDistance(right.end, left.start, left.end));
        return leftMargin > errorDistance && rightMargin > errorDistance;
    }

    size_t buildNode(size_t begin, size_t end)
    {
        const size_t nodeIndex = m_nodes.size();
        m_nodes.emplace_back();
        SourceBounds bounds;
        for(size_t offset = begin; offset < end; ++offset) {
            const auto& segment = m_segments[m_indices[offset]];
            bounds.include(segment.start);
            bounds.include(segment.end);
            m_nodes[nodeIndex].maximum_boundary_error = std::max(
                m_nodes[nodeIndex].maximum_boundary_error,
                segment.input_precision_error_source
                    + segment.approximation_error_source);
        }
        m_nodes[nodeIndex].bounds = bounds;
        m_nodes[nodeIndex].begin = begin;
        m_nodes[nodeIndex].end = end;
        if(end - begin <= LEAF_SIZE) {
            m_nodes[nodeIndex].leaf = true;
            return nodeIndex;
        }
        const bool splitX = bounds.max_x - bounds.min_x
            >= bounds.max_y - bounds.min_y;
        const size_t middle = begin + (end - begin) / 2;
        std::nth_element(
            m_indices.begin() + static_cast<std::ptrdiff_t>(begin),
            m_indices.begin() + static_cast<std::ptrdiff_t>(middle),
            m_indices.begin() + static_cast<std::ptrdiff_t>(end),
            [&](size_t left, size_t right) {
                const auto leftBounds = segmentBounds(m_segments[left]);
                const auto rightBounds = segmentBounds(m_segments[right]);
                const double leftCenter = splitX
                    ? leftBounds.min_x + leftBounds.max_x
                    : leftBounds.min_y + leftBounds.max_y;
                const double rightCenter = splitX
                    ? rightBounds.min_x + rightBounds.max_x
                    : rightBounds.min_y + rightBounds.max_y;
                return leftCenter == rightCenter
                    ? left < right : leftCenter < rightCenter;
            });
        const size_t left = buildNode(begin, middle);
        const size_t right = buildNode(middle, end);
        m_nodes[nodeIndex].left = left;
        m_nodes[nodeIndex].right = right;
        return nodeIndex;
    }

    bool queryNode(size_t nodeIndex, size_t segmentIndex,
                   const SourceBounds& query, double quantizationErrorSource,
                   double maximumIntersectionDisplacementSource,
                   double minimumSignificantGapSource,
                   double minimumSignificantIntersectionMarginSource,
                   size_t& candidateChecks) const
    {
        const auto& node = m_nodes[nodeIndex];
        const auto& segment = m_segments[segmentIndex];
        const double nodeDistance = quantizationErrorSource * 2.0
            + segment.input_precision_error_source
            + segment.approximation_error_source
            + node.maximum_boundary_error;
        const double nodeSearchDistance =
            nodeDistance > minimumSignificantGapSource
                ? nodeDistance : 0.0;
        if(!boundsWithinDistance(query, node.bounds, nodeSearchDistance))
            return false;
        if(node.leaf) {
            for(size_t offset = node.begin; offset < node.end; ++offset) {
                const size_t candidateIndex = m_indices[offset];
                if(candidateIndex <= segmentIndex)
                    continue;
                const auto& candidate = m_segments[candidateIndex];
                const double pairDistance = quantizationErrorSource * 2.0
                    + segment.input_precision_error_source
                    + candidate.input_precision_error_source
                    + segment.approximation_error_source
                    + candidate.approximation_error_source;
                const double pairInputDistance = quantizationErrorSource * 2.0
                    + segment.input_precision_error_source
                    + candidate.input_precision_error_source;
                const double pairSearchDistance =
                    pairDistance > minimumSignificantGapSource
                        ? pairDistance : 0.0;
                if(adjacentContourEdges(segment, candidate)
                        || !boundsWithinDistance(
                            query, segmentBounds(candidate),
                            pairSearchDistance))
                    continue;
                if(++candidateChecks > MAX_CANDIDATE_CHECKS)
                    return true;
                const auto intersection = segmentIntersection(
                    segment, candidate);
                if(intersection != SegmentIntersection::None) {
                    if(intersection == SegmentIntersection::Proper) {
                        if(robustProperCrossing(
                                segment, candidate, pairDistance,
                                pairInputDistance,
                                maximumIntersectionDisplacementSource))
                            continue;
                        if(minimumEndpointMargin(segment, candidate)
                                <= minimumSignificantIntersectionMarginSource)
                            continue;
                        return true;
                    }
                    if(segment.operation_id != candidate.operation_id
                            || sharedEndpoint(segment, candidate)
                            || robustNonCollinearTouch(
                                segment, candidate, pairDistance,
                                pairInputDistance,
                                maximumIntersectionDisplacementSource))
                        continue;
                    return true;
                }
                const double distance = segmentDistance(segment, candidate);
                if(distance <= pairDistance
                        && distance > minimumSignificantGapSource)
                    return true;
            }
            return false;
        }
        return queryNode(
                   node.left, segmentIndex, query, quantizationErrorSource,
                   maximumIntersectionDisplacementSource,
                   minimumSignificantGapSource,
                   minimumSignificantIntersectionMarginSource,
                   candidateChecks)
            || queryNode(
                   node.right, segmentIndex, query, quantizationErrorSource,
                   maximumIntersectionDisplacementSource,
                   minimumSignificantGapSource,
                   minimumSignificantIntersectionMarginSource,
                   candidateChecks);
    }

    std::vector<SourceSegment> m_segments;
    std::vector<size_t> m_indices;
    std::vector<Node> m_nodes;
    bool m_unstableDuplicate{false};
};

double maximumRelevantBoundaryErrorSource(
    const TopologyTrace& trace,
    const SourceBounds& sourceBounds,
    const lunasvg::Box& viewport)
{
    constexpr double VIEWPORT_OPERATION_ULPS = 4.0;
    double maximumError = std::max({
        floatUlp(viewport.x) * VIEWPORT_OPERATION_ULPS,
        floatUlp(viewport.y) * VIEWPORT_OPERATION_ULPS,
        floatUlp(viewport.w) * VIEWPORT_OPERATION_ULPS,
        floatUlp(viewport.h) * VIEWPORT_OPERATION_ULPS,
    });
    for(const auto& segment : trace.segments) {
        const auto bounds = segmentBounds(segment);
        const bool intersectsResultDomain =
            bounds.min_x <= sourceBounds.max_x
            && bounds.max_x >= sourceBounds.min_x
            && bounds.min_y <= sourceBounds.max_y
            && bounds.max_y >= sourceBounds.min_y;
        if(!intersectsResultDomain)
            continue;
        maximumError = std::max(
            maximumError,
            segment.input_precision_error_source
                + segment.approximation_error_source);
    }
    return maximumError;
}

void flattenCubic(const PointD& start, const PointD& control1,
                  const PointD& control2, const PointD& end,
                  double tolerance, double sourceErrorScale,
                  unsigned depth, std::vector<PointD>& output,
                  std::vector<double>& incomingApproximationErrors)
{
    const double localApproximationError = std::max(
        pointSegmentDistance(control1, start, end),
        pointSegmentDistance(control2, start, end));
    if(depth >= 32 || localApproximationError <= tolerance) {
        output.push_back(end);
        incomingApproximationErrors.push_back(
            localApproximationError * sourceErrorScale);
        return;
    }

    const PointD p01{(start.x + control1.x) * 0.5,
                     (start.y + control1.y) * 0.5};
    const PointD p12{(control1.x + control2.x) * 0.5,
                     (control1.y + control2.y) * 0.5};
    const PointD p23{(control2.x + end.x) * 0.5,
                     (control2.y + end.y) * 0.5};
    const PointD p012{(p01.x + p12.x) * 0.5, (p01.y + p12.y) * 0.5};
    const PointD p123{(p12.x + p23.x) * 0.5, (p12.y + p23.y) * 0.5};
    const PointD midpoint{(p012.x + p123.x) * 0.5,
                          (p012.y + p123.y) * 0.5};
    flattenCubic(
        start, p01, p012, midpoint, tolerance, sourceErrorScale,
        depth + 1, output, incomingApproximationErrors);
    flattenCubic(
        midpoint, p123, p23, end, tolerance, sourceErrorScale,
        depth + 1, output, incomingApproximationErrors);
}

int64_t checkedQuantize(double value)
{
    constexpr double safeCoordinate = 1.0e15;
    if(!std::isfinite(value) || std::abs(value) > safeCoordinate)
        throw std::range_error("numeric_range_error");
    return static_cast<int64_t>(std::llround(value));
}

Point64 toGridPoint(const PointD& local,
                    const lunasvg::Matrix& transform,
                    const PhysicalDomain& domain)
{
    const auto source = transformPoint(transform, local);
    const auto x = (source.x - domain.bbox_x) * domain.source_to_mm
        / domain.grid_step_mm;
    const auto y = (source.y - domain.bbox_y) * domain.source_to_mm
        / domain.grid_step_mm;
    return Point64(checkedQuantize(x), checkedQuantize(y));
}

bool hasNonCollinearTransformedPoints(
    const std::vector<PointD>& points,
    const lunasvg::Matrix& transform)
{
    if(points.size() < 3)
        return false;
    const auto first = transformPoint(transform, points.front());
    size_t secondIndex = 1;
    PointD second;
    for(; secondIndex < points.size(); ++secondIndex) {
        second = transformPoint(transform, points[secondIndex]);
        if(second.x != first.x || second.y != first.y)
            break;
    }
    if(secondIndex == points.size())
        return false;
    for(size_t index = secondIndex + 1; index < points.size(); ++index) {
        const auto third = transformPoint(transform, points[index]);
        const long double cross =
            static_cast<long double>(second.x - first.x)
                * static_cast<long double>(third.y - first.y)
            - static_cast<long double>(second.y - first.y)
                * static_cast<long double>(third.x - first.x);
        if(cross != 0.0L)
            return true;
    }
    return false;
}

void traceClosedContour(const std::vector<PointD>& localPoints,
                        const lunasvg::Matrix& transform,
                        int64_t operationId,
                        const CoordinatePrecisionError& precisionError,
                        const std::vector<double>& incomingApproximationErrors,
                        TopologyTrace* trace)
{
    if(trace == nullptr || localPoints.size() < 3)
        return;
    if(incomingApproximationErrors.size() != localPoints.size())
        throw std::logic_error("invalid_approximation_error_count");
    std::vector<PointD> points;
    std::vector<double> incomingErrors;
    points.reserve(localPoints.size());
    incomingErrors.reserve(localPoints.size());
    for(size_t index = 0; index < localPoints.size(); ++index) {
        const auto& local = localPoints[index];
        const auto point = transformPoint(transform, local);
        if(points.empty() || point.x != points.back().x
                || point.y != points.back().y) {
            points.push_back(point);
            incomingErrors.push_back(incomingApproximationErrors[index]);
        } else {
            incomingErrors.back() = std::max(
                incomingErrors.back(), incomingApproximationErrors[index]);
        }
    }
    if(points.size() > 1
            && points.front().x == points.back().x
            && points.front().y == points.back().y) {
        incomingErrors.front() = std::max(
            incomingErrors.front(), incomingErrors.back());
        points.pop_back();
        incomingErrors.pop_back();
    }
    if(points.size() < 3)
        return;
    const size_t contourId = trace->next_contour_id++;
    for(size_t index = 0; index < points.size(); ++index) {
        const auto& start = points[index];
        const auto& end = points[(index + 1) % points.size()];
        if(start.x == end.x && start.y == end.y)
            continue;
        const double dx = end.x - start.x;
        const double dy = end.y - start.y;
        const double length = std::hypot(dx, dy);
        const double normalPrecisionError = length > 0
            ? (std::abs(dy) * precisionError.x
                + std::abs(dx) * precisionError.y) / length
            : std::max(precisionError.x, precisionError.y);
        trace->segments.push_back({
            start, end, contourId, index, points.size(),
            operationId, normalPrecisionError,
            incomingErrors[(index + 1) % points.size()],
        });
    }
}

void traceClosedContour(const std::vector<PointD>& localPoints,
                        const lunasvg::Matrix& transform,
                        int64_t operationId,
                        const CoordinatePrecisionError& precisionError,
                        double approximationErrorSource,
                        TopologyTrace* trace)
{
    traceClosedContour(
        localPoints, transform, operationId, precisionError,
        std::vector<double>(localPoints.size(), approximationErrorSource),
        trace);
}

void finishSubpath(std::vector<PointD>& points,
                   std::vector<double>& incomingApproximationErrors,
                   const lunasvg::PaintCommand& command,
                   const PhysicalDomain& domain,
                   const CoordinatePrecisionError& precisionError,
                   Paths64& paths)
{
    if(points.size() < 3) {
        points.clear();
        incomingApproximationErrors.clear();
        return;
    }
    const bool sourceHasArea = hasNonCollinearTransformedPoints(
        points, command.transform);
    if(!sourceHasArea)
        throw InputPrecisionError();
    traceClosedContour(
        points, command.transform,
        static_cast<int64_t>(command.source_index) * 8
            + static_cast<int64_t>(command.kind),
        precisionError,
        incomingApproximationErrors,
        domain.topology_trace);
    Path64 path;
    path.reserve(points.size());
    for(const auto& point : points) {
        const auto gridPoint = toGridPoint(point, command.transform, domain);
        if(path.empty() || path.back() != gridPoint)
            path.push_back(gridPoint);
    }
    if(path.size() > 1 && path.front() == path.back())
        path.pop_back();
    if(sourceHasArea && (path.size() < 3
            || Clipper2Lib::Area(path) == 0.0))
        throw TopologyCollapseError();
    if(path.size() >= 3)
        paths.emplace_back(std::move(path));
    points.clear();
    incomingApproximationErrors.clear();
}

Paths64 flattenFill(const lunasvg::PaintCommand& command,
                    const PhysicalDomain& domain)
{
    const double singularValue = maximumSingularValue(command.transform);
    if(!isPositiveFinite(singularValue))
        return {};
    const double localTolerance = domain.flatten_budget_mm
        / (domain.source_to_mm * singularValue);
    Paths64 paths;
    std::vector<PointD> subpath;
    std::vector<double> incomingApproximationErrors;
    CoordinatePrecisionError subpathPrecisionError;
    PointD current;
    PointD subpathStart;
    bool hasCurrentPoint = false;
    size_t pointIndex = 0;
    auto includePointPrecision = [&](const PointD& point) {
        const auto error = transformedPointPrecisionError(
            command, point);
        subpathPrecisionError.x = std::max(
            subpathPrecisionError.x, error.x);
        subpathPrecisionError.y = std::max(
            subpathPrecisionError.y, error.y);
    };
    auto includePrecision = [&](const lunasvg::PaintPoint& point) {
        includePointPrecision({point.x, point.y});
    };
    for(const auto verb : command.path_verbs) {
        switch(verb) {
        case lunasvg::PaintPathVerb::MoveTo: {
            finishSubpath(
                subpath, incomingApproximationErrors, command, domain,
                subpathPrecisionError, paths);
            subpathPrecisionError = {};
            const auto& point = command.path_points.at(pointIndex++);
            includePrecision(point);
            current = {point.x, point.y};
            subpathStart = current;
            hasCurrentPoint = true;
            subpath.push_back(current);
            incomingApproximationErrors.push_back(0.0);
            break;
        }
        case lunasvg::PaintPathVerb::LineTo: {
            const auto& point = command.path_points.at(pointIndex++);
            includePrecision(point);
            if(subpath.empty() && hasCurrentPoint) {
                includePointPrecision(current);
                subpath.push_back(current);
                incomingApproximationErrors.push_back(0.0);
            }
            current = {point.x, point.y};
            subpath.push_back(current);
            incomingApproximationErrors.push_back(0.0);
            break;
        }
        case lunasvg::PaintPathVerb::CubicTo: {
            const auto& first = command.path_points.at(pointIndex++);
            const auto& second = command.path_points.at(pointIndex++);
            const auto& last = command.path_points.at(pointIndex++);
            includePrecision(first);
            includePrecision(second);
            includePrecision(last);
            const PointD control1{first.x, first.y};
            const PointD control2{second.x, second.y};
            const PointD end{last.x, last.y};
            if(subpath.empty() && hasCurrentPoint) {
                includePointPrecision(current);
                subpath.push_back(current);
                incomingApproximationErrors.push_back(0.0);
            }
            flattenCubic(current, control1, control2, end,
                         localTolerance, singularValue, 0, subpath,
                         incomingApproximationErrors);
            current = end;
            break;
        }
        case lunasvg::PaintPathVerb::Close:
            finishSubpath(
                subpath, incomingApproximationErrors, command, domain,
                subpathPrecisionError, paths);
            subpathPrecisionError = {};
            if(hasCurrentPoint)
                current = subpathStart;
            break;
        }
    }
    finishSubpath(
        subpath, incomingApproximationErrors, command, domain,
        subpathPrecisionError, paths);
    return paths;
}

FillRule clipperFillRule(lunasvg::PaintFillRule fillRule)
{
    return fillRule == lunasvg::PaintFillRule::EvenOdd
        ? FillRule::EvenOdd : FillRule::NonZero;
}

Paths64 normalizeFill(const lunasvg::PaintCommand& command,
                      const PhysicalDomain& domain)
{
    auto paths = flattenFill(command, domain);
    return Clipper2Lib::Union(paths, clipperFillRule(command.fill_rule));
}

Paths64 normalizeStroke(const lunasvg::PaintCommand& command,
                        const PhysicalDomain& domain)
{
    const double singularValue = maximumSingularValue(command.transform);
    if(!isPositiveFinite(singularValue))
        return {};
    const double localFlattenTolerance = domain.flatten_budget_mm
        / (domain.source_to_mm * singularValue);
    const double localGridStep = domain.stroke_quantization_budget_mm
        * std::sqrt(2.0) / (domain.source_to_mm * singularValue);
    Paths64 paths;
    const auto precisionError = commandPrecisionError(command);
    for(const auto& ring : expandStrokeLocal(
            command, localFlattenTolerance, localGridStep)) {
        std::vector<PointD> localPoints;
        localPoints.reserve(ring.size());
        for(const auto& point : ring)
            localPoints.push_back({point.x, point.y});
        traceClosedContour(
            localPoints, command.transform,
            static_cast<int64_t>(command.source_index) * 8
                + static_cast<int64_t>(command.kind),
            precisionError,
            (domain.flatten_budget_mm
                + domain.stroke_quantization_budget_mm)
                / domain.source_to_mm,
            domain.topology_trace);
        Path64 path;
        path.reserve(ring.size());
        for(const auto& point : ring) {
            const auto gridPoint = toGridPoint(
                {point.x, point.y}, command.transform, domain);
            if(path.empty() || path.back() != gridPoint)
                path.push_back(gridPoint);
        }
        if(path.size() > 1 && path.front() == path.back())
            path.pop_back();
        if(path.size() < 3 || Clipper2Lib::Area(path) == 0.0)
            throw TopologyCollapseError();
        if(path.size() >= 3)
            paths.emplace_back(std::move(path));
    }
    return Clipper2Lib::Union(paths, FillRule::NonZero);
}

Paths64 applyActiveClips(Paths64 paths,
                         const std::vector<Paths64>& activeClips)
{
    for(const auto& clip : activeClips) {
        paths = Clipper2Lib::Intersect(paths, clip, FillRule::NonZero);
        if(paths.empty())
            break;
    }
    return paths;
}

struct PaintReplay {
    std::vector<PaintGeometry> paints;
    std::string reason_code;
};

PaintReplay replayPaintCommands(
    const std::vector<lunasvg::PaintCommand>& commands,
    const PhysicalDomain& domain)
{
    PaintReplay replay;
    std::vector<Paths64> activeClips;
    replay.paints.reserve(commands.size());
    int32_t drawIndex = 0;
    for(const auto& command : commands) {
        if(command.kind == lunasvg::PaintCommandKind::ClipBegin) {
            activeClips.push_back(normalizeFill(command, domain));
            continue;
        }
        if(command.kind == lunasvg::PaintCommandKind::ClipEnd) {
            if(activeClips.empty()) {
                replay.reason_code = "invalid_clip_stack";
                return replay;
            }
            activeClips.pop_back();
            continue;
        }
        if(command.kind != lunasvg::PaintCommandKind::Fill
                && command.kind != lunasvg::PaintCommandKind::Stroke)
            continue;

        PaintGeometry paint;
        paint.paths = command.kind == lunasvg::PaintCommandKind::Stroke
            ? normalizeStroke(command, domain)
            : normalizeFill(command, domain);
        paint.paths = applyActiveClips(std::move(paint.paths), activeClips);
        paint.bounds = pathsBounds(paint.paths);
        paint.rgba = command.rgba;
        paint.draw_index = drawIndex++;
        paint.source_index = command.source_index;
        paint.source_kind = command.kind == lunasvg::PaintCommandKind::Stroke
            ? SourceKind::Stroke : SourceKind::Fill;
        replay.paints.emplace_back(std::move(paint));
    }
    if(!activeClips.empty())
        replay.reason_code = "invalid_clip_stack";
    return replay;
}

bool hasNonEmptyPaint(const std::vector<PaintGeometry>& paints)
{
    return std::any_of(
        paints.begin(), paints.end(),
        [](const PaintGeometry& paint) { return !paint.paths.empty(); });
}

SourceBounds sourceBoundsForPaints(
    const std::vector<PaintGeometry>& paints,
    const PhysicalDomain& domain)
{
    SourceBounds bounds;
    const double gridToSource = domain.grid_step_mm / domain.source_to_mm;
    for(const auto& paint : paints) {
        if(!paint.bounds.valid)
            continue;
        bounds.include(PointD{
            domain.bbox_x + paint.bounds.min_x * gridToSource,
            domain.bbox_y + paint.bounds.min_y * gridToSource,
        });
        bounds.include(PointD{
            domain.bbox_x + paint.bounds.max_x * gridToSource,
            domain.bbox_y + paint.bounds.max_y * gridToSource,
        });
    }
    return bounds;
}

void includeViewport(SourceBounds& bounds, const lunasvg::Box& viewport)
{
    if(!isPositiveFinite(viewport.w) || !isPositiveFinite(viewport.h))
        return;
    bounds.include(PointD{viewport.x, viewport.y});
    bounds.include(PointD{viewport.x + viewport.w, viewport.y + viewport.h});
}

void appendRing(GeometryCollection& collection, const Path64& ring,
                int64_t parent)
{
    if(ring.size() < 3)
        return;
    const uint64_t pointCount = collection.coordinates.size() / 2;
    if(pointCount > std::numeric_limits<uint64_t>::max() - ring.size() - 1)
        throw std::length_error("result_size_overflow");
    for(const auto& point : ring) {
        collection.coordinates.push_back(point.x);
        collection.coordinates.push_back(point.y);
    }
    collection.coordinates.push_back(ring.front().x);
    collection.coordinates.push_back(ring.front().y);
    collection.ring_offsets.push_back(pointCount + ring.size() + 1);
    collection.hole_parent.push_back(parent);
}

void appendOuterNode(GeometryCollection& collection, const PolyPath64& outer)
{
    if(outer.IsHole() || outer.Polygon().size() < 3)
        return;
    const auto outerRingIndex = static_cast<int64_t>(
        collection.ring_offsets.size() - 1);
    appendRing(collection, outer.Polygon(), -1);
    for(size_t index = 0; index < outer.Count(); ++index) {
        const auto* child = outer.Child(index);
        if(child->IsHole())
            appendRing(collection, child->Polygon(), outerRingIndex);
    }
    collection.polygon_offsets.push_back(collection.ring_offsets.size() - 1);

    for(size_t index = 0; index < outer.Count(); ++index) {
        const auto* hole = outer.Child(index);
        for(size_t childIndex = 0; childIndex < hole->Count(); ++childIndex)
            appendOuterNode(collection, *hole->Child(childIndex));
    }
}

void appendGeometry(GeometryCollection& collection,
                    const PaintGeometry& geometry)
{
    PolyTree64 tree;
    if(!geometry.paths.empty()) {
        Clipper64 clipper;
        clipper.AddSubject(geometry.paths);
        if(!clipper.Execute(ClipType::Union, FillRule::NonZero, tree))
            throw std::runtime_error("clipper_union_failed");
        for(size_t index = 0; index < tree.Count(); ++index)
            appendOuterNode(collection, *tree.Child(index));
    }

    collection.geometry_offsets.push_back(collection.polygon_offsets.size() - 1);
    collection.rgba.insert(collection.rgba.end(),
                           geometry.rgba.begin(), geometry.rgba.end());
    collection.draw_indices.push_back(geometry.draw_index);
    collection.source_indices.push_back(geometry.source_index);
    collection.source_kinds.push_back(
        static_cast<int32_t>(geometry.source_kind));
}

bool offsetsAreValid(const std::vector<uint64_t>& offsets,
                     uint64_t terminal)
{
    return !offsets.empty()
        && offsets.front() == 0
        && offsets.back() == terminal
        && std::is_sorted(offsets.begin(), offsets.end());
}

bool collectionLayoutIsValid(const GeometryCollection& collection)
{
    if(collection.coordinates.size() % 2 != 0
            || collection.ring_offsets.empty()
            || collection.polygon_offsets.empty()
            || collection.geometry_offsets.empty())
        return false;
    const uint64_t pointCount = collection.coordinates.size() / 2;
    const uint64_t ringCount = collection.ring_offsets.size() - 1;
    const uint64_t polygonCount = collection.polygon_offsets.size() - 1;
    const uint64_t geometryCount = collection.geometryCount();
    if(!offsetsAreValid(collection.ring_offsets, pointCount)
            || !offsetsAreValid(collection.polygon_offsets, ringCount)
            || !offsetsAreValid(collection.geometry_offsets, polygonCount)
            || collection.hole_parent.size() != ringCount
            || collection.rgba.size() != geometryCount * 4
            || collection.draw_indices.size() != geometryCount
            || collection.source_indices.size() != geometryCount
            || collection.source_kinds.size() != geometryCount)
        return false;

    for(size_t index = 1; index < collection.ring_offsets.size(); ++index) {
        const uint64_t begin = collection.ring_offsets[index - 1];
        const uint64_t end = collection.ring_offsets[index];
        if(end - begin < 4)
            return false;
        const size_t first = static_cast<size_t>(begin * 2);
        const size_t last = static_cast<size_t>((end - 1) * 2);
        if(collection.coordinates[first] != collection.coordinates[last]
                || collection.coordinates[first + 1]
                    != collection.coordinates[last + 1])
            return false;
    }
    for(size_t index = 1; index < collection.polygon_offsets.size(); ++index) {
        if(collection.polygon_offsets[index]
                == collection.polygon_offsets[index - 1])
            return false;
    }
    for(size_t index = 0; index < collection.hole_parent.size(); ++index) {
        const int64_t parent = collection.hole_parent[index];
        if(parent < -1 || parent >= static_cast<int64_t>(index))
            return false;
    }
    return true;
}

bool materialCensusMatches(const GeometryCollection& collection,
                           const std::vector<PaintGeometry>& paints)
{
    if(collection.geometryCount() != paints.size())
        return false;
    for(size_t index = 0; index < paints.size(); ++index) {
        const auto& paint = paints[index];
        if(!std::equal(
                paint.rgba.begin(), paint.rgba.end(),
                collection.rgba.begin() + static_cast<ptrdiff_t>(index * 4))
                || collection.draw_indices[index] != paint.draw_index
                || collection.source_indices[index] != paint.source_index
                || collection.source_kinds[index]
                    != static_cast<int32_t>(paint.source_kind))
            return false;
    }
    return true;
}

bool resultCensusIsValid(const NativeResult& result,
                         const std::vector<PaintGeometry>& paints)
{
    return collectionLayoutIsValid(result.raw)
        && collectionLayoutIsValid(result.visible)
        && collectionLayoutIsValid(result.silhouette)
        && materialCensusMatches(result.raw, paints)
        && materialCensusMatches(result.visible, paints)
        && result.silhouette.geometryCount() == 1
        && result.silhouette.componentCount() > 0
        && result.silhouette.rgba
            == std::vector<uint8_t>({0, 0, 0, 255})
        && result.silhouette.draw_indices == std::vector<int32_t>({0})
        && result.silhouette.source_indices == std::vector<int32_t>({-1})
        && result.silhouette.source_kinds == std::vector<int32_t>({
            static_cast<int32_t>(SourceKind::Silhouette)});
}

struct CompositedPaths {
    std::vector<Paths64> visible;
    Paths64 silhouette;
};

uint64_t pathsFingerprint(const Paths64& paths)
{
    constexpr uint64_t FNV_OFFSET = 1469598103934665603ULL;
    constexpr uint64_t FNV_PRIME = 1099511628211ULL;
    uint64_t fingerprint = FNV_OFFSET;
    auto include = [&](uint64_t value) {
        fingerprint ^= value;
        fingerprint *= FNV_PRIME;
    };
    include(paths.size());
    for(const auto& path : paths) {
        include(path.size());
        for(const auto& point : path) {
            include(static_cast<uint64_t>(point.x));
            include(static_cast<uint64_t>(point.y));
        }
    }
    return fingerprint;
}

bool hasExactLaterPaint(
    const std::unordered_multimap<uint64_t, size_t>& fingerprints,
    const std::vector<PaintGeometry>& paints, size_t paintIndex,
    uint64_t fingerprint)
{
    const auto range = fingerprints.equal_range(fingerprint);
    for(auto iterator = range.first; iterator != range.second; ++iterator) {
        if(paints[iterator->second].paths == paints[paintIndex].paths)
            return true;
    }
    return false;
}

CompositedPaths compositePaints(const std::vector<PaintGeometry>& paints)
{
    CompositedPaths composited;
    composited.visible.resize(paints.size());
    const PackedBoundsIndex boundsIndex(paints);
    std::unordered_multimap<uint64_t, size_t> laterFingerprints;
    laterFingerprints.reserve(paints.size());
    for(size_t reverseIndex = paints.size(); reverseIndex > 0; --reverseIndex) {
        const size_t index = reverseIndex - 1;
        const uint64_t fingerprint = pathsFingerprint(paints[index].paths);
        if(hasExactLaterPaint(
                laterFingerprints, paints, index, fingerprint)) {
            composited.visible[index] = {};
        } else {
            const auto overlaps = boundsIndex.laterOverlaps(index);
            if(overlaps.empty()) {
                composited.visible[index] = paints[index].paths;
            } else {
                Paths64 laterOverlaps;
                for(const size_t overlapIndex : overlaps) {
                    const auto& paths = paints[overlapIndex].paths;
                    laterOverlaps.insert(
                        laterOverlaps.end(), paths.begin(), paths.end());
                }
                composited.visible[index] = Clipper2Lib::Difference(
                    paints[index].paths,
                    laterOverlaps,
                    FillRule::NonZero);
            }
        }
        laterFingerprints.emplace(fingerprint, index);
    }

    Paths64 allPaints;
    for(const auto& paint : paints) {
        allPaints.insert(
            allPaints.end(), paint.paths.begin(), paint.paths.end());
    }
    composited.silhouette = Clipper2Lib::Union(
        allPaints, FillRule::NonZero);
    return composited;
}

std::shared_ptr<NativeResult> buildResult(RecorderResult recording,
                                          double targetWidthMm,
                                          double toleranceMm)
{
    auto result = std::make_shared<NativeResult>();
    result->image_vectorizer_origin = recording.image_vectorizer_origin;
    if(!isPositiveFinite(targetWidthMm) || !isPositiveFinite(toleranceMm)) {
        result->reason_code = "invalid_physical_parameters";
        return result;
    }
    if(recording.status != "supported") {
        result->status = recording.status;
        result->reason_code = recording.reason_code;
        return result;
    }
    result->max_flattening_error_mm = toleranceMm * 0.4;
    auto sourceBounds = exactPaintBounds(recording.commands);
    includeViewport(sourceBounds, recording.viewport);
    if(!sourceBounds.valid()) {
        result->reason_code = "empty_geometry";
        return result;
    }

    const bool hasClipCommands = std::any_of(
        recording.commands.begin(), recording.commands.end(),
        [](const lunasvg::PaintCommand& command) {
            return command.kind == lunasvg::PaintCommandKind::ClipBegin;
        });
    const bool hasStrokeCommands = std::any_of(
        recording.commands.begin(), recording.commands.end(),
        [](const lunasvg::PaintCommand& command) {
            return command.kind == lunasvg::PaintCommandKind::Stroke;
        });
    const double finalFlatteningBudgetMm = toleranceMm
        * (hasClipCommands ? 0.35 : 0.4);
    const double finalQuantizationBudgetMm = toleranceMm
        * (hasClipCommands ? 0.05 : 0.15);
    const double strokeQuantizationBudgetMm = toleranceMm * 0.05;
    const double budgetGridStepMm = finalQuantizationBudgetMm
        * std::sqrt(2.0);
    const auto boundsPlan = buildClipBoundsPlan(recording.commands);
    if(hasClipCommands) {
        if(!boundsPlan.coordinate_bounds.valid()
                || !boundsPlan.clipped_paint_bounds.valid()) {
            result->status = "unsupported";
            result->reason_code = "unsupported_clipped_geometry";
            return result;
        }
        const double coordinateWidth =
            boundsPlan.coordinate_bounds.max_x
            - boundsPlan.coordinate_bounds.min_x;
        const double coordinateHeight =
            boundsPlan.coordinate_bounds.max_y
            - boundsPlan.coordinate_bounds.min_y;
        const double coordinateSpan = std::max(
            coordinateWidth, coordinateHeight);
        const double coordinateMagnitude = std::max({
            1.0,
            std::abs(boundsPlan.coordinate_bounds.min_x),
            std::abs(boundsPlan.coordinate_bounds.min_y),
            std::abs(boundsPlan.coordinate_bounds.max_x),
            std::abs(boundsPlan.coordinate_bounds.max_y),
        });
        const double sizingGridStep = std::max(
            coordinateSpan / 1.0e13,
            coordinateMagnitude
                * std::numeric_limits<double>::epsilon() * 16.0);
        if(!isPositiveFinite(sizingGridStep)
                || !std::isfinite(boundsPlan.minimum_paint_extent)
                || sizingGridStep * 4096.0
                    > boundsPlan.minimum_paint_extent) {
            result->status = "unsupported";
            result->reason_code = "unsupported_clip_dynamic_range";
            return result;
        }
        // The sizing pass only derives a conservative scale upper bound for
        // the budgeted bounds pass. It never contributes coordinates or a
        // bbox to the returned result.
        const PhysicalDomain sizingDomain{
            boundsPlan.coordinate_bounds.min_x,
            boundsPlan.coordinate_bounds.min_y,
            1.0,
            sizingGridStep,
            sizingGridStep,
            sizingGridStep / std::sqrt(2.0),
        };
        auto sizingReplay = replayPaintCommands(
            recording.commands, sizingDomain);
        if(!sizingReplay.reason_code.empty()) {
            result->reason_code = sizingReplay.reason_code;
            return result;
        }
        if(sizingReplay.paints.size() != boundsPlan.paint_bounds.size()) {
            result->reason_code = "native_geometry_error";
            return result;
        }
        if(!hasNonEmptyPaint(sizingReplay.paints)) {
            result->status = "unsupported";
            result->reason_code = "unsupported_clipped_geometry";
            return result;
        }
        const auto sizingBounds = sourceBoundsForPaints(
            sizingReplay.paints, sizingDomain);
        const double sizingBoundaryError = sizingGridStep
            * (2.0 + std::sqrt(2.0));
        const double sizingWidthLowerBound =
            sizingBounds.max_x - sizingBounds.min_x
            - 2.0 * sizingBoundaryError;
        if(!isPositiveFinite(sizingWidthLowerBound)) {
            result->status = "unsupported";
            result->reason_code = "unsupported_clip_dynamic_range";
            return result;
        }
        const double boundsScaleUpperBound =
            targetWidthMm / sizingWidthLowerBound;
        const double boundsFlatteningBudgetMm = toleranceMm * 0.05;
        const double boundsGridQuantizationBudgetMm = toleranceMm * 0.03;
        const double boundsStrokeQuantizationBudgetMm = toleranceMm * 0.02;
        const double boundsGridStepMm =
            boundsGridQuantizationBudgetMm * std::sqrt(2.0);
        if(!isPositiveFinite(boundsScaleUpperBound)
                || coordinateSpan * boundsScaleUpperBound / boundsGridStepMm
                    > 1.0e15) {
            result->status = "unsupported";
            result->reason_code = "unsupported_clip_dynamic_range";
            return result;
        }
        const PhysicalDomain boundsDomain{
            boundsPlan.coordinate_bounds.min_x,
            boundsPlan.coordinate_bounds.min_y,
            boundsScaleUpperBound,
            boundsGridStepMm,
            boundsFlatteningBudgetMm,
            boundsStrokeQuantizationBudgetMm,
        };
        auto boundsReplay = replayPaintCommands(
            recording.commands, boundsDomain);
        if(!boundsReplay.reason_code.empty()) {
            result->reason_code = boundsReplay.reason_code;
            return result;
        }
        if(boundsReplay.paints.size() != boundsPlan.paint_bounds.size()) {
            result->reason_code = "native_geometry_error";
            return result;
        }
        for(size_t index = 0; index < boundsReplay.paints.size(); ++index) {
            if(boundsPlan.paint_bounds[index].valid()
                    && boundsReplay.paints[index].paths.empty()) {
                result->status = "unsupported";
                result->reason_code = "unsupported_clipped_geometry";
                return result;
            }
        }
        if(!hasNonEmptyPaint(boundsReplay.paints)) {
            result->status = "unsupported";
            result->reason_code = "unsupported_clipped_geometry";
            return result;
        }
        auto compensatedBounds = sourceBoundsForPaints(
            boundsReplay.paints, boundsDomain);
        const double boundsBoundaryBudgetMm = boundsFlatteningBudgetMm
            + boundsGridQuantizationBudgetMm
            + (hasStrokeCommands ? boundsStrokeQuantizationBudgetMm : 0.0);
        const double boundsBoundaryBudgetSource =
            boundsBoundaryBudgetMm / boundsScaleUpperBound;
        compensatedBounds.min_x -= boundsBoundaryBudgetSource;
        compensatedBounds.min_y -= boundsBoundaryBudgetSource;
        compensatedBounds.max_x += boundsBoundaryBudgetSource;
        compensatedBounds.max_y += boundsBoundaryBudgetSource;
        sourceBounds = compensatedBounds.intersected(
            boundsPlan.clipped_paint_bounds);
        includeViewport(sourceBounds, recording.viewport);
        if(!sourceBounds.valid()) {
            result->reason_code = "empty_geometry";
            return result;
        }
    }

    const double sourceWidth = sourceBounds.max_x - sourceBounds.min_x;
    const double sourceHeight = sourceBounds.max_y - sourceBounds.min_y;
    result->bbox = {{sourceBounds.min_x, sourceBounds.min_y,
                     sourceWidth, sourceHeight}};
    if(isPositiveFinite(recording.viewport.w)
            && isPositiveFinite(recording.viewport.h)) {
        result->viewport_bounds = {{
            recording.viewport.x - sourceBounds.min_x,
            recording.viewport.y - sourceBounds.min_y,
            recording.viewport.w,
            recording.viewport.h,
        }};
    }
    result->scale_factor = targetWidthMm / sourceWidth;
    const double coordinateDistance = std::max({
        std::abs(boundsPlan.coordinate_bounds.min_x - sourceBounds.min_x),
        std::abs(boundsPlan.coordinate_bounds.max_x - sourceBounds.min_x),
        std::abs(boundsPlan.coordinate_bounds.min_y - sourceBounds.min_y),
        std::abs(boundsPlan.coordinate_bounds.max_y - sourceBounds.min_y),
    });
    constexpr double TARGET_GRID_CELLS = 1.0e12;
    constexpr double SAFE_GRID_COORDINATE = 5.0e14;
    const double precisionGridStepMm = targetWidthMm / TARGET_GRID_CELLS;
    const double rangeGridStepMm = coordinateDistance
        * result->scale_factor / SAFE_GRID_COORDINATE;
    const double gridStepMm = std::max(
        precisionGridStepMm, rangeGridStepMm);
    if(!isPositiveFinite(gridStepMm)
            || gridStepMm > budgetGridStepMm) {
        result->status = "unsupported";
        result->reason_code = "unsupported_topology_dynamic_range";
        return result;
    }
    result->max_quantization_error_mm = gridStepMm / std::sqrt(2.0);
    result->grid_to_source_unit = gridStepMm / result->scale_factor;
    TopologyTrace topologyTrace;
    const PhysicalDomain domain{
        sourceBounds.min_x,
        sourceBounds.min_y,
        result->scale_factor,
        gridStepMm,
        finalFlatteningBudgetMm,
        strokeQuantizationBudgetMm,
        &topologyTrace,
    };

    auto replay = replayPaintCommands(recording.commands, domain);
    if(!replay.reason_code.empty()) {
        result->reason_code = replay.reason_code;
        return result;
    }
    if(!hasNonEmptyPaint(replay.paints)) {
        result->reason_code = "empty_geometry";
        return result;
    }
    auto paints = std::move(replay.paints);
    const double maximumBoundaryErrorMm =
        maximumRelevantBoundaryErrorSource(
            topologyTrace, sourceBounds, recording.viewport)
            * result->scale_factor
        + result->max_quantization_error_mm;
    if(!std::isfinite(maximumBoundaryErrorMm)
            || maximumBoundaryErrorMm > toleranceMm * 0.6) {
        result->status = "unsupported";
        result->reason_code = "unsupported_input_precision";
        return result;
    }
    const SourceSegmentIndex topologyIndex(topologyTrace.segments);
    if(topologyIndex.hasUnstableSegments(
            result->max_quantization_error_mm / result->scale_factor,
            toleranceMm * 0.6 / result->scale_factor,
            toleranceMm / result->scale_factor,
            toleranceMm / result->scale_factor)) {
        result->status = "unsupported";
        result->reason_code = "unsupported_topology_collapse";
        return result;
    }
    const auto finalComposite = compositePaints(paints);

    for(const auto& paint : paints)
        appendGeometry(result->raw, paint);

    for(size_t index = 0; index < paints.size(); ++index) {
        auto visible = paints[index];
        visible.paths = finalComposite.visible[index];
        appendGeometry(result->visible, visible);
    }

    PaintGeometry silhouette;
    silhouette.paths = finalComposite.silhouette;
    silhouette.bounds = pathsBounds(silhouette.paths);
    silhouette.rgba = {{0, 0, 0, 255}};
    silhouette.draw_index = 0;
    silhouette.source_index = -1;
    silhouette.source_kind = SourceKind::Silhouette;
    appendGeometry(result->silhouette, silhouette);

    if(!resultCensusIsValid(*result, paints))
        throw std::runtime_error("native_result_census_failed");

    result->status = "supported";
    result->reason_code.clear();
    return result;
}

template<typename Loader>
std::shared_ptr<NativeResult> analyzeWith(Loader&& loader,
                                          double targetWidthMm,
                                          double toleranceMm,
                                          bool allowStrokes)
{
    if(!isPositiveFinite(targetWidthMm) || !isPositiveFinite(toleranceMm)) {
        auto result = std::make_shared<NativeResult>();
        result->reason_code = "invalid_physical_parameters";
        return result;
    }
    try {
        const auto recorderStarted = std::chrono::steady_clock::now();
        auto recording = loader();
        const auto recorderFinished = std::chrono::steady_clock::now();
        if(allowStrokes && recording.status == "supported"
                && std::any_of(
                    recording.commands.begin(), recording.commands.end(),
                    [](const lunasvg::PaintCommand& command) {
                        return command.kind
                                == lunasvg::PaintCommandKind::Stroke
                            && std::any_of(
                                command.stroke.dash_array.begin(),
                                command.stroke.dash_array.end(),
                                [](float value) {
                                    return std::abs(value)
                                        <= std::numeric_limits<float>::epsilon();
                                });
                    })) {
            auto result = std::make_shared<NativeResult>();
            result->status = "unsupported";
            result->reason_code = "unsupported_zero_length_dash";
            result->recorder_seconds = std::chrono::duration<double>(
                recorderFinished - recorderStarted).count();
            return result;
        }
        if(!allowStrokes && recording.status == "supported"
                && std::any_of(
                    recording.commands.begin(), recording.commands.end(),
                    [](const lunasvg::PaintCommand& command) {
                        return command.kind
                            == lunasvg::PaintCommandKind::Stroke;
                    })) {
            auto result = std::make_shared<NativeResult>();
            result->status = "unsupported";
            result->reason_code = "unsupported_stroke_policy";
            const auto kernelFinished = std::chrono::steady_clock::now();
            result->recorder_seconds = std::chrono::duration<double>(
                recorderFinished - recorderStarted).count();
            result->kernel_seconds = std::chrono::duration<double>(
                kernelFinished - recorderFinished).count();
            return result;
        }
        auto result = buildResult(
            std::move(recording), targetWidthMm, toleranceMm);
        const auto kernelFinished = std::chrono::steady_clock::now();
        result->recorder_seconds = std::chrono::duration<double>(
            recorderFinished - recorderStarted).count();
        result->kernel_seconds = std::chrono::duration<double>(
            kernelFinished - recorderFinished).count();
        return result;
    } catch(const TopologyCollapseError&) {
        auto result = std::make_shared<NativeResult>();
        result->status = "unsupported";
        result->reason_code = "unsupported_topology_collapse";
        return result;
    } catch(const InputPrecisionError&) {
        auto result = std::make_shared<NativeResult>();
        result->status = "unsupported";
        result->reason_code = "unsupported_input_precision";
        return result;
    } catch(const std::range_error&) {
        auto result = std::make_shared<NativeResult>();
        result->reason_code = "numeric_range_error";
        return result;
    } catch(const std::bad_alloc&) {
        auto result = std::make_shared<NativeResult>();
        result->reason_code = "allocation_failed";
        return result;
    } catch(const std::exception&) {
        auto result = std::make_shared<NativeResult>();
        result->reason_code = "native_geometry_error";
        return result;
    }
}

} // namespace

std::shared_ptr<NativeResult> analyzeSvg(const std::string& filename,
                                         double targetWidthMm,
                                         double toleranceMm,
                                         bool allowStrokes)
{
    return analyzeSvgPath(
        std::filesystem::u8path(filename),
        targetWidthMm, toleranceMm, allowStrokes);
}

std::shared_ptr<NativeResult> analyzeSvgPath(
    const std::filesystem::path& filename,
    double targetWidthMm,
    double toleranceMm,
    bool allowStrokes)
{
    return analyzeWith(
        [&filename]() { return recordPaintCommandsPath(filename); },
        targetWidthMm, toleranceMm, allowStrokes);
}

std::shared_ptr<NativeResult> analyzeSvgData(const std::string& svg,
                                             double targetWidthMm,
                                             double toleranceMm,
                                             bool allowStrokes)
{
    return analyzeWith(
        [&svg]() { return recordPaintCommandsSvg(svg); },
        targetWidthMm, toleranceMm, allowStrokes);
}

} // namespace lumina_svg_core
