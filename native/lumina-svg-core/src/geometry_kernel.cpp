#include "lumina_svg_core/geometry_kernel.h"

#include "canonical_boundary.h"
#include "complexity_budget.h"
#include "clipper_safety.h"
#include "lumina_svg_core/paint_command.h"
#include "lumina_svg_core/stroke_expander.h"

#include <clipper2/clipper.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <limits>
#include <memory>
#include <numeric>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <system_error>
#include <thread>
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

struct SourceBoundarySegment {
    PointD start;
    PointD control1;
    PointD control2;
    PointD end;
    bool cubic{false};
};

struct TopologyTrace {
    struct BoundaryError {
        double min_x{0};
        double min_y{0};
        double max_x{0};
        double max_y{0};
        double maximum_error_source{0};
    };

    std::vector<BoundaryError> boundaries;

    void append(BoundaryError boundary)
    {
        boundaries.emplace_back(std::move(boundary));
    }
};

struct PhysicalDomain {
    double bbox_x{0};
    double bbox_y{0};
    double source_to_mm{0};
    double grid_step_mm{0};
    double flatten_budget_mm{0};
    double stroke_quantization_budget_mm{0};
    TopologyTrace* topology_trace{nullptr};
    ComplexityBudget* complexity_budget{nullptr};
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

struct PaintContributor {
    int32_t draw_index{-1};
    int32_t source_index{-1};
    SourceKind source_kind{SourceKind::Fill};
    double weight{0};
};

struct PaintGeometry {
    Paths64 paths;
    std::vector<Paths64> components;
    GridBounds bounds;
    double boundary_error_source{0};
    double input_precision_error_x_source{0};
    double input_precision_error_y_source{0};
    std::array<uint8_t, 4> rgba{{0, 0, 0, 0}};
    std::array<double, 4> rgba_f64{{0, 0, 0, 0}};
    int32_t draw_index{-1};
    int32_t source_index{-1};
    SourceKind source_kind{SourceKind::Fill};
    std::vector<PaintContributor> contributors;
};

struct FragmentIssue {
    UnprintableReason reason{UnprintableReason::EmptyPath};
    int32_t subpath_index{-1};
};

struct PrecisionPaths {
    Paths64 paths;
    double boundary_error_source{0};
    double input_precision_error_x_source{0};
    double input_precision_error_y_source{0};
    std::vector<FragmentIssue> fragment_issues;
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

std::vector<GridBounds> individualPathBounds(const Paths64& paths)
{
    std::vector<GridBounds> bounds;
    bounds.reserve(paths.size());
    for(const auto& path : paths) {
        GridBounds pathBounds;
        for(const auto& point : path)
            pathBounds.include(point);
        bounds.emplace_back(pathBounds);
    }
    return bounds;
}

size_t pathPointCount(const Paths64& paths)
{
    return clipperPathPointCount(paths);
}

void consumeBooleanInputs(ComplexityBudget& complexityBudget,
                          const Paths64& first,
                          const Paths64* second = nullptr)
{
    size_t count = pathPointCount(first);
    if(second != nullptr)
        count = checkedSizeSum(count, pathPointCount(*second));
    complexityBudget.consumeBooleanInputPoints(count);
}

void consumeClipperOutput(ComplexityBudget& complexityBudget,
                          const Paths64& paths)
{
    complexityBudget.consumeClipperOutputPoints(pathPointCount(paths));
    complexityBudget.consumeClipperOutputRings(paths.size());
}

Paths64 executeClipperBoolean(ClipType clipType, FillRule fillRule,
                              const Paths64& subjects,
                              const Paths64* clips,
                              ComplexityBudget& complexityBudget)
{
    size_t inputPointCount = pathPointCount(subjects);
    if(clips != nullptr) {
        inputPointCount = checkedSizeSum(
            inputPointCount, pathPointCount(*clips));
    }
    Paths64 result;
    Clipper64 clipper;
    clipper.AddSubject(subjects);
    if(clips != nullptr)
        clipper.AddClip(*clips);
    if(!clipper.Execute(clipType, fillRule, result))
        throw std::runtime_error("clipper_boolean_failed");
    return result;
}

void preflightBoolean(ComplexityBudget& complexityBudget,
                      const Paths64& paths)
{
    consumeBooleanInputs(complexityBudget, paths);
}

void preflightBoolean(ComplexityBudget& complexityBudget,
                      const Paths64& first,
                      const Paths64& second)
{
    consumeBooleanInputs(complexityBudget, first, &second);
}

void preflightNormalizedBoolean(ComplexityBudget& complexityBudget,
                                const Paths64& paths)
{
    consumeBooleanInputs(complexityBudget, paths);
}

void preflightNormalizedBoolean(ComplexityBudget& complexityBudget,
                                const Paths64& first,
                                const Paths64& second)
{
    consumeBooleanInputs(complexityBudget, first, &second);
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
        size_t paintIndex, ComplexityBudget& complexityBudget) const
    {
        std::vector<size_t> matches;
        if(m_nodes.empty() || !m_paints[paintIndex].bounds.valid)
            return matches;
        queryNode(
            0, paintIndex, m_paints[paintIndex].bounds,
            complexityBudget, matches);
        return matches;
    }

    bool hasLaterOverlap(
        size_t paintIndex, ComplexityBudget& complexityBudget) const
    {
        if(m_nodes.empty() || !m_paints[paintIndex].bounds.valid)
            return false;
        return queryAnyNode(
            0, paintIndex, m_paints[paintIndex].bounds,
            complexityBudget);
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
                   const GridBounds& query,
                   ComplexityBudget& complexityBudget,
                   std::vector<size_t>& matches) const
    {
        const auto& node = m_nodes[nodeIndex];
        if(!node.bounds.intersects(query))
            return;
        if(node.leaf) {
            for(size_t offset = node.begin; offset < node.end; ++offset) {
                const size_t candidate = m_indices[offset];
                if(candidate <= paintIndex)
                    continue;
                complexityBudget.consumeCompositorBoundsCandidates();
                if(m_paints[candidate].bounds.intersects(query))
                    matches.push_back(candidate);
            }
            return;
        }
        queryNode(
            node.left, paintIndex, query, complexityBudget, matches);
        queryNode(
            node.right, paintIndex, query, complexityBudget, matches);
    }

    bool queryAnyNode(size_t nodeIndex, size_t paintIndex,
                      const GridBounds& query,
                      ComplexityBudget& complexityBudget) const
    {
        const auto& node = m_nodes[nodeIndex];
        if(!node.bounds.intersects(query))
            return false;
        if(node.leaf) {
            for(size_t offset = node.begin; offset < node.end; ++offset) {
                const size_t candidate = m_indices[offset];
                if(candidate <= paintIndex)
                    continue;
                complexityBudget.consumeCompositorBoundsCandidates();
                if(m_paints[candidate].bounds.intersects(query))
                    return true;
            }
            return false;
        }
        return queryAnyNode(
                   node.left, paintIndex, query, complexityBudget)
            || queryAnyNode(
                   node.right, paintIndex, query, complexityBudget);
    }

    const std::vector<PaintGeometry>& m_paints;
    std::vector<size_t> m_indices;
    std::vector<Node> m_nodes;
};

class PackedGridBoundsIndex {
public:
    explicit PackedGridBoundsIndex(std::vector<GridBounds> bounds)
        : m_bounds(std::move(bounds))
    {
        m_indices.reserve(m_bounds.size());
        for(size_t index = 0; index < m_bounds.size(); ++index) {
            if(m_bounds[index].valid)
                m_indices.push_back(index);
        }
        if(!m_indices.empty())
            buildNode(0, m_indices.size());
    }

    bool intersects(const GridBounds& query,
                    ComplexityBudget& complexityBudget) const
    {
        return !m_nodes.empty()
            && queryNode(0, query, complexityBudget);
    }

    std::vector<size_t> matches(
        const GridBounds& query,
        ComplexityBudget& complexityBudget) const
    {
        std::vector<size_t> matches;
        if(!m_nodes.empty())
            queryMatches(0, query, complexityBudget, matches);
        return matches;
    }

    std::vector<GridBounds> releaseBounds()
    {
        m_indices.clear();
        m_nodes.clear();
        return std::move(m_bounds);
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
            bounds.include(m_bounds[m_indices[offset]]);
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
                const auto& leftBounds = m_bounds[left];
                const auto& rightBounds = m_bounds[right];
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

    bool queryNode(size_t nodeIndex, const GridBounds& query,
                   ComplexityBudget& complexityBudget) const
    {
        const auto& node = m_nodes[nodeIndex];
        if(!node.bounds.intersects(query))
            return false;
        if(node.leaf) {
            for(size_t offset = node.begin; offset < node.end; ++offset) {
                complexityBudget.consumeCompositorBoundsCandidates();
                if(m_bounds[m_indices[offset]].intersects(query))
                    return true;
            }
            return false;
        }
        return queryNode(node.left, query, complexityBudget)
            || queryNode(node.right, query, complexityBudget);
    }

    void queryMatches(size_t nodeIndex, const GridBounds& query,
                      ComplexityBudget& complexityBudget,
                      std::vector<size_t>& matches) const
    {
        const auto& node = m_nodes[nodeIndex];
        if(!node.bounds.intersects(query))
            return;
        if(node.leaf) {
            for(size_t offset = node.begin; offset < node.end; ++offset) {
                const size_t candidate = m_indices[offset];
                complexityBudget.consumeCompositorBoundsCandidates();
                if(m_bounds[candidate].intersects(query))
                    matches.push_back(candidate);
            }
            return;
        }
        queryMatches(
            node.left, query, complexityBudget, matches);
        queryMatches(
            node.right, query, complexityBudget, matches);
    }

    std::vector<GridBounds> m_bounds;
    std::vector<size_t> m_indices;
    std::vector<Node> m_nodes;
};

bool pathBoundsIntersectAcross(const Paths64& first,
                               const Paths64& second,
                               ComplexityBudget& complexityBudget)
{
    if(first.empty() || second.empty())
        return false;
    auto firstBounds = individualPathBounds(first);
    auto secondBounds = individualPathBounds(second);
    const auto* queries = &firstBounds;
    auto* indexed = &secondBounds;
    if(firstBounds.size() > secondBounds.size()) {
        queries = &secondBounds;
        indexed = &firstBounds;
    }
    const PackedGridBoundsIndex index(std::move(*indexed));
    for(const auto& query : *queries) {
        if(index.intersects(query, complexityBudget))
            return true;
    }
    return false;
}

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

    bool finiteExtent() const
    {
        return std::isfinite(min_x) && std::isfinite(min_y)
            && std::isfinite(max_x) && std::isfinite(max_y)
            && max_x >= min_x && max_y >= min_y;
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

    void includeFiniteExtent(const SourceBounds& other)
    {
        if(!other.finiteExtent())
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

class InputPrecisionError : public std::runtime_error {
public:
    explicit InputPrecisionError(const char* detail = "input_precision")
        : std::runtime_error(detail)
    {}

};

bool isPositiveFinite(double value)
{
    return std::isfinite(value) && value > 0;
}

double maximumSingularValue(const lunasvg::PaintTransform& matrix)
{
    const double aa = matrix.a * matrix.a + matrix.b * matrix.b;
    const double bb = matrix.c * matrix.c + matrix.d * matrix.d;
    const double cross = matrix.a * matrix.c + matrix.b * matrix.d;
    const double discriminant = std::sqrt(
        std::max(0.0, (aa - bb) * (aa - bb) + 4.0 * cross * cross));
    return std::sqrt(std::max(0.0, (aa + bb + discriminant) * 0.5));
}

PointD transformPoint(const lunasvg::PaintTransform& matrix,
                      const PointD& point)
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

double storedDoubleUlp(double value)
{
    if(!std::isfinite(value))
        return std::numeric_limits<double>::infinity();
    const double upward = std::nextafter(
        value, std::numeric_limits<double>::infinity());
    const double downward = std::nextafter(
        value, -std::numeric_limits<double>::infinity());
    return std::max(upward - value, value - downward);
}

bool isIdentityMatrix(const lunasvg::PaintTransform& matrix)
{
    return matrix.a == 1.0f && matrix.b == 0.0f
        && matrix.c == 0.0f && matrix.d == 1.0f
        && matrix.e == 0.0f && matrix.f == 0.0f;
}

struct CoordinatePrecisionError {
    double x{0};
    double y{0};
};

CoordinatePrecisionError pathInputPrecisionError(
    const lunasvg::PaintCommand& command)
{
    const bool hasAxisMetadata =
        command.path_input_precision_error_x > 0.0
        || command.path_input_precision_error_y > 0.0;
    if(hasAxisMetadata) {
        return {
            command.path_input_precision_error_x,
            command.path_input_precision_error_y,
        };
    }
    return {
        command.path_input_precision_error,
        command.path_input_precision_error,
    };
}

struct StrokePathMetrics {
    double maximum_length{0};
    double maximum_length_error{0};
};

double localPointPrecisionMagnitude(
    const lunasvg::PaintCommand& command,
    const PointD& point)
{
    constexpr double operationUlps = 4.0;
    const auto inputError = pathInputPrecisionError(command);
    return std::hypot(
        (command.path_coordinates_exact
                ? 0.0
                : floatUlp(static_cast<float>(point.x)) * operationUlps)
            + inputError.x,
        (command.path_coordinates_exact
                ? 0.0
                : floatUlp(static_cast<float>(point.y)) * operationUlps)
            + inputError.y);
}

struct StrokePrecisionSegment {
    PointD start;
    PointD end;
    PointD start_tangent_point;
    PointD end_tangent_point;
};

bool distinctPoints(const PointD& first, const PointD& second)
{
    return first.x != second.x || first.y != second.y;
}

double strokeInputPrecisionAmplification(
    const lunasvg::PaintCommand& command)
{
    constexpr double POSITION_SAFETY = 16.0;
    const double radius = std::abs(
        static_cast<double>(command.stroke.width)) * 0.5;
    const double limitError = storedDoubleUlp(
        command.stroke.miter_limit) * 4.0;
    const double maximumLimit = std::max(
        1.0, static_cast<double>(command.stroke.miter_limit) + limitError);
    const double threshold = maximumLimit <= 1.0
        ? 1.0 : 2.0 / (maximumLimit * maximumLimit) - 1.0;
    double amplification = 1.0;
    std::vector<StrokePrecisionSegment> segments;
    PointD current;
    PointD subpathStart;
    bool hasCurrentPoint = false;
    size_t pointIndex = 0;

    const auto includeSegmentDirection = [&](const StrokePrecisionSegment& segment) {
        const double startLength = std::hypot(
            segment.start_tangent_point.x - segment.start.x,
            segment.start_tangent_point.y - segment.start.y);
        const double endLength = std::hypot(
            segment.end.x - segment.end_tangent_point.x,
            segment.end.y - segment.end_tangent_point.y);
        const double minimumLength = std::min(startLength, endLength);
        if(!(std::isfinite(minimumLength) && minimumLength > 0.0))
            return;
        const double candidate = 1.0
            + POSITION_SAFETY * radius / minimumLength;
        if(!std::isfinite(candidate))
            throw InputPrecisionError("stroke_direction_precision");
        amplification = std::max(amplification, candidate);
    };
    const auto includeJoin = [&](const StrokePrecisionSegment& incoming,
                                 const StrokePrecisionSegment& outgoing) {
        if(command.stroke.line_join != lunasvg::PaintLineJoin::Miter)
            return;
        const double incomingX = incoming.end.x
            - incoming.end_tangent_point.x;
        const double incomingY = incoming.end.y
            - incoming.end_tangent_point.y;
        const double outgoingX = outgoing.start_tangent_point.x
            - outgoing.start.x;
        const double outgoingY = outgoing.start_tangent_point.y
            - outgoing.start.y;
        const double incomingLength = std::hypot(incomingX, incomingY);
        const double outgoingLength = std::hypot(outgoingX, outgoingY);
        if(!(std::isfinite(incomingLength) && incomingLength > 0.0)
                || !(std::isfinite(outgoingLength)
                    && outgoingLength > 0.0))
            return;
        const double cosine = std::clamp(
            (incomingX * outgoingX + incomingY * outgoingY)
                / (incomingLength * outgoingLength),
            -1.0, 1.0);
        if(cosine <= threshold)
            return;
        const double denominator = 1.0 + cosine;
        if(!(denominator > 0.0))
            throw InputPrecisionError("stroke_miter_precision");
        const double joinRatio = std::min(
            maximumLimit, std::sqrt(2.0 / denominator));
        const double minimumLength = std::min(
            incomingLength, outgoingLength);
        const double candidate = 1.0
            + POSITION_SAFETY * radius * joinRatio * joinRatio
                / minimumLength;
        if(!std::isfinite(candidate))
            throw InputPrecisionError("stroke_miter_precision");
        amplification = std::max(amplification, candidate);
    };
    const auto finishSubpath = [&](bool closed) {
        for(const auto& segment : segments)
            includeSegmentDirection(segment);
        for(size_t index = 1; index < segments.size(); ++index)
            includeJoin(segments[index - 1], segments[index]);
        if(closed && segments.size() > 1)
            includeJoin(segments.back(), segments.front());
        segments.clear();
    };
    const auto appendLine = [&](const PointD& end) {
        if(!hasCurrentPoint)
            return;
        if(distinctPoints(current, end)) {
            segments.push_back({current, end, end, current});
        }
        current = end;
    };

    for(const auto verb : command.path_verbs) {
        switch(verb) {
        case lunasvg::PaintPathVerb::MoveTo: {
            finishSubpath(false);
            const auto& point = command.path_points.at(pointIndex++);
            current = {point.x, point.y};
            subpathStart = current;
            hasCurrentPoint = true;
            break;
        }
        case lunasvg::PaintPathVerb::LineTo: {
            const auto& point = command.path_points.at(pointIndex++);
            appendLine({point.x, point.y});
            break;
        }
        case lunasvg::PaintPathVerb::CubicTo: {
            const auto& first = command.path_points.at(pointIndex++);
            const auto& second = command.path_points.at(pointIndex++);
            const auto& last = command.path_points.at(pointIndex++);
            const PointD control1{first.x, first.y};
            const PointD control2{second.x, second.y};
            const PointD end{last.x, last.y};
            if(hasCurrentPoint && distinctPoints(current, end)) {
                PointD startTangent = distinctPoints(current, control1)
                    ? control1 : (distinctPoints(current, control2)
                        ? control2 : end);
                PointD endTangent = distinctPoints(end, control2)
                    ? control2 : (distinctPoints(end, control1)
                        ? control1 : current);
                segments.push_back({
                    current, end, startTangent, endTangent,
                });
            }
            current = end;
            break;
        }
        case lunasvg::PaintPathVerb::Close:
            appendLine(subpathStart);
            finishSubpath(true);
            current = subpathStart;
            break;
        }
    }
    finishSubpath(false);
    return amplification;
}

StrokePathMetrics strokePathMetrics(const lunasvg::PaintCommand& command)
{
    StrokePathMetrics metrics;
    double subpathLength = 0;
    double subpathLengthError = 0;
    PointD current;
    PointD subpathStart;
    double currentError = 0;
    double subpathStartError = 0;
    bool hasCurrentPoint = false;
    size_t pointIndex = 0;
    auto finishSubpath = [&]() {
        metrics.maximum_length = std::max(
            metrics.maximum_length, subpathLength);
        metrics.maximum_length_error = std::max(
            metrics.maximum_length_error, subpathLengthError);
        subpathLength = 0;
        subpathLengthError = 0;
    };
    auto addLine = [&](const PointD& end, double endError) {
        subpathLength += std::hypot(
            end.x - current.x, end.y - current.y);
        subpathLengthError += currentError + endError;
        current = end;
        currentError = endError;
    };

    for(const auto verb : command.path_verbs) {
        switch(verb) {
        case lunasvg::PaintPathVerb::MoveTo: {
            finishSubpath();
            const auto& point = command.path_points.at(pointIndex++);
            current = {point.x, point.y};
            currentError = localPointPrecisionMagnitude(command, current);
            subpathStart = current;
            subpathStartError = currentError;
            hasCurrentPoint = true;
            break;
        }
        case lunasvg::PaintPathVerb::LineTo: {
            const auto& point = command.path_points.at(pointIndex++);
            const PointD end{point.x, point.y};
            addLine(end, localPointPrecisionMagnitude(command, end));
            break;
        }
        case lunasvg::PaintPathVerb::CubicTo: {
            const auto& first = command.path_points.at(pointIndex++);
            const auto& second = command.path_points.at(pointIndex++);
            const auto& last = command.path_points.at(pointIndex++);
            const PointD control1{first.x, first.y};
            const PointD control2{second.x, second.y};
            const PointD end{last.x, last.y};
            const double control1Error = localPointPrecisionMagnitude(
                command, control1);
            const double control2Error = localPointPrecisionMagnitude(
                command, control2);
            const double endError = localPointPrecisionMagnitude(command, end);
            // A Bezier's arclength and its perturbation are bounded by the
            // three edges of its control polygon.
            subpathLength += std::hypot(
                control1.x - current.x, control1.y - current.y);
            subpathLength += std::hypot(
                control2.x - control1.x, control2.y - control1.y);
            subpathLength += std::hypot(
                end.x - control2.x, end.y - control2.y);
            subpathLengthError += currentError
                + 2.0 * control1Error
                + 2.0 * control2Error
                + endError;
            current = end;
            currentError = endError;
            break;
        }
        case lunasvg::PaintPathVerb::Close:
            if(hasCurrentPoint)
                addLine(subpathStart, subpathStartError);
            finishSubpath();
            break;
        }
    }
    finishSubpath();
    return metrics;
}

double strokeDashPrecisionError(const lunasvg::PaintCommand& command)
{
    constexpr double STROKE_OPERATION_ULPS = 4.0;
    if(command.stroke.dash_array.empty())
        return 0;

    double patternLength = 0;
    double patternLengthError = 0;
    for(const double value : command.stroke.dash_array) {
        patternLength += std::abs(static_cast<double>(value));
        patternLengthError += storedDoubleUlp(value)
            * STROKE_OPERATION_ULPS;
    }
    if(command.stroke.dash_array.size() % 2 == 1) {
        patternLength *= 2.0;
        patternLengthError *= 2.0;
    }
    const double minimumPatternLength = patternLength - patternLengthError;
    if(!isPositiveFinite(minimumPatternLength))
        return std::numeric_limits<double>::infinity();

    const double offsetError = storedDoubleUlp(command.stroke.dash_offset)
        * STROKE_OPERATION_ULPS;
    const auto pathMetrics = strokePathMetrics(command);
    const double offsetCycles = std::ceil(
        (std::abs(static_cast<double>(command.stroke.dash_offset))
            + offsetError) / minimumPatternLength) + 1.0;
    const double pathCycles = std::ceil(
        (pathMetrics.maximum_length
            + pathMetrics.maximum_length_error)
            / minimumPatternLength) + 2.0;
    const double repeatedPatternError =
        (offsetCycles + pathCycles + 2.0) * patternLengthError;
    return offsetError
        + pathMetrics.maximum_length_error
        + repeatedPatternError;
}

CoordinatePrecisionError transformedPointPrecisionError(
    const lunasvg::PaintCommand& command,
    const PointD& point,
    bool includeStoredCoordinatePrecision = true)
{
    constexpr double pathOperationUlps = 4.0;
    const double transformOperationUlps = 4.0 * std::max(
        1.0, static_cast<double>(command.transform_operation_count));
    const auto& matrix = command.transform;
    const auto inputError = pathInputPrecisionError(command);
    const double pointErrorX = (includeStoredCoordinatePrecision
            && !command.path_coordinates_exact
            ? floatUlp(static_cast<float>(point.x)) * pathOperationUlps
            : 0.0) + inputError.x;
    const double pointErrorY = (includeStoredCoordinatePrecision
            && !command.path_coordinates_exact
            ? floatUlp(static_cast<float>(point.y)) * pathOperationUlps
            : 0.0) + inputError.y;

    const double errorA = (includeStoredCoordinatePrecision
            && !command.transform_coordinates_exact
            ? floatUlp(matrix.a) * transformOperationUlps : 0.0)
        + command.transform_linear_precision_error;
    const double errorB = (includeStoredCoordinatePrecision
            && !command.transform_coordinates_exact
            ? floatUlp(matrix.b) * transformOperationUlps : 0.0)
        + command.transform_linear_precision_error;
    const double errorC = (includeStoredCoordinatePrecision
            && !command.transform_coordinates_exact
            ? floatUlp(matrix.c) * transformOperationUlps : 0.0)
        + command.transform_linear_precision_error;
    const double errorD = (includeStoredCoordinatePrecision
            && !command.transform_coordinates_exact
            ? floatUlp(matrix.d) * transformOperationUlps : 0.0)
        + command.transform_linear_precision_error;
    const double errorE = (includeStoredCoordinatePrecision
            && !command.transform_coordinates_exact
            ? floatUlp(matrix.e) * transformOperationUlps : 0.0)
        + command.transform_translation_precision_error;
    const double errorF = (includeStoredCoordinatePrecision
            && !command.transform_coordinates_exact
            ? floatUlp(matrix.f) * transformOperationUlps : 0.0)
        + command.transform_translation_precision_error;
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

CoordinatePrecisionError paintedFillPrecisionError(
    const lunasvg::PaintCommand& command,
    bool includeStoredCoordinatePrecision)
{
    CoordinatePrecisionError maximumError;
    CoordinatePrecisionError subpathError;
    std::vector<PointD> supportPoints;
    PointD current;
    PointD subpathStart;
    bool hasCurrentPoint = false;
    size_t pointIndex = 0;
    auto includePoint = [&](const PointD& point) {
        supportPoints.push_back(transformPoint(command.transform, point));
        const auto error = transformedPointPrecisionError(
            command, point, includeStoredCoordinatePrecision);
        subpathError.x = std::max(subpathError.x, error.x);
        subpathError.y = std::max(subpathError.y, error.y);
    };
    auto finishSubpath = [&]() {
        bool hasArea = false;
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
                        hasArea = true;
                        break;
                    }
                }
            }
        }
        if(hasArea) {
            maximumError.x = std::max(maximumError.x, subpathError.x);
            maximumError.y = std::max(maximumError.y, subpathError.y);
        }
        supportPoints.clear();
        subpathError = {};
    };
    for(const auto verb : command.path_verbs) {
        switch(verb) {
        case lunasvg::PaintPathVerb::MoveTo: {
            finishSubpath();
            const auto& point = command.path_points.at(pointIndex++);
            current = {point.x, point.y};
            subpathStart = current;
            hasCurrentPoint = true;
            includePoint(current);
            break;
        }
        case lunasvg::PaintPathVerb::LineTo: {
            const auto& point = command.path_points.at(pointIndex++);
            if(supportPoints.empty() && hasCurrentPoint)
                includePoint(current);
            current = {point.x, point.y};
            includePoint(current);
            break;
        }
        case lunasvg::PaintPathVerb::CubicTo: {
            const auto& first = command.path_points.at(pointIndex++);
            const auto& second = command.path_points.at(pointIndex++);
            const auto& last = command.path_points.at(pointIndex++);
            if(supportPoints.empty() && hasCurrentPoint)
                includePoint(current);
            includePoint({first.x, first.y});
            includePoint({second.x, second.y});
            current = {last.x, last.y};
            includePoint(current);
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
    return maximumError;
}

CoordinatePrecisionError commandPrecisionError(
    const lunasvg::PaintCommand& command,
    bool includeStoredCoordinatePrecision = true)
{
    constexpr double STROKE_OPERATION_ULPS = 4.0;
    CoordinatePrecisionError error =
        command.kind == lunasvg::PaintCommandKind::Fill
            || command.kind == lunasvg::PaintCommandKind::ClipBegin
        ? paintedFillPrecisionError(
            command, includeStoredCoordinatePrecision)
        : CoordinatePrecisionError{};
    if(command.kind == lunasvg::PaintCommandKind::Stroke) {
        if(command.stroke_direction_input_ambiguous
                || (command.isolated_stroke_direction_input_ambiguous
                    && (command.stroke.line_cap
                            == lunasvg::PaintLineCap::Square
                        || (command.stroke.line_cap
                                == lunasvg::PaintLineCap::Round
                            && !command.stroke.dash_array.empty()))))
            throw InputPrecisionError("stroke_direction_precision");
        double localPointErrorX = 0.0;
        double localPointErrorY = 0.0;
        const auto inputError = pathInputPrecisionError(command);
        for(const auto& point : command.path_points) {
            const auto pointError = transformedPointPrecisionError(
                command, {point.x, point.y},
                includeStoredCoordinatePrecision);
            error.x = std::max(error.x, pointError.x);
            error.y = std::max(error.y, pointError.y);
            localPointErrorX = std::max(
                localPointErrorX,
                (includeStoredCoordinatePrecision
                    && !command.path_coordinates_exact
                    ? floatUlp(point.x) * STROKE_OPERATION_ULPS : 0.0)
                    + inputError.x);
            localPointErrorY = std::max(
                localPointErrorY,
                (includeStoredCoordinatePrecision
                    && !command.path_coordinates_exact
                    ? floatUlp(point.y) * STROKE_OPERATION_ULPS : 0.0)
                    + inputError.y);
        }
        const double inputAmplification =
            strokeInputPrecisionAmplification(command);
        const double additionalLocalErrorX = localPointErrorX
            * (inputAmplification - 1.0);
        const double additionalLocalErrorY = localPointErrorY
            * (inputAmplification - 1.0);
        error.x += std::abs(static_cast<double>(command.transform.a))
                * additionalLocalErrorX
            + std::abs(static_cast<double>(command.transform.c))
                * additionalLocalErrorY;
        error.y += std::abs(static_cast<double>(command.transform.b))
                * additionalLocalErrorX
            + std::abs(static_cast<double>(command.transform.d))
                * additionalLocalErrorY;
    }
    if(command.kind == lunasvg::PaintCommandKind::Stroke) {
        const double widthError = storedDoubleUlp(command.stroke.width)
            * STROKE_OPERATION_ULPS;
        double expansionRatio = command.stroke.line_cap
                == lunasvg::PaintLineCap::Square
            ? std::sqrt(2.0) : 1.0;
        if(command.stroke.line_join == lunasvg::PaintLineJoin::Miter) {
            const double miterLimitError = storedDoubleUlp(
                command.stroke.miter_limit) * STROKE_OPERATION_ULPS;
            expansionRatio = std::max(
                expansionRatio,
                static_cast<double>(command.stroke.miter_limit)
                    + miterLimitError);
        }
        const double dashError = strokeDashPrecisionError(command);
        const double localBoundaryError = widthError * 0.5 * expansionRatio
            + dashError;
        const double transformedBoundaryError = localBoundaryError
            * maximumSingularValue(command.transform);
        error.x += transformedBoundaryError;
        error.y += transformedBoundaryError;

        if(!isIdentityMatrix(command.transform)
                || command.transform_linear_precision_error > 0) {
            const double transformOperationUlps = 4.0 * std::max(
                1.0,
                static_cast<double>(command.transform_operation_count));
            const double localExpansion =
                (std::abs(static_cast<double>(command.stroke.width)) * 0.5
                    + widthError * 0.5) * expansionRatio
                + dashError;
            const double errorA = (command.transform_coordinates_exact
                    ? 0.0 : floatUlp(command.transform.a)
                        * transformOperationUlps)
                + command.transform_linear_precision_error;
            const double errorB = (command.transform_coordinates_exact
                    ? 0.0 : floatUlp(command.transform.b)
                        * transformOperationUlps)
                + command.transform_linear_precision_error;
            const double errorC = (command.transform_coordinates_exact
                    ? 0.0 : floatUlp(command.transform.c)
                        * transformOperationUlps)
                + command.transform_linear_precision_error;
            const double errorD = (command.transform_coordinates_exact
                    ? 0.0 : floatUlp(command.transform.d)
                        * transformOperationUlps)
                + command.transform_linear_precision_error;
            error.x += localExpansion * (errorA + errorC);
            error.y += localExpansion * (errorB + errorD);
        }
    }
    const double loweringError = command.path_lowering_precision_error;
    if(loweringError > 0.0) {
        error.x += loweringError * std::hypot(
            static_cast<double>(command.transform.a),
            static_cast<double>(command.transform.c));
        error.y += loweringError * std::hypot(
            static_cast<double>(command.transform.b),
            static_cast<double>(command.transform.d));
    }
    return error;
}

lunasvg::PaintCommand nonScalingStrokeGeometryCommand(
    const lunasvg::PaintCommand& command)
{
    auto transformed = command;
    CoordinatePrecisionError maximumInputError;
    for(size_t index = 0; index < command.path_points.size(); ++index) {
        const auto& sourcePoint = command.path_points[index];
        const PointD source{sourcePoint.x, sourcePoint.y};
        const auto point = transformPoint(command.transform, source);
        const auto error = transformedPointPrecisionError(command, source);
        maximumInputError.x = std::max(maximumInputError.x, error.x);
        maximumInputError.y = std::max(maximumInputError.y, error.y);
        transformed.path_points[index] = {point.x, point.y};
    }
    transformed.transform = {};
    transformed.transform_coordinates_exact = true;
    transformed.transform_operation_count = 0;
    transformed.transform_linear_precision_error = 0.0;
    transformed.transform_translation_precision_error = 0.0;
    transformed.path_input_precision_error = std::hypot(
        maximumInputError.x, maximumInputError.y);
    transformed.path_input_precision_error_x = maximumInputError.x;
    transformed.path_input_precision_error_y = maximumInputError.y;
    transformed.path_lowering_precision_error =
        command.path_lowering_precision_error
        * maximumSingularValue(command.transform);
    transformed.path_coordinates_exact = command.path_coordinates_exact
        && command.transform_coordinates_exact
        && maximumInputError.x == 0.0
        && maximumInputError.y == 0.0;
    transformed.non_scaling_stroke = false;
    return transformed;
}

double maximumInputPrecisionErrorSource(
    const std::vector<lunasvg::PaintCommand>& commands,
    const lunasvg::Box& viewport,
    bool includeStoredCoordinatePrecision)
{
    constexpr double VIEWPORT_OPERATION_ULPS = 4.0;
    double maximumError = std::max({
        floatUlp(viewport.x) * VIEWPORT_OPERATION_ULPS,
        floatUlp(viewport.y) * VIEWPORT_OPERATION_ULPS,
        floatUlp(viewport.w) * VIEWPORT_OPERATION_ULPS,
        floatUlp(viewport.h) * VIEWPORT_OPERATION_ULPS,
    });
    for(const auto& command : commands) {
        if(command.kind != lunasvg::PaintCommandKind::Fill
                && command.kind != lunasvg::PaintCommandKind::Stroke
                && command.kind != lunasvg::PaintCommandKind::ClipBegin)
            continue;
        const auto error = command.kind == lunasvg::PaintCommandKind::Stroke
                && command.non_scaling_stroke
            ? commandPrecisionError(
                nonScalingStrokeGeometryCommand(command),
                includeStoredCoordinatePrecision)
            : commandPrecisionError(
                command, includeStoredCoordinatePrecision);
        // A slanted edge projects both coordinate errors onto its normal.
        // Reserve their Euclidean envelope here so the later flattening
        // budget can use only the genuinely remaining physical tolerance.
        maximumError = std::max(
            maximumError, std::hypot(error.x, error.y));
    }
    return maximumError;
}

void requireFiniteRecording(
    const std::vector<lunasvg::PaintCommand>& commands,
    const lunasvg::Box& viewport)
{
    const auto finiteMatrix = [](const lunasvg::PaintTransform& matrix) {
        return std::isfinite(matrix.a) && std::isfinite(matrix.b)
            && std::isfinite(matrix.c) && std::isfinite(matrix.d)
            && std::isfinite(matrix.e) && std::isfinite(matrix.f);
    };
    if(!std::isfinite(viewport.x) || !std::isfinite(viewport.y)
            || !std::isfinite(viewport.w) || !std::isfinite(viewport.h))
        throw InputPrecisionError("nonfinite_viewport");
    for(const auto& command : commands) {
        if(!finiteMatrix(command.transform)
                || !std::isfinite(command.path_input_precision_error)
                || command.path_input_precision_error < 0
                || !std::isfinite(command.path_input_precision_error_x)
                || command.path_input_precision_error_x < 0
                || !std::isfinite(command.path_input_precision_error_y)
                || command.path_input_precision_error_y < 0
                || !std::isfinite(command.path_lowering_precision_error)
                || command.path_lowering_precision_error < 0
                || !std::isfinite(command.source_fill_area_upper_bound)
                || command.source_fill_area_upper_bound < 0
                || !std::isfinite(command.transform_linear_precision_error)
                || command.transform_linear_precision_error < 0
                || !std::isfinite(
                    command.transform_translation_precision_error)
                || command.transform_translation_precision_error < 0
                || !std::isfinite(command.paint_opacity)
                || command.paint_opacity < 0
                || command.paint_opacity > 1
                || !std::isfinite(command.group_opacity)
                || command.group_opacity < 0
                || command.group_opacity > 1)
            throw InputPrecisionError("nonfinite_command_metadata");
        for(const auto& point : command.path_points) {
            if(!std::isfinite(point.x) || !std::isfinite(point.y))
                throw InputPrecisionError("nonfinite_path_point");
        }
        if(command.kind != lunasvg::PaintCommandKind::Stroke)
            continue;
        if(!std::isfinite(command.stroke.width)
                || !std::isfinite(command.stroke.miter_limit)
                || !std::isfinite(command.stroke.dash_offset))
            throw InputPrecisionError("nonfinite_stroke_metadata");
        for(const double dashValue : command.stroke.dash_array) {
            if(!std::isfinite(dashValue))
                throw InputPrecisionError("nonfinite_dash_value");
        }
    }
}

double cubicCoordinate(double start, double control1, double control2,
                       double end, long double t)
{
    const long double oneMinusT = 1.0L - t;
    return static_cast<double>(
        oneMinusT * oneMinusT * oneMinusT * start
        + 3.0L * oneMinusT * oneMinusT * t * control1
        + 3.0L * oneMinusT * t * t * control2
        + t * t * t * end);
}

void includeCubicExtrema(const PointD& start, const PointD& control1,
                         const PointD& control2, const PointD& end,
                         SourceBounds& bounds)
{
    bounds.include(start);
    bounds.include(end);
    auto includeCoordinateExtrema = [&](double p0, double p1, double p2,
                                        double p3, bool xCoordinate) {
        const long double lp0 = p0;
        const long double lp1 = p1;
        const long double lp2 = p2;
        const long double lp3 = p3;
        const long double a = -lp0 + 3.0L * lp1 - 3.0L * lp2 + lp3;
        const long double b = 2.0L * (lp0 - 2.0L * lp1 + lp2);
        const long double c = lp1 - lp0;
        std::array<long double, 2> roots{{-1, -1}};
        size_t rootCount = 0;
        if(a == 0.0L) {
            if(b != 0.0L)
                roots[rootCount++] = -c / b;
        } else {
            const long double discriminant = b * b - 4.0L * a * c;
            if(discriminant >= 0.0L) {
                const long double root = std::sqrt(discriminant);
                if(root == 0.0L) {
                    roots[rootCount++] = -b / (2.0L * a);
                } else {
                    const long double q = -0.5L
                        * (b + std::copysign(root, b));
                    roots[rootCount++] = q / a;
                    roots[rootCount++] = c / q;
                }
            }
        }
        for(size_t index = 0; index < rootCount; ++index) {
            const long double t = roots[index];
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
    const bool strokeCommand =
        command.kind == lunasvg::PaintCommandKind::Stroke;
    if(command.kind == lunasvg::PaintCommandKind::Fill
            || command.kind == lunasvg::PaintCommandKind::ClipBegin
            || strokeCommand) {
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
            if((strokeCommand && !supportPoints.empty())
                    || hasNonCollinearPoints) {
                if(strokeCommand)
                    bounds.includeFiniteExtent(subpathBounds);
                else
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

SourceBounds exactPaintBounds(const lunasvg::PaintCommand& command,
                              ComplexityBudget& complexityBudget)
{
    const auto nonScalingCommand = command.kind
                == lunasvg::PaintCommandKind::Stroke
            && command.non_scaling_stroke
        ? std::optional<lunasvg::PaintCommand>(
            nonScalingStrokeGeometryCommand(command))
        : std::nullopt;
    const auto& geometryCommand = nonScalingCommand
        ? *nonScalingCommand : command;
    auto bounds = exactFillBounds(geometryCommand);
    if(command.kind == lunasvg::PaintCommandKind::Stroke) {
        const bool hasDrawSegment = std::any_of(
            geometryCommand.path_verbs.begin(),
            geometryCommand.path_verbs.end(),
            [](lunasvg::PaintPathVerb verb) {
                return verb != lunasvg::PaintPathVerb::MoveTo;
            });
        if(hasDrawSegment && bounds.finiteExtent()
                && geometryCommand.stroke.line_join
                    == lunasvg::PaintLineJoin::Round
                && geometryCommand.stroke.line_cap
                    == lunasvg::PaintLineCap::Round) {
            const double radius = std::abs(
                static_cast<double>(geometryCommand.stroke.width)) * 0.5;
            const auto& matrix = geometryCommand.transform;
            const double paddingX = radius * std::hypot(
                static_cast<double>(matrix.a),
                static_cast<double>(matrix.c));
            const double paddingY = radius * std::hypot(
                static_cast<double>(matrix.b),
                static_cast<double>(matrix.d));
            if(std::isfinite(paddingX) && std::isfinite(paddingY)) {
                bounds.min_x -= paddingX;
                bounds.max_x += paddingX;
                bounds.min_y -= paddingY;
                bounds.max_y += paddingY;
                return bounds;
            }
        }
        const double singularValue = maximumSingularValue(
            geometryCommand.transform);
        const bool hasFinitePathBounds = std::isfinite(bounds.min_x)
            && std::isfinite(bounds.min_y)
            && std::isfinite(bounds.max_x)
            && std::isfinite(bounds.max_y)
            && bounds.max_x >= bounds.min_x
            && bounds.max_y >= bounds.min_y;
        if(!isPositiveFinite(singularValue) || !hasFinitePathBounds)
            return bounds;
        const double pathScale = std::max({
            bounds.max_x - bounds.min_x,
            bounds.max_y - bounds.min_y,
            std::abs(static_cast<double>(geometryCommand.stroke.width)),
        });
        if(!isPositiveFinite(pathScale))
            return bounds;
        // This discarded sizing pass is relative to the local artwork span,
        // not its absolute coordinate magnitude or the printer tolerance. It
        // therefore finds the actual stroke bbox without erasing short paths
        // at large offsets and without changing the returned geometry grid.
        const double localFlattenTolerance = pathScale * 1.0e-6;
        const double localGridStep = pathScale * 1.0e-10;
        SourceBounds expandedBounds;
        const auto expansion = expandStrokeLocal(
            geometryCommand, localFlattenTolerance, localGridStep,
            complexityBudget, false);
        for(const auto& expandedPath : expansion.paths) {
            for(const auto& point : expandedPath.points) {
                expandedBounds.include(transformPoint(
                    geometryCommand.transform, {point.x, point.y}));
            }
        }
        if(expandedBounds.valid())
            bounds = expandedBounds;
    }
    return bounds;
}

SourceBounds exactPaintBounds(
    const std::vector<lunasvg::PaintCommand>& commands,
    ComplexityBudget& complexityBudget)
{
    SourceBounds bounds;
    for(const auto& command : commands) {
        if(command.kind == lunasvg::PaintCommandKind::Fill
                || command.kind == lunasvg::PaintCommandKind::Stroke)
            bounds.include(exactPaintBounds(command, complexityBudget));
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
    const std::vector<lunasvg::PaintCommand>& commands,
    ComplexityBudget& complexityBudget)
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
            : exactPaintBounds(command, complexityBudget);
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
    for(const auto& boundary : trace.boundaries) {
        const bool intersectsResultDomain =
            boundary.min_x <= sourceBounds.max_x
            && boundary.max_x >= sourceBounds.min_x
            && boundary.min_y <= sourceBounds.max_y
            && boundary.max_y >= sourceBounds.min_y;
        if(!intersectsResultDomain)
            continue;
        maximumError = std::max(
            maximumError, boundary.maximum_error_source);
    }
    return maximumError;
}

void flattenCubic(const PointD& start, const PointD& control1,
                  const PointD& control2, const PointD& end,
                  double tolerance, double sourceErrorScale,
                  unsigned depth, std::vector<PointD>& output,
                  std::vector<double>& incomingApproximationErrors,
                  ComplexityBudget& complexityBudget)
{
    const double localApproximationError = std::max(
        pointSegmentDistance(control1, start, end),
        pointSegmentDistance(control2, start, end));
    if(depth >= 32 || localApproximationError <= tolerance) {
        complexityBudget.consumeGeneratedPoints();
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
        depth + 1, output, incomingApproximationErrors,
        complexityBudget);
    flattenCubic(
        midpoint, p123, p23, end, tolerance, sourceErrorScale,
        depth + 1, output, incomingApproximationErrors,
        complexityBudget);
}

void flattenCubicWithMinimumDepth(
    const PointD& start, const PointD& control1,
    const PointD& control2, const PointD& end,
    double tolerance, double sourceErrorScale,
    unsigned depth, unsigned minimumDepth,
    std::vector<PointD>& output,
    std::vector<double>& incomingApproximationErrors,
    ComplexityBudget& complexityBudget)
{
    if(depth >= minimumDepth) {
        flattenCubic(
            start, control1, control2, end,
            tolerance, sourceErrorScale, depth,
            output, incomingApproximationErrors, complexityBudget);
        return;
    }

    const PointD p01{(start.x + control1.x) * 0.5,
                     (start.y + control1.y) * 0.5};
    const PointD p12{(control1.x + control2.x) * 0.5,
                     (control1.y + control2.y) * 0.5};
    const PointD p23{(control2.x + end.x) * 0.5,
                     (control2.y + end.y) * 0.5};
    const PointD p012{(p01.x + p12.x) * 0.5,
                      (p01.y + p12.y) * 0.5};
    const PointD p123{(p12.x + p23.x) * 0.5,
                      (p12.y + p23.y) * 0.5};
    const PointD center{(p012.x + p123.x) * 0.5,
                        (p012.y + p123.y) * 0.5};
    flattenCubicWithMinimumDepth(
        start, p01, p012, center,
        tolerance, sourceErrorScale, depth + 1, minimumDepth,
        output, incomingApproximationErrors, complexityBudget);
    flattenCubicWithMinimumDepth(
        center, p123, p23, end,
        tolerance, sourceErrorScale, depth + 1, minimumDepth,
        output, incomingApproximationErrors, complexityBudget);
}

int64_t checkedQuantize(double value)
{
    constexpr double safeCoordinate = 1.0e15;
    if(!std::isfinite(value) || std::abs(value) > safeCoordinate)
        throw std::range_error("numeric_range_error");
    return static_cast<int64_t>(std::llround(value));
}

Point64 toGridPoint(const PointD& local,
                    const lunasvg::PaintTransform& transform,
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
    const lunasvg::PaintTransform& transform)
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

long double triangleArea(const PointD& first, const PointD& second,
                         const PointD& third)
{
    return std::abs(
        (static_cast<long double>(second.x) - first.x)
                * (static_cast<long double>(third.y) - first.y)
            - (static_cast<long double>(second.y) - first.y)
                * (static_cast<long double>(third.x) - first.x))
        * 0.5L;
}

long double cubicControlHullArea(const std::array<PointD, 4>& cubic)
{
    std::array<PointD, 4> points = cubic;
    std::sort(points.begin(), points.end(), [](const auto& left,
                                               const auto& right) {
        return left.x == right.x ? left.y < right.y : left.x < right.x;
    });
    std::array<PointD, 8> hull;
    size_t hullSize = 0;
    const auto cross = [](const PointD& first, const PointD& second,
                          const PointD& third) {
        return (static_cast<long double>(second.x) - first.x)
                * (static_cast<long double>(third.y) - first.y)
            - (static_cast<long double>(second.y) - first.y)
                * (static_cast<long double>(third.x) - first.x);
    };
    for(const auto& point : points) {
        while(hullSize >= 2
                && cross(hull[hullSize - 2], hull[hullSize - 1], point)
                    <= 0.0L)
            --hullSize;
        hull[hullSize++] = point;
    }
    const size_t lowerSize = hullSize;
    for(size_t index = points.size(); index > 1; --index) {
        const auto& point = points[index - 2];
        while(hullSize > lowerSize
                && cross(hull[hullSize - 2], hull[hullSize - 1], point)
                    <= 0.0L)
            --hullSize;
        hull[hullSize++] = point;
    }
    if(hullSize > 1)
        --hullSize;
    if(hullSize < 3)
        return 0.0L;
    long double twiceArea = 0.0L;
    for(size_t index = 0; index < hullSize; ++index) {
        const auto& current = hull[index];
        const auto& next = hull[(index + 1) % hullSize];
        twiceArea += static_cast<long double>(current.x) * next.y
            - static_cast<long double>(current.y) * next.x;
    }
    return std::abs(twiceArea) * 0.5L;
}

PointD midpoint(const PointD& first, const PointD& second)
{
    return {(first.x + second.x) * 0.5, (first.y + second.y) * 0.5};
}

void appendCubicAreaEnvelope(
    const std::array<PointD, 4>& cubic,
    unsigned depth,
    std::vector<PointD>& boundary,
    long double& bulgeArea)
{
    if(depth == 0) {
        boundary.push_back(cubic[3]);
        bulgeArea += cubicControlHullArea(cubic);
        return;
    }
    const auto p01 = midpoint(cubic[0], cubic[1]);
    const auto p12 = midpoint(cubic[1], cubic[2]);
    const auto p23 = midpoint(cubic[2], cubic[3]);
    const auto p012 = midpoint(p01, p12);
    const auto p123 = midpoint(p12, p23);
    const auto center = midpoint(p012, p123);
    appendCubicAreaEnvelope(
        {{cubic[0], p01, p012, center}}, depth - 1,
        boundary, bulgeArea);
    appendCubicAreaEnvelope(
        {{center, p123, p23, cubic[3]}}, depth - 1,
        boundary, bulgeArea);
}

long double translatedGridArea(const Path64& path)
{
    if(path.size() < 3)
        return 0.0L;
    const auto anchor = path.front();
    long double twiceArea = 0.0L;
    for(size_t index = 0; index < path.size(); ++index) {
        const auto& current = path[index];
        const auto& next = path[(index + 1) % path.size()];
        const long double currentX = static_cast<long double>(
            current.x - anchor.x);
        const long double currentY = static_cast<long double>(
            current.y - anchor.y);
        const long double nextX = static_cast<long double>(
            next.x - anchor.x);
        const long double nextY = static_cast<long double>(
            next.y - anchor.y);
        twiceArea += currentX * nextY - currentY * nextX;
    }
    return std::abs(twiceArea) * 0.5L;
}

long double polylineFilledAreaUpperBound(
    const std::vector<PointD>& boundary,
    ComplexityBudget& complexityBudget)
{
    if(boundary.size() < 3)
        return 0.0L;
    double minX = std::numeric_limits<double>::infinity();
    double minY = std::numeric_limits<double>::infinity();
    double maxX = -std::numeric_limits<double>::infinity();
    double maxY = -std::numeric_limits<double>::infinity();
    long double perimeter = 0.0L;
    for(size_t index = 0; index < boundary.size(); ++index) {
        const auto& point = boundary[index];
        const auto& next = boundary[(index + 1) % boundary.size()];
        minX = std::min(minX, point.x);
        minY = std::min(minY, point.y);
        maxX = std::max(maxX, point.x);
        maxY = std::max(maxY, point.y);
        perimeter += std::hypot(
            static_cast<long double>(next.x) - point.x,
            static_cast<long double>(next.y) - point.y);
    }
    const double span = std::max(maxX - minX, maxY - minY);
    if(!isPositiveFinite(span) || !std::isfinite(perimeter))
        return std::numeric_limits<long double>::infinity();

    // Rebase before quantization so Clipper measures the filled polyline area
    // rather than losing a thin loop to cancellation at a large SVG offset.
    // The swept-boundary term covers every point moved by grid rounding.
    constexpr double LOCAL_AREA_GRID_CELLS = 1.0e8;
    constexpr long double PI =
        3.141592653589793238462643383279502884L;
    const double scale = LOCAL_AREA_GRID_CELLS / span;
    if(!isPositiveFinite(scale))
        return std::numeric_limits<long double>::infinity();
    Path64 path;
    path.reserve(boundary.size());
    for(const auto& point : boundary) {
        const Point64 gridPoint{
            static_cast<int64_t>(std::llround((point.x - minX) * scale)),
            static_cast<int64_t>(std::llround((point.y - minY) * scale)),
        };
        if(path.empty() || path.back() != gridPoint)
            path.push_back(gridPoint);
    }
    if(path.size() > 1 && path.front() == path.back())
        path.pop_back();

    long double filledArea = 0.0L;
    size_t normalizedPointCount = 0;
    if(path.size() >= 3) {
        Paths64 sourcePaths;
        sourcePaths.emplace_back(std::move(path));
        preflightBoolean(complexityBudget, sourcePaths);
        const auto normalized = executeClipperBoolean(
            ClipType::Union, FillRule::NonZero,
            sourcePaths, nullptr, complexityBudget);
        consumeClipperOutput(complexityBudget, normalized);
        for(const auto& ring : normalized) {
            filledArea += translatedGridArea(ring);
            normalizedPointCount += ring.size();
        }
        filledArea /= static_cast<long double>(scale)
            * static_cast<long double>(scale);
    }
    const long double roundingRadius = std::sqrt(0.5L)
        / static_cast<long double>(scale);
    const long double sweptBoundaryArea =
        2.0L * perimeter * roundingRadius
        + 4.0L * PI * roundingRadius * roundingRadius;
    const long double arithmeticAreaError =
        static_cast<long double>(normalizedPointCount + 1)
        * std::numeric_limits<long double>::epsilon()
        * 32.0L * static_cast<long double>(span)
        * static_cast<long double>(span);
    return filledArea + sweptBoundaryArea + arithmeticAreaError;
}

double sourceAreaUpperBound(
    const std::vector<SourceBoundarySegment>& segments,
    const lunasvg::PaintTransform& transform,
    ComplexityBudget& complexityBudget)
{
    if(segments.empty())
        return 0.0;
    constexpr unsigned AREA_ENVELOPE_SUBDIVISIONS = 4;
    size_t maximumBoundaryPoints = 1;
    for(const auto& segment : segments) {
        maximumBoundaryPoints = checkedSizeSum(
            maximumBoundaryPoints,
            segment.cubic
                ? size_t{1} << AREA_ENVELOPE_SUBDIVISIONS
                : size_t{1});
    }
    std::vector<PointD> boundary;
    boundary.reserve(maximumBoundaryPoints);
    boundary.push_back(transformPoint(transform, segments.front().start));
    long double bulgeArea = 0.0L;
    for(const auto& segment : segments) {
        if(!segment.cubic) {
            boundary.push_back(transformPoint(transform, segment.end));
            continue;
        }
        appendCubicAreaEnvelope(
            {{
                transformPoint(transform, segment.start),
                transformPoint(transform, segment.control1),
                transformPoint(transform, segment.control2),
                transformPoint(transform, segment.end),
            }},
            AREA_ENVELOPE_SUBDIVISIONS, boundary, bulgeArea);
    }

    const auto& anchor = boundary.front();
    long double fanArea = 0.0L;
    for(size_t index = 1; index + 1 < boundary.size(); ++index)
        fanArea += triangleArea(anchor, boundary[index], boundary[index + 1]);
    const long double filledArea = polylineFilledAreaUpperBound(
        boundary, complexityBudget);
    return static_cast<double>(
        std::min(fanArea, filledArea) + bulgeArea);
}

double sourcePrecisionEnvelopeAreaUpperBound(
    const std::vector<SourceBoundarySegment>& segments,
    const lunasvg::PaintTransform& transform,
    const CoordinatePrecisionError& precisionError)
{
    if(segments.empty()
            || !std::isfinite(precisionError.x)
            || !std::isfinite(precisionError.y))
        return std::numeric_limits<double>::infinity();
    double minimumX = std::numeric_limits<double>::infinity();
    double minimumY = std::numeric_limits<double>::infinity();
    double maximumX = -std::numeric_limits<double>::infinity();
    double maximumY = -std::numeric_limits<double>::infinity();
    const auto include = [&](const PointD& point) {
        const auto transformed = transformPoint(transform, point);
        minimumX = std::min(minimumX, transformed.x);
        minimumY = std::min(minimumY, transformed.y);
        maximumX = std::max(maximumX, transformed.x);
        maximumY = std::max(maximumY, transformed.y);
    };
    for(const auto& segment : segments) {
        include(segment.start);
        if(segment.cubic) {
            include(segment.control1);
            include(segment.control2);
        }
        include(segment.end);
    }
    const long double width =
        static_cast<long double>(maximumX) - minimumX
        + 2.0L * precisionError.x;
    const long double height =
        static_cast<long double>(maximumY) - minimumY
        + 2.0L * precisionError.y;
    const long double area = width * height;
    if(!(width >= 0.0L) || !(height >= 0.0L)
            || !std::isfinite(area))
        return std::numeric_limits<double>::infinity();
    return static_cast<double>(area);
}

bool refineCollapsedCurveBoundary(
    const std::vector<SourceBoundarySegment>& segments,
    const lunasvg::PaintTransform& transform,
    const PhysicalDomain& domain,
    std::vector<PointD>& points,
    std::vector<double>& incomingApproximationErrors)
{
    const bool hasCurve = std::any_of(
        segments.begin(), segments.end(),
        [](const SourceBoundarySegment& segment) {
            return segment.cubic;
        });
    if(!hasCurve || segments.empty() || domain.complexity_budget == nullptr)
        return false;
    const double singularValue = maximumSingularValue(transform);
    if(!isPositiveFinite(singularValue))
        return false;
    const double localTolerance = domain.flatten_budget_mm
        / (domain.source_to_mm * singularValue);
    if(!isPositiveFinite(localTolerance))
        return false;

    points.clear();
    incomingApproximationErrors.clear();
    domain.complexity_budget->consumeGeneratedPoints();
    points.push_back(segments.front().start);
    incomingApproximationErrors.push_back(0.0);
    // The normal error-bounded flattener may represent a small closed curve
    // only by coincident endpoints. Sample its interior deterministically
    // before deciding whether the authoritative geometry grid can retain it.
    constexpr unsigned MINIMUM_COLLAPSE_REFINEMENT_DEPTH = 4;
    for(const auto& segment : segments) {
        if(!segment.cubic) {
            domain.complexity_budget->consumeGeneratedPoints();
            points.push_back(segment.end);
            incomingApproximationErrors.push_back(0.0);
            continue;
        }
        flattenCubicWithMinimumDepth(
            segment.start, segment.control1, segment.control2, segment.end,
            localTolerance, singularValue, 0,
            MINIMUM_COLLAPSE_REFINEMENT_DEPTH,
            points, incomingApproximationErrors,
            *domain.complexity_budget);
    }
    return true;
}

void traceClosedContour(const std::vector<PointD>& localPoints,
                        const lunasvg::PaintTransform& transform,
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
        trace->append({
            std::min(start.x, end.x),
            std::min(start.y, end.y),
            std::max(start.x, end.x),
            std::max(start.y, end.y),
            normalPrecisionError
                + incomingErrors[(index + 1) % points.size()],
        });
    }
}

void traceClosedContour(const std::vector<PointD>& localPoints,
                        const lunasvg::PaintTransform& transform,
                        const CoordinatePrecisionError& precisionError,
                        double approximationErrorSource,
                        TopologyTrace* trace)
{
    traceClosedContour(
        localPoints, transform, precisionError,
        std::vector<double>(localPoints.size(), approximationErrorSource),
        trace);
}

void finishSubpath(std::vector<PointD>& points,
                   std::vector<double>& incomingApproximationErrors,
                   std::vector<SourceBoundarySegment>& sourceSegments,
                   const lunasvg::PaintCommand& command,
                   bool sourceAreaPotential,
                   int32_t subpathIndex,
                   const PhysicalDomain& domain,
                   const CoordinatePrecisionError& precisionError,
                   Paths64& paths,
                   std::vector<FragmentIssue>& fragmentIssues)
{
    const auto clearState = [&]() {
        points.clear();
        incomingApproximationErrors.clear();
        sourceSegments.clear();
    };
    if(points.empty())
        return;
    bool curveBoundaryRefined = false;
    if(points.size() < 3 && sourceAreaPotential) {
        curveBoundaryRefined = refineCollapsedCurveBoundary(
            sourceSegments, command.transform, domain,
            points, incomingApproximationErrors);
    }
    const auto distinctPointCount = [&]() {
        std::vector<PointD> distinct;
        distinct.reserve(std::min<size_t>(points.size(), 3));
        for(const auto& point : points) {
            const bool seen = std::any_of(
                distinct.begin(), distinct.end(),
                [&](const PointD& value) {
                    return value.x == point.x && value.y == point.y;
                });
            if(!seen)
                distinct.push_back(point);
            if(distinct.size() >= 3)
                break;
        }
        return distinct.size();
    };
    if(points.size() < 3) {
        fragmentIssues.push_back({
            sourceAreaPotential
                ? UnprintableReason::AreaCollapse
                : distinctPointCount() <= 1
                    ? UnprintableReason::PointOnly
                    : UnprintableReason::LineOnly,
            subpathIndex,
        });
        clearState();
        return;
    }
    bool sourceHasArea = hasNonCollinearTransformedPoints(
        points, command.transform);
    if(!sourceHasArea) {
        if(sourceAreaPotential && !curveBoundaryRefined) {
            curveBoundaryRefined = refineCollapsedCurveBoundary(
                sourceSegments, command.transform, domain,
                points, incomingApproximationErrors);
            sourceHasArea = hasNonCollinearTransformedPoints(
                points, command.transform);
        }
        if(!sourceHasArea) {
            fragmentIssues.push_back({
                sourceAreaPotential
                    ? UnprintableReason::AreaCollapse
                    : distinctPointCount() <= 1
                        ? UnprintableReason::PointOnly
                        : UnprintableReason::LineOnly,
                subpathIndex,
            });
            clearState();
            return;
        }
    }
    if(domain.complexity_budget == nullptr)
        throw std::logic_error("missing_complexity_budget");
    const auto quantizeBoundary = [&]() {
        Path64 candidate;
        domain.complexity_budget->consumeGeneratedPoints(points.size());
        candidate.reserve(points.size());
        for(const auto& point : points) {
            const auto gridPoint = toGridPoint(
                point, command.transform, domain);
            if(candidate.empty() || candidate.back() != gridPoint)
                candidate.push_back(gridPoint);
        }
        if(candidate.size() > 1 && candidate.front() == candidate.back())
            candidate.pop_back();
        return candidate;
    };
    auto path = quantizeBoundary();
    if((path.size() < 3 || Clipper2Lib::Area(path) == 0.0)
            && sourceAreaPotential && !curveBoundaryRefined) {
        curveBoundaryRefined = refineCollapsedCurveBoundary(
            sourceSegments, command.transform, domain,
            points, incomingApproximationErrors);
        if(curveBoundaryRefined)
            path = quantizeBoundary();
    }
    if(path.size() < 3 || Clipper2Lib::Area(path) == 0.0) {
        fragmentIssues.push_back({
            UnprintableReason::AreaCollapse,
            subpathIndex,
        });
        clearState();
        return;
    }
    traceClosedContour(
        points, command.transform, precisionError,
        incomingApproximationErrors,
        domain.topology_trace);
    if(path.size() >= 3) {
        domain.complexity_budget->consumeGeneratedRings();
        paths.emplace_back(std::move(path));
    }
    clearState();
}

Paths64 flattenFill(const lunasvg::PaintCommand& command,
                    const PhysicalDomain& domain,
                    std::vector<FragmentIssue>& fragmentIssues)
{
    if(domain.complexity_budget == nullptr)
        throw std::logic_error("missing_complexity_budget");
    auto& complexityBudget = *domain.complexity_budget;
    const double singularValue = maximumSingularValue(command.transform);
    if(!isPositiveFinite(singularValue))
        return {};
    const double localTolerance = domain.flatten_budget_mm
        / (domain.source_to_mm * singularValue);
    Paths64 paths;
    std::vector<PointD> subpath;
    std::vector<double> incomingApproximationErrors;
    std::vector<SourceBoundarySegment> sourceSegments;
    CoordinatePrecisionError subpathPrecisionError;
    PointD current;
    PointD subpathStart;
    bool hasCurrentPoint = false;
    size_t pointIndex = 0;
    size_t sourceSubpathIndex = 0;
    int32_t currentSubpathIndex = -1;
    bool sourceAreaPotential = true;
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
                subpath, incomingApproximationErrors, sourceSegments,
                command,
                sourceAreaPotential, currentSubpathIndex, domain,
                subpathPrecisionError, paths, fragmentIssues);
            subpathPrecisionError = {};
            sourceAreaPotential = sourceSubpathIndex
                    < command.source_subpath_area_potential.size()
                ? command.source_subpath_area_potential[sourceSubpathIndex]
                    != 0
                : true;
            currentSubpathIndex = static_cast<int32_t>(sourceSubpathIndex);
            ++sourceSubpathIndex;
            const auto& point = command.path_points.at(pointIndex++);
            includePrecision(point);
            current = {point.x, point.y};
            subpathStart = current;
            hasCurrentPoint = true;
            complexityBudget.consumeGeneratedPoints();
            subpath.push_back(current);
            incomingApproximationErrors.push_back(0.0);
            break;
        }
        case lunasvg::PaintPathVerb::LineTo: {
            const auto& point = command.path_points.at(pointIndex++);
            includePrecision(point);
            if(subpath.empty() && hasCurrentPoint) {
                includePointPrecision(current);
                complexityBudget.consumeGeneratedPoints();
                subpath.push_back(current);
                incomingApproximationErrors.push_back(0.0);
            }
            sourceSegments.push_back({current, {}, {}, {point.x, point.y}, false});
            current = {point.x, point.y};
            complexityBudget.consumeGeneratedPoints();
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
                complexityBudget.consumeGeneratedPoints();
                subpath.push_back(current);
                incomingApproximationErrors.push_back(0.0);
            }
            sourceSegments.push_back({
                current, control1, control2, end, true,
            });
            flattenCubic(current, control1, control2, end,
                         localTolerance, singularValue, 0, subpath,
                         incomingApproximationErrors, complexityBudget);
            current = end;
            break;
        }
        case lunasvg::PaintPathVerb::Close:
            finishSubpath(
                subpath, incomingApproximationErrors, sourceSegments,
                command,
                sourceAreaPotential, currentSubpathIndex, domain,
                subpathPrecisionError, paths, fragmentIssues);
            subpathPrecisionError = {};
            if(hasCurrentPoint)
                current = subpathStart;
            break;
        }
    }
    finishSubpath(
        subpath, incomingApproximationErrors, sourceSegments, command,
        sourceAreaPotential, currentSubpathIndex, domain,
        subpathPrecisionError, paths, fragmentIssues);
    if(command.path_verbs.empty())
        fragmentIssues.push_back({UnprintableReason::EmptyPath, -1});
    return paths;
}

FillRule clipperFillRule(lunasvg::PaintFillRule fillRule)
{
    return fillRule == lunasvg::PaintFillRule::EvenOdd
        ? FillRule::EvenOdd : FillRule::NonZero;
}

double boundaryErrorSince(const PhysicalDomain& domain, size_t traceStart)
{
    double maximumError = 0.0;
    if(domain.topology_trace != nullptr) {
        for(size_t index = traceStart;
                index < domain.topology_trace->boundaries.size(); ++index) {
            maximumError = std::max(
                maximumError,
                domain.topology_trace->boundaries[index]
                    .maximum_error_source);
        }
    }
    const double gridToSource =
        domain.grid_step_mm / domain.source_to_mm;
    return maximumError + gridToSource / std::sqrt(2.0);
}

PrecisionPaths normalizeFill(const lunasvg::PaintCommand& command,
                             const PhysicalDomain& domain)
{
    const size_t traceStart = domain.topology_trace == nullptr
        ? 0 : domain.topology_trace->boundaries.size();
    std::vector<FragmentIssue> fragmentIssues;
    auto paths = flattenFill(command, domain, fragmentIssues);
    const bool hadAreaPaths = !paths.empty();
    preflightBoolean(*domain.complexity_budget, paths);
    double boundaryErrorSource = boundaryErrorSince(domain, traceStart);
    const auto inputPrecision = commandPrecisionError(command, false);
    auto normalized = executeClipperBoolean(
        ClipType::Union, clipperFillRule(command.fill_rule),
        paths, nullptr, *domain.complexity_budget);
    consumeClipperOutput(*domain.complexity_budget, normalized);
    if(hadAreaPaths && normalized.empty()) {
        fragmentIssues.push_back({
            UnprintableReason::FillRuleCancelled,
            -1,
        });
    }
    return {
        std::move(normalized), boundaryErrorSource,
        inputPrecision.x, inputPrecision.y,
        std::move(fragmentIssues),
    };
}

PrecisionPaths normalizeStroke(const lunasvg::PaintCommand& command,
                               const PhysicalDomain& domain)
{
    const size_t traceStart = domain.topology_trace == nullptr
        ? 0 : domain.topology_trace->boundaries.size();
    const auto nonScalingCommand = command.non_scaling_stroke
        ? std::optional<lunasvg::PaintCommand>(
            nonScalingStrokeGeometryCommand(command))
        : std::nullopt;
    const auto& geometryCommand = nonScalingCommand
        ? *nonScalingCommand : command;
    const double singularValue = maximumSingularValue(
        geometryCommand.transform);
    if(!isPositiveFinite(singularValue))
        return {};
    const double localFlattenTolerance = domain.flatten_budget_mm
        / (domain.source_to_mm * singularValue);
    // Stroke offsetting uses the same authoritative numeric grid as fills.
    // A tolerance-sized secondary grid would be print-resolution snapping at
    // the parser boundary and can erase real short stroked regions before the
    // downstream physical cleanup stage sees them.
    const double localGridStep = domain.grid_step_mm
        / (domain.source_to_mm * singularValue);
    Paths64 paths;
    std::vector<FragmentIssue> fragmentIssues;
    if(domain.complexity_budget == nullptr)
        throw std::logic_error("missing_complexity_budget");
    auto& complexityBudget = *domain.complexity_budget;
    const auto precisionError = commandPrecisionError(geometryCommand);
    const auto expansion = expandStrokeLocal(
        geometryCommand, localFlattenTolerance, localGridStep,
        complexityBudget);
    for(const int32_t subpathIndex : expansion.collapsed_subpath_indices) {
        fragmentIssues.push_back({
            UnprintableReason::StrokeCollapse,
            subpathIndex,
        });
    }
    for(const auto& expandedPath : expansion.paths) {
        const auto& ring = expandedPath.points;
        std::vector<PointD> localPoints;
        complexityBudget.consumeGeneratedPoints(ring.size());
        localPoints.reserve(ring.size());
        for(const auto& point : ring)
            localPoints.push_back({point.x, point.y});
        traceClosedContour(
            localPoints, geometryCommand.transform, precisionError,
            (domain.flatten_budget_mm
                + domain.grid_step_mm / std::sqrt(2.0))
                / domain.source_to_mm,
            domain.topology_trace);
        Path64 path;
        complexityBudget.consumeGeneratedPoints(ring.size());
        path.reserve(ring.size());
        for(const auto& point : ring) {
            const auto gridPoint = toGridPoint(
                {point.x, point.y}, geometryCommand.transform, domain);
            if(path.empty() || path.back() != gridPoint)
                path.push_back(gridPoint);
        }
        if(path.size() > 1 && path.front() == path.back())
            path.pop_back();
        if(path.size() < 3 || Clipper2Lib::Area(path) == 0.0) {
            fragmentIssues.push_back({
                UnprintableReason::StrokeCollapse,
                expandedPath.source_subpath_index,
            });
            continue;
        }
        if(path.size() >= 3) {
            complexityBudget.consumeGeneratedRings();
            paths.emplace_back(std::move(path));
        }
    }
    preflightBoolean(complexityBudget, paths);
    double boundaryErrorSource = boundaryErrorSince(domain, traceStart);
    const auto inputPrecision = commandPrecisionError(
        geometryCommand, false);
    auto normalized = executeClipperBoolean(
        ClipType::Union, FillRule::NonZero,
        paths, nullptr, complexityBudget);
    consumeClipperOutput(complexityBudget, normalized);
    if(normalized.empty() && fragmentIssues.empty()) {
        const bool hasPoint = std::any_of(
            command.path_verbs.begin(), command.path_verbs.end(),
            [](lunasvg::PaintPathVerb verb) {
                return verb == lunasvg::PaintPathVerb::MoveTo;
            });
        fragmentIssues.push_back({
            hasPoint
                ? UnprintableReason::StrokeCollapse
                : UnprintableReason::EmptyPath,
            -1,
        });
    }
    return {
        std::move(normalized), boundaryErrorSource,
        inputPrecision.x, inputPrecision.y,
        std::move(fragmentIssues),
    };
}

PrecisionPaths applyActiveClips(
    PrecisionPaths geometry,
    const std::vector<PrecisionPaths>& activeClips,
    const PhysicalDomain& domain)
{
    for(const auto& clip : activeClips) {
        const bool hadArea = !geometry.paths.empty();
        preflightNormalizedBoolean(
            *domain.complexity_budget, geometry.paths, clip.paths);
        geometry.boundary_error_source = std::max(
            geometry.boundary_error_source,
            clip.boundary_error_source);
        geometry.input_precision_error_x_source = std::max(
            geometry.input_precision_error_x_source,
            clip.input_precision_error_x_source);
        geometry.input_precision_error_y_source = std::max(
            geometry.input_precision_error_y_source,
            clip.input_precision_error_y_source);
        geometry.paths = executeClipperBoolean(
            ClipType::Intersection, FillRule::NonZero,
            geometry.paths, &clip.paths, *domain.complexity_budget);
        consumeClipperOutput(
            *domain.complexity_budget, geometry.paths);
        if(hadArea && geometry.paths.empty()) {
            geometry.fragment_issues.push_back({
                UnprintableReason::ClippedOut,
                -1,
            });
            break;
        }
    }
    return geometry;
}

struct PaintReplay {
    struct ProgramNode {
        enum class Kind : uint8_t {
            Paint,
            Group,
        };

        Kind kind{Kind::Group};
        size_t paint_index{0};
        double opacity{1};
        std::vector<size_t> children;
    };

    std::vector<PaintGeometry> paints;
    std::vector<ProgramNode> program_nodes{{}};
    UnprintableFragmentCollection unprintable_fragments;
    std::string reason_code;
    uint32_t worker_count{0};
};

uint8_t compatibilityColorByte(double value)
{
    const double clamped = std::clamp(value, 0.0, 1.0);
    return static_cast<uint8_t>(std::lround(clamped * 255.0));
}

void appendUnprintableFragment(
    UnprintableFragmentCollection& fragments,
    UnprintableReason reason,
    const std::array<double, 4>& rgbaF64,
    int32_t drawIndex,
    int32_t sourceIndex,
    SourceKind sourceKind,
    int32_t subpathIndex)
{
    if(fragments.reason_ids.size() == fragments.reason_ids.max_size()
            || fragments.rgba.size() > fragments.rgba.max_size() - 4
            || fragments.rgba_f64.size()
                > fragments.rgba_f64.max_size() - 4
            || fragments.draw_indices.size()
                == fragments.draw_indices.max_size()
            || fragments.source_indices.size()
                == fragments.source_indices.max_size()
            || fragments.source_kinds.size()
                == fragments.source_kinds.max_size()
            || fragments.subpath_indices.size()
                == fragments.subpath_indices.max_size())
        throw ComplexityLimitError();
    fragments.reason_ids.push_back(static_cast<int32_t>(reason));
    for(const double component : rgbaF64) {
        if(!std::isfinite(component) || component < 0.0 || component > 1.0)
            throw std::runtime_error("invalid_fragment_rgba");
        fragments.rgba.push_back(compatibilityColorByte(component));
    }
    fragments.rgba_f64.insert(
        fragments.rgba_f64.end(), rgbaF64.begin(), rgbaF64.end());
    fragments.draw_indices.push_back(drawIndex);
    fragments.source_indices.push_back(sourceIndex);
    fragments.source_kinds.push_back(static_cast<int32_t>(sourceKind));
    fragments.subpath_indices.push_back(subpathIndex);
}

void appendUnprintableFragment(
    UnprintableFragmentCollection& fragments,
    const FragmentIssue& issue,
    const lunasvg::PaintCommand& command,
    int32_t drawIndex)
{
    const std::array<double, 4> rgbaF64{{
        command.rgba[0] / 255.0,
        command.rgba[1] / 255.0,
        command.rgba[2] / 255.0,
        command.paint_opacity,
    }};
    appendUnprintableFragment(
        fragments, issue.reason, rgbaF64, drawIndex,
        command.source_index,
        command.kind == lunasvg::PaintCommandKind::Stroke
            ? SourceKind::Stroke : SourceKind::Fill,
        issue.subpath_index);
}

void appendUnprintableFragment(
    UnprintableFragmentCollection& fragments,
    UnprintableReason reason,
    const PaintGeometry& paint)
{
    appendUnprintableFragment(
        fragments, reason, paint.rgba_f64, paint.draw_index,
        paint.source_index, paint.source_kind, -1);
}

bool commandNeedsNormalization(const lunasvg::PaintCommand& command)
{
    return command.kind == lunasvg::PaintCommandKind::ClipBegin
        || command.kind == lunasvg::PaintCommandKind::Fill
        || command.kind == lunasvg::PaintCommandKind::Stroke;
}

constexpr size_t MAX_REPLAY_WORKERS = 16;

size_t configuredReplayWorkerCount(size_t taskCount, size_t inputPointCount)
{
    if(taskCount == 0)
        return 0;

    const auto boundedWorkerCount = [taskCount](size_t requested) {
        return std::min(
            std::min(taskCount, requested), MAX_REPLAY_WORKERS);
    };

    if(const char* value = std::getenv("LUMINA_SVG_REPLAY_THREADS")) {
        size_t requested = 0;
        const char* end = value + std::char_traits<char>::length(value);
        const auto parsed = std::from_chars(value, end, requested);
        if(parsed.ec == std::errc{} && parsed.ptr == end && requested > 0)
            return boundedWorkerCount(requested);
    }

    constexpr size_t MIN_PARALLEL_TASKS = 8;
    constexpr size_t MIN_PARALLEL_INPUT_POINTS = 1024;
    constexpr size_t MIN_AVERAGE_INPUT_POINTS = 128;
    if(taskCount < MIN_PARALLEL_TASKS
            || inputPointCount < MIN_PARALLEL_INPUT_POINTS
            || inputPointCount / taskCount < MIN_AVERAGE_INPUT_POINTS)
        return 1;
    const size_t hardwareThreads = std::max(
        size_t{1}, static_cast<size_t>(std::thread::hardware_concurrency()));
    return boundedWorkerCount(hardwareThreads);
}

std::optional<size_t> configuredReplayTestFailureAfter()
{
    const char* value = std::getenv("LUMINA_SVG_TEST_REPLAY_FAIL_AFTER");
    if(value == nullptr)
        return std::nullopt;
    size_t commandCount = 0;
    const char* end = value + std::char_traits<char>::length(value);
    const auto parsed = std::from_chars(value, end, commandCount);
    if(parsed.ec != std::errc{} || parsed.ptr != end || commandCount == 0)
        return std::nullopt;
    return commandCount;
}

struct PreparedCommandNormalization {
    PrecisionPaths geometry;
    TopologyTrace topology_trace;
    ComplexityBudget complexity_budget;
    std::exception_ptr failure;
    bool ready{false};
};

struct PreparedNormalizationBatch {
    std::vector<PreparedCommandNormalization> commands;
    size_t worker_count{0};
};

void discardPreparedNormalizations(PreparedNormalizationBatch& batch)
{
    std::vector<PreparedCommandNormalization>().swap(batch.commands);
    batch.worker_count = 1;
}

PreparedNormalizationBatch prepareCommandNormalizations(
    const std::vector<lunasvg::PaintCommand>& commands,
    const PhysicalDomain& domain,
    bool allowParallel = true)
{
    PreparedNormalizationBatch batch;
    size_t taskCount = 0;
    size_t inputPointCount = 0;
    for(const auto& command : commands) {
        if(!commandNeedsNormalization(command))
            continue;
        taskCount = checkedSizeSum(taskCount, 1);
        inputPointCount = checkedSizeSum(
            inputPointCount, command.path_points.size());
    }
    batch.worker_count = allowParallel
        ? configuredReplayWorkerCount(taskCount, inputPointCount)
        : (taskCount == 0 ? 0 : 1);
    if(batch.worker_count < 2)
        return batch;

    std::vector<size_t> taskIndices;
    try {
        taskIndices.reserve(taskCount);
        for(size_t index = 0; index < commands.size(); ++index) {
            if(commandNeedsNormalization(commands[index]))
                taskIndices.push_back(index);
        }
        batch.commands.resize(commands.size());
    } catch(const std::bad_alloc&) {
        discardPreparedNormalizations(batch);
        return batch;
    }
    std::atomic<size_t> nextTask{0};
    std::atomic<bool> taskFailed{false};
    const auto runTasks = [&]() {
        while(true) {
            if(taskFailed.load(std::memory_order_acquire))
                return;
            const size_t taskOffset = nextTask.fetch_add(
                1, std::memory_order_relaxed);
            if(taskOffset >= taskIndices.size())
                return;
            const size_t commandIndex = taskIndices[taskOffset];
            const auto& command = commands[commandIndex];
            auto& prepared = batch.commands[commandIndex];
            try {
                PhysicalDomain taskDomain = domain;
                taskDomain.complexity_budget = &prepared.complexity_budget;
                taskDomain.topology_trace = domain.topology_trace == nullptr
                    ? nullptr : &prepared.topology_trace;
                prepared.geometry = command.kind
                        == lunasvg::PaintCommandKind::Stroke
                    ? normalizeStroke(command, taskDomain)
                    : normalizeFill(command, taskDomain);
            } catch(...) {
                prepared.failure = std::current_exception();
                taskFailed.store(true, std::memory_order_release);
            }
            prepared.ready = true;
        }
    };

    std::vector<std::thread> workers;
    try {
        workers.reserve(
            batch.worker_count > 0 ? batch.worker_count - 1 : 0);
    } catch(const std::bad_alloc&) {
        discardPreparedNormalizations(batch);
        return batch;
    }
    bool threadStartFailed = false;
    for(size_t index = 1; index < batch.worker_count; ++index) {
        try {
            workers.emplace_back(runTasks);
        } catch(const std::system_error&) {
            threadStartFailed = true;
            break;
        } catch(const std::bad_alloc&) {
            threadStartFailed = true;
            break;
        }
    }
    if(threadStartFailed && workers.empty()) {
        discardPreparedNormalizations(batch);
        return batch;
    }
    batch.worker_count = workers.size() + 1;
    runTasks();
    for(auto& worker : workers)
        worker.join();
    if(taskFailed.load(std::memory_order_acquire))
        discardPreparedNormalizations(batch);
    return batch;
}

class ParallelReplayRetry : public std::exception {};

PrecisionPaths consumePreparedNormalization(
    PreparedCommandNormalization* prepared,
    const lunasvg::PaintCommand& command,
    const PhysicalDomain& domain)
{
    if(prepared == nullptr) {
        return command.kind == lunasvg::PaintCommandKind::Stroke
            ? normalizeStroke(command, domain)
            : normalizeFill(command, domain);
    }
    if(!prepared->ready)
        throw std::logic_error("missing_prepared_normalization");
    if(prepared->failure != nullptr)
        std::rethrow_exception(prepared->failure);
    domain.complexity_budget->mergeFrom(prepared->complexity_budget);
    if(domain.topology_trace != nullptr) {
        auto& destination = domain.topology_trace->boundaries;
        for(auto& boundary : prepared->topology_trace.boundaries)
            destination.emplace_back(std::move(boundary));
        std::vector<TopologyTrace::BoundaryError>().swap(
            prepared->topology_trace.boundaries);
    }
    prepared->ready = false;
    return std::move(prepared->geometry);
}

PaintReplay replayPreparedPaintCommands(
    const std::vector<lunasvg::PaintCommand>& commands,
    const PhysicalDomain& domain,
    PreparedNormalizationBatch& prepared,
    const std::optional<size_t>& testFailureAfter)
{
    if(domain.complexity_budget == nullptr)
        throw std::logic_error("missing_complexity_budget");
    PaintReplay replay;
    std::vector<PrecisionPaths> activeClips;
    std::vector<size_t> groupStack{0};
    replay.paints.reserve(commands.size());
    replay.program_nodes.reserve(commands.size() + 1);
    replay.worker_count = static_cast<uint32_t>(prepared.worker_count);
    int32_t drawIndex = 0;
    size_t consumedNormalizationCount = 0;
    const auto injectOrderedReplayFailure = [&]() {
        if(!testFailureAfter.has_value())
            return;
        ++consumedNormalizationCount;
        if(consumedNormalizationCount == *testFailureAfter)
            throw std::runtime_error("ordered_replay_test_failure");
    };
    for(size_t commandIndex = 0;
            commandIndex < commands.size(); ++commandIndex) {
        const auto& command = commands[commandIndex];
        if(command.kind == lunasvg::PaintCommandKind::GroupBegin) {
            if(groupStack.empty()) {
                replay.reason_code = "invalid_group_stack";
                return replay;
            }
            PaintReplay::ProgramNode group;
            group.opacity = command.group_opacity;
            const size_t groupIndex = replay.program_nodes.size();
            replay.program_nodes.emplace_back(std::move(group));
            replay.program_nodes[groupStack.back()].children.push_back(
                groupIndex);
            groupStack.push_back(groupIndex);
            continue;
        }
        if(command.kind == lunasvg::PaintCommandKind::GroupEnd) {
            if(groupStack.size() <= 1
                    || replay.program_nodes[groupStack.back()].opacity
                        != command.group_opacity) {
                replay.reason_code = "invalid_group_stack";
                return replay;
            }
            groupStack.pop_back();
            continue;
        }
        if(command.kind == lunasvg::PaintCommandKind::ClipBegin) {
            activeClips.push_back(consumePreparedNormalization(
                prepared.commands.empty()
                    ? nullptr : &prepared.commands[commandIndex],
                command, domain));
            injectOrderedReplayFailure();
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

        const int32_t paintDrawIndex = drawIndex++;
        PaintGeometry paint;
        auto geometry = consumePreparedNormalization(
            prepared.commands.empty()
                ? nullptr : &prepared.commands[commandIndex],
            command, domain);
        injectOrderedReplayFailure();
        geometry = applyActiveClips(
            std::move(geometry), activeClips, domain);
        for(const auto& issue : geometry.fragment_issues) {
            appendUnprintableFragment(
                replay.unprintable_fragments,
                issue, command, paintDrawIndex);
        }
        paint.paths = std::move(geometry.paths);
        paint.boundary_error_source = geometry.boundary_error_source;
        paint.input_precision_error_x_source =
            geometry.input_precision_error_x_source;
        paint.input_precision_error_y_source =
            geometry.input_precision_error_y_source;
        paint.bounds = pathsBounds(paint.paths);
        paint.rgba = command.rgba;
        paint.rgba_f64 = {{
            command.rgba[0] / 255.0,
            command.rgba[1] / 255.0,
            command.rgba[2] / 255.0,
            command.paint_opacity,
        }};
        paint.draw_index = paintDrawIndex;
        paint.source_index = command.source_index;
        paint.source_kind = command.kind == lunasvg::PaintCommandKind::Stroke
            ? SourceKind::Stroke : SourceKind::Fill;
        paint.contributors.push_back({
            paint.draw_index,
            paint.source_index,
            paint.source_kind,
            command.paint_opacity,
        });
        PaintReplay::ProgramNode paintNode;
        paintNode.kind = PaintReplay::ProgramNode::Kind::Paint;
        paintNode.paint_index = replay.paints.size();
        replay.program_nodes.emplace_back(std::move(paintNode));
        replay.program_nodes[groupStack.back()].children.push_back(
            replay.program_nodes.size() - 1);
        replay.paints.emplace_back(std::move(paint));
    }
    if(!activeClips.empty())
        replay.reason_code = "invalid_clip_stack";
    else if(groupStack.size() != 1)
        replay.reason_code = "invalid_group_stack";
    return replay;
}

PaintReplay replayPaintCommandsOnce(
    const std::vector<lunasvg::PaintCommand>& commands,
    const PhysicalDomain& domain,
    bool allowParallel)
{
    auto prepared = prepareCommandNormalizations(
        commands, domain, allowParallel);
    const bool parallelActive = !prepared.commands.empty() && allowParallel;
    const auto testFailureAfter = parallelActive
        ? configuredReplayTestFailureAfter() : std::nullopt;
    try {
        return replayPreparedPaintCommands(
            commands, domain, prepared, testFailureAfter);
    } catch(...) {
        if(parallelActive)
            throw ParallelReplayRetry();
        throw;
    }
}

PaintReplay replayPaintCommands(
    const std::vector<lunasvg::PaintCommand>& commands,
    const PhysicalDomain& domain)
{
    if(domain.complexity_budget == nullptr)
        throw std::logic_error("missing_complexity_budget");
    const ComplexityBudget budgetBeforeReplay = *domain.complexity_budget;
    const size_t topologySizeBeforeReplay = domain.topology_trace == nullptr
        ? 0 : domain.topology_trace->boundaries.size();
    try {
        return replayPaintCommandsOnce(commands, domain, true);
    } catch(const ParallelReplayRetry&) {
        *domain.complexity_budget = budgetBeforeReplay;
        if(domain.topology_trace != nullptr) {
            domain.topology_trace->boundaries.resize(
                topologySizeBeforeReplay);
        }
        return replayPaintCommandsOnce(commands, domain, false);
    }
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
                int64_t parent, ComplexityBudget& complexityBudget)
{
    if(ring.size() < 3)
        return;
    const uint64_t pointCount = collection.coordinates.size() / 2;
    const size_t additionalPoints = checkedSizeSum(ring.size(), size_t{1});
    if(pointCount > std::numeric_limits<uint64_t>::max() - additionalPoints)
        throw std::length_error("result_size_overflow");
    complexityBudget.consumeResultPoints(additionalPoints);
    const size_t additionalCoordinates = checkedSizeProduct(
        additionalPoints, size_t{2});
    if(additionalCoordinates
            > collection.coordinates.max_size()
                - collection.coordinates.size()
            || collection.ring_offsets.size()
                == collection.ring_offsets.max_size()
            || collection.hole_parent.size()
                == collection.hole_parent.max_size())
        throw ComplexityLimitError();
    for(const auto& point : ring) {
        collection.coordinates.push_back(point.x);
        collection.coordinates.push_back(point.y);
    }
    collection.coordinates.push_back(ring.front().x);
    collection.coordinates.push_back(ring.front().y);
    collection.ring_offsets.push_back(pointCount + ring.size() + 1);
    collection.hole_parent.push_back(parent);
}

void appendOuterNode(GeometryCollection& collection, const PolyPath64& outer,
                     ComplexityBudget& complexityBudget)
{
    if(outer.IsHole() || outer.Polygon().size() < 3)
        return;
    const auto outerRingIndex = static_cast<int64_t>(
        collection.ring_offsets.size() - 1);
    appendRing(collection, outer.Polygon(), -1, complexityBudget);
    for(size_t index = 0; index < outer.Count(); ++index) {
        const auto* child = outer.Child(index);
        if(child->IsHole())
            appendRing(
                collection, child->Polygon(), outerRingIndex,
                complexityBudget);
    }
    if(collection.polygon_offsets.size()
            == collection.polygon_offsets.max_size())
        throw ComplexityLimitError();
    collection.polygon_offsets.push_back(collection.ring_offsets.size() - 1);
}

void appendPolyTree(GeometryCollection& collection, const PolyTree64& tree,
                    ComplexityBudget& complexityBudget)
{
    std::vector<const PolyPath64*> pending;
    pending.reserve(tree.Count());
    for(size_t index = tree.Count(); index > 0; --index)
        pending.push_back(tree.Child(index - 1));
    while(!pending.empty()) {
        const auto* outer = pending.back();
        pending.pop_back();
        appendOuterNode(collection, *outer, complexityBudget);
        for(size_t holeIndex = outer->Count(); holeIndex > 0; --holeIndex) {
            const auto* hole = outer->Child(holeIndex - 1);
            for(size_t childIndex = hole->Count(); childIndex > 0;
                    --childIndex) {
                if(pending.size() == pending.max_size())
                    throw ComplexityLimitError();
                pending.push_back(hole->Child(childIndex - 1));
            }
        }
    }
}

// A Clipper union is correct as a filled region, but its outline can touch or
// cross itself, or a hole can touch its shell: two lobes meeting at one
// vertex, a vertex sitting on a non-adjacent edge, a collinear run shared by
// two rings, a genuine crossing, a hole that connects to the shell in two
// places and pinches the region apart. OGC consumers reject every one of
// those, so exported boundaries go through the shared canonical rule: the same
// linework and the same filled region, emitted as the filled faces, which meet
// only along their boundaries, with the shell/hole hierarchy rebuilt from
// containment and nesting parity. A union that is already canonical is emitted
// directly, unchanged.
void appendCanonicalNode(GeometryCollection& collection,
                         const lumina::canonical::CanonicalNode<int64_t>& node,
                         ComplexityBudget& complexityBudget)
{
    for(const auto& child : node.children) {
        if(child->is_hole || child->path.size() < 3)
            continue;
        const auto outerRingIndex = static_cast<int64_t>(
            collection.ring_offsets.size() - 1);
        appendRing(collection, child->path, -1, complexityBudget);
        for(const auto& hole : child->children) {
            if(hole->is_hole && hole->path.size() >= 3) {
                appendRing(
                    collection, hole->path, outerRingIndex, complexityBudget);
            }
        }
        if(collection.polygon_offsets.size()
                == collection.polygon_offsets.max_size())
            throw ComplexityLimitError();
        collection.polygon_offsets.push_back(collection.ring_offsets.size() - 1);
        for(const auto& hole : child->children) {
            if(hole->is_hole)
                appendCanonicalNode(collection, *hole, complexityBudget);
        }
    }
}

void appendCoveragePolyTree(GeometryCollection& collection,
                            const PolyTree64& tree,
                            ComplexityBudget& complexityBudget)
{
    const auto paths = lumina::canonical::PolyTreePaths<int64_t>(tree);
    // Node the linework to the grid before anything judges it. Splitting a
    // segment at a quantized node moves where the pieces meet, so the pieces
    // can meet again somewhere else; `NodeToGrid` is the shared rule's settle
    // step for that, and the face build below requires its result.
    bool already_canonical = false;
    const auto noded =
        lumina::canonical::NodeToGrid<int64_t>(paths, &already_canonical);
    // A union whose rings are simple, non-degenerate, and meet only at shared
    // vertices - at most one per ring pair - is already a legal expression of
    // its region, so it is emitted as it stands, coordinates untouched.
    if(already_canonical) {
        appendPolyTree(collection, tree, complexityBudget);
        return;
    }
    // Otherwise the same filled region is exported as the faces that meet only
    // along their boundaries, which is what an OGC consumer can model.
    lumina::canonical::CanonicalNode<int64_t> coverage;
    lumina::canonical::BuildFacesFromNoded<int64_t>(noded, coverage);
    appendCanonicalNode(collection, coverage, complexityBudget);
}

std::vector<Paths64> polyTreeComponents(const PolyTree64& tree)
{
    std::vector<Paths64> components;
    std::vector<const PolyPath64*> pending;
    pending.reserve(tree.Count());
    for(size_t index = tree.Count(); index > 0; --index)
        pending.push_back(tree.Child(index - 1));
    while(!pending.empty()) {
        const auto* outer = pending.back();
        pending.pop_back();
        if(outer->IsHole() || outer->Polygon().size() < 3)
            continue;
        Paths64 component;
        component.reserve(checkedSizeSum(outer->Count(), size_t{1}));
        component.push_back(outer->Polygon());
        for(size_t holeIndex = 0; holeIndex < outer->Count(); ++holeIndex) {
            const auto* hole = outer->Child(holeIndex);
            if(hole->IsHole() && hole->Polygon().size() >= 3)
                component.push_back(hole->Polygon());
            for(size_t childIndex = hole->Count(); childIndex > 0;
                    --childIndex) {
                if(pending.size() == pending.max_size())
                    throw ComplexityLimitError("alpha_compositor_components");
                pending.push_back(hole->Child(childIndex - 1));
            }
        }
        components.emplace_back(std::move(component));
    }
    return components;
}

size_t recordPolyTreeOutput(
    const PolyTree64& tree, ComplexityBudget& complexityBudget)
{
    size_t pointCount = 0;
    size_t ringCount = 0;
    std::vector<const PolyPath64*> pending;
    pending.reserve(tree.Count());
    for(size_t index = 0; index < tree.Count(); ++index)
        pending.push_back(tree.Child(index));
    while(!pending.empty()) {
        const auto* node = pending.back();
        pending.pop_back();
        if(node->Polygon().size() >= 3) {
            pointCount = checkedSizeSum(
                pointCount, node->Polygon().size());
            ringCount = checkedSizeSum(ringCount, size_t{1});
        }
        for(size_t index = 0; index < node->Count(); ++index)
            pending.push_back(node->Child(index));
    }
    complexityBudget.consumeClipperOutputPoints(pointCount);
    complexityBudget.consumeClipperOutputRings(ringCount);
    return ringCount;
}

bool appendGeometry(GeometryCollection& collection,
                    const PaintGeometry& geometry,
                    ComplexityBudget& complexityBudget,
                    std::vector<Paths64>* canonicalComponents = nullptr)
{
    if(geometry.paths.empty())
        return false;
    PolyTree64 tree;
    preflightNormalizedBoolean(complexityBudget, geometry.paths);
    Clipper64 clipper;
    clipper.AddSubject(geometry.paths);
    if(!clipper.Execute(ClipType::Union, FillRule::NonZero, tree))
        throw std::runtime_error("clipper_union_failed");
    recordPolyTreeOutput(tree, complexityBudget);
    if(canonicalComponents != nullptr)
        *canonicalComponents = polyTreeComponents(tree);
    // A Paths64 difference can contain a redundant oriented ring at a
    // touching boundary. Rebuilding the canonical PolyTree may remove that
    // ring without removing any filled area. Ring-count equality is therefore
    // not a validity invariant; only an empty canonical tree is a collapse.
    const size_t polygonCountBefore = collection.polygon_offsets.size();
    appendCoveragePolyTree(collection, tree, complexityBudget);
    if(collection.polygon_offsets.size() == polygonCountBefore)
        return false;

    if(collection.geometry_offsets.size()
            == collection.geometry_offsets.max_size()
            || collection.rgba.size() > collection.rgba.max_size() - 4
            || collection.rgba_f64.size()
                > collection.rgba_f64.max_size() - 4
            || collection.draw_indices.size()
                == collection.draw_indices.max_size()
            || collection.source_indices.size()
                == collection.source_indices.max_size()
            || collection.source_kinds.size()
                == collection.source_kinds.max_size()
            || collection.contributor_offsets.size()
                == collection.contributor_offsets.max_size()
            || geometry.contributors.size()
                > collection.contributor_draw_indices.max_size()
                    - collection.contributor_draw_indices.size()
            || geometry.contributors.size()
                > collection.contributor_source_indices.max_size()
                    - collection.contributor_source_indices.size()
            || geometry.contributors.size()
                > collection.contributor_source_kinds.max_size()
                    - collection.contributor_source_kinds.size()
            || geometry.contributors.size()
                > collection.contributor_weights.max_size()
                    - collection.contributor_weights.size())
        throw ComplexityLimitError();
    collection.geometry_offsets.push_back(collection.polygon_offsets.size() - 1);
    for(const double component : geometry.rgba_f64) {
        if(!std::isfinite(component) || component < 0.0 || component > 1.0)
            throw std::runtime_error("invalid_geometry_rgba");
        collection.rgba_f64.push_back(component);
        collection.rgba.push_back(compatibilityColorByte(component));
    }
    collection.draw_indices.push_back(geometry.draw_index);
    collection.source_indices.push_back(geometry.source_index);
    collection.source_kinds.push_back(
        static_cast<int32_t>(geometry.source_kind));
    for(const auto& contributor : geometry.contributors) {
        if(!std::isfinite(contributor.weight)
                || contributor.weight < 0.0
                || contributor.weight > 1.0)
            throw std::runtime_error("invalid_contributor_weight");
        collection.contributor_draw_indices.push_back(
            contributor.draw_index);
        collection.contributor_source_indices.push_back(
            contributor.source_index);
        collection.contributor_source_kinds.push_back(
            static_cast<int32_t>(contributor.source_kind));
        collection.contributor_weights.push_back(contributor.weight);
    }
    const uint64_t contributorCount =
        collection.contributor_draw_indices.size();
    collection.contributor_offsets.push_back(contributorCount);
    return true;
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
    const uint64_t contributorCount =
        collection.contributor_draw_indices.size();
    if(!offsetsAreValid(collection.ring_offsets, pointCount)
            || !offsetsAreValid(collection.polygon_offsets, ringCount)
            || !offsetsAreValid(collection.geometry_offsets, polygonCount)
            || !offsetsAreValid(
                collection.contributor_offsets, contributorCount)
            || collection.hole_parent.size() != ringCount
            || collection.rgba.size() != geometryCount * 4
            || collection.rgba_f64.size() != geometryCount * 4
            || collection.draw_indices.size() != geometryCount
            || collection.source_indices.size() != geometryCount
            || collection.source_kinds.size() != geometryCount
            || collection.contributor_offsets.size() != geometryCount + 1
            || collection.contributor_source_indices.size()
                != contributorCount
            || collection.contributor_source_kinds.size()
                != contributorCount
            || collection.contributor_weights.size() != contributorCount)
        return false;

    for(size_t geometryIndex = 0; geometryIndex < geometryCount;
            ++geometryIndex) {
        const auto sourceKind = static_cast<SourceKind>(
            collection.source_kinds[geometryIndex]);
        if(sourceKind != SourceKind::Fill
                && sourceKind != SourceKind::Stroke
                && sourceKind != SourceKind::Silhouette
                && sourceKind != SourceKind::Composite)
            return false;
        const size_t begin = static_cast<size_t>(
            collection.contributor_offsets[geometryIndex]);
        const size_t end = static_cast<size_t>(
            collection.contributor_offsets[geometryIndex + 1]);
        if(sourceKind == SourceKind::Silhouette) {
            if(begin != end)
                return false;
        } else if(begin == end) {
            return false;
        }
        double weightSum = 0.0;
        for(size_t index = begin; index < end; ++index) {
            const double weight = collection.contributor_weights[index];
            if(!std::isfinite(weight) || weight < 0.0 || weight > 1.0)
                return false;
            weightSum += weight;
        }
        for(size_t component = 0; component < 4; ++component) {
            const double value = collection.rgba_f64[
                geometryIndex * 4 + component];
            if(!std::isfinite(value) || value < 0.0 || value > 1.0)
                return false;
        }
        const double alpha = collection.rgba_f64[geometryIndex * 4 + 3];
        const double tolerance = 1e-12
            * std::max<size_t>(size_t{1}, end - begin);
        if(sourceKind != SourceKind::Silhouette
                && std::abs(weightSum - alpha) > tolerance)
            return false;
    }

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
    for(size_t index = 1; index < collection.geometry_offsets.size(); ++index) {
        if(collection.geometry_offsets[index]
                == collection.geometry_offsets[index - 1])
            return false;
    }
    for(size_t index = 0; index < collection.hole_parent.size(); ++index) {
        const int64_t parent = collection.hole_parent[index];
        if(parent < -1 || parent >= static_cast<int64_t>(index))
            return false;
    }
    return true;
}

bool unprintableLayoutIsValid(
    const UnprintableFragmentCollection& fragments)
{
    const uint64_t count = fragments.count();
    return fragments.rgba.size() == count * 4
        && fragments.rgba_f64.size() == count * 4
        && fragments.draw_indices.size() == count
        && fragments.source_indices.size() == count
        && fragments.source_kinds.size() == count
        && fragments.subpath_indices.size() == count;
}

bool resultCensusIsValid(const NativeResult& result)
{
    const bool layoutsValid = collectionLayoutIsValid(result.raw)
        && collectionLayoutIsValid(result.visible)
        && collectionLayoutIsValid(result.silhouette)
        && unprintableLayoutIsValid(result.unprintable_fragments)
        && result.raw.geometryCount() <= result.input_paint_count;
    if(!layoutsValid)
        return false;
    if(result.raw.geometryCount() == 0
            && result.visible.geometryCount() == 0)
        return result.silhouette.geometryCount() == 0;
    return result.silhouette.geometryCount() == 1
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

struct CoverageBatch {
    Paths64 paths;
    std::unique_ptr<PackedGridBoundsIndex> index;
    GridBounds bounds;
    size_t paint_count{0};

    size_t weight() const
    {
        return paint_count;
    }
};

Paths64 mergeNormalizedCoverage(Paths64 left, Paths64 right,
                                ComplexityBudget& complexityBudget)
{
    if(left.empty())
        return right;
    if(right.empty())
        return left;

    const auto leftBounds = individualPathBounds(left);
    const PackedGridBoundsIndex rightIndex(individualPathBounds(right));
    const size_t leftCount = left.size();
    const size_t totalCount = checkedSizeSum(leftCount, right.size());
    std::vector<size_t> parents(totalCount);
    std::vector<uint8_t> ranks(totalCount, 0);
    std::iota(parents.begin(), parents.end(), size_t{0});
    const auto findRoot = [&](size_t item) {
        size_t root = item;
        while(parents[root] != root)
            root = parents[root];
        while(parents[item] != item) {
            const size_t parent = parents[item];
            parents[item] = root;
            item = parent;
        }
        return root;
    };
    const auto unite = [&](size_t first, size_t second) {
        size_t firstRoot = findRoot(first);
        size_t secondRoot = findRoot(second);
        if(firstRoot == secondRoot)
            return;
        if(ranks[firstRoot] < ranks[secondRoot])
            std::swap(firstRoot, secondRoot);
        parents[secondRoot] = firstRoot;
        if(ranks[firstRoot] == ranks[secondRoot])
            ++ranks[firstRoot];
    };

    bool hasCrossOverlap = false;
    for(size_t index = 0; index < leftBounds.size(); ++index) {
        const auto matches = rightIndex.matches(
            leftBounds[index], complexityBudget);
        for(const size_t match : matches) {
            unite(index, checkedSizeSum(leftCount, match));
            hasCrossOverlap = true;
        }
    }
    if(!hasCrossOverlap) {
        left.reserve(totalCount);
        for(auto& path : right)
            left.emplace_back(std::move(path));
        return left;
    }

    constexpr size_t NO_GROUP = std::numeric_limits<size_t>::max();
    std::vector<size_t> rootGroups(totalCount, NO_GROUP);
    std::vector<Paths64> groups;
    groups.reserve(totalCount);
    const auto appendToGroup = [&](size_t item, Path64 path) {
        const size_t root = findRoot(item);
        size_t& groupIndex = rootGroups[root];
        if(groupIndex == NO_GROUP) {
            groupIndex = groups.size();
            groups.emplace_back();
        }
        groups[groupIndex].emplace_back(std::move(path));
    };
    for(size_t index = 0; index < left.size(); ++index)
        appendToGroup(index, std::move(left[index]));
    for(size_t index = 0; index < right.size(); ++index)
        appendToGroup(leftCount + index, std::move(right[index]));

    Paths64 merged;
    for(auto& group : groups) {
        if(group.size() == 1) {
            merged.emplace_back(std::move(group.front()));
            continue;
        }
        preflightNormalizedBoolean(complexityBudget, group);
        auto normalized = executeClipperBoolean(
            ClipType::Union, FillRule::NonZero,
            group, nullptr, complexityBudget);
        consumeClipperOutput(complexityBudget, normalized);
        const size_t required = checkedSizeSum(
            merged.size(), normalized.size());
        merged.reserve(required);
        for(auto& path : normalized)
            merged.emplace_back(std::move(path));
    }
    return merged;
}

struct SurfaceCell {
    Paths64 paths;
    GridBounds bounds;
    std::shared_ptr<PackedGridBoundsIndex> path_bounds_index;
    std::array<double, 3> premultiplied_rgb{{0, 0, 0}};
    double alpha{0};
    std::vector<PaintContributor> contributors;
};

using Surface = std::vector<SurfaceCell>;

void updateSurfaceCellGeometry(SurfaceCell& cell, Paths64 paths)
{
    cell.paths = std::move(paths);
    cell.bounds = pathsBounds(cell.paths);
    if(cell.paths.size() > 16) {
        cell.path_bounds_index = std::make_shared<PackedGridBoundsIndex>(
            individualPathBounds(cell.paths));
    } else {
        cell.path_bounds_index.reset();
    }
}

const Paths64& relevantComponentPaths(
    const SurfaceCell& cell, const GridBounds& query,
    ComplexityBudget& complexityBudget, Paths64& selected)
{
    if(cell.path_bounds_index == nullptr)
        return cell.paths;
    auto matches = cell.path_bounds_index->matches(
        query, complexityBudget);
    if(matches.size() == cell.paths.size())
        return cell.paths;
    std::sort(matches.begin(), matches.end());
    selected.reserve(matches.size());
    for(const size_t match : matches)
        selected.push_back(cell.paths.at(match));
    return selected;
}

std::vector<Paths64> partitionNormalizedPaths(
    Paths64 paths, ComplexityBudget& complexityBudget);

bool sameContributor(const PaintContributor& left,
                     const PaintContributor& right)
{
    return left.draw_index == right.draw_index
        && left.source_index == right.source_index
        && left.source_kind == right.source_kind
        && left.weight == right.weight;
}

bool sameSurfaceStyle(const SurfaceCell& left, const SurfaceCell& right)
{
    return left.premultiplied_rgb == right.premultiplied_rgb
        && left.alpha == right.alpha
        && left.contributors.size() == right.contributors.size()
        && std::equal(
            left.contributors.begin(), left.contributors.end(),
            right.contributors.begin(), sameContributor);
}

size_t surfaceStyleHash(const SurfaceCell& cell)
{
    size_t hash = std::hash<double>{}(cell.alpha);
    const auto include = [&](size_t value) {
        hash ^= value + 0x9e3779b97f4a7c15ULL
            + (hash << 6) + (hash >> 2);
    };
    for(const double component : cell.premultiplied_rgb)
        include(std::hash<double>{}(component));
    include(cell.contributors.size());
    for(const auto& contributor : cell.contributors) {
        include(std::hash<int32_t>{}(contributor.draw_index));
        include(std::hash<int32_t>{}(contributor.source_index));
        include(std::hash<int32_t>{}(
            static_cast<int32_t>(contributor.source_kind)));
        include(std::hash<double>{}(contributor.weight));
    }
    return hash;
}

void appendMovedPaths(Paths64& destination, Paths64& source)
{
    if(source.size() > destination.max_size() - destination.size())
        throw ComplexityLimitError("alpha_compositor_paths");
    destination.reserve(destination.size() + source.size());
    for(auto& path : source)
        destination.emplace_back(std::move(path));
}

Surface consolidateSurface(Surface cells)
{
    Surface consolidated;
    consolidated.reserve(cells.size());
    std::unordered_multimap<size_t, size_t> styleIndices;
    styleIndices.reserve(cells.size());
    for(auto& cell : cells) {
        if(cell.paths.empty() || !(cell.alpha > 0.0))
            continue;
        const size_t hash = surfaceStyleHash(cell);
        const auto range = styleIndices.equal_range(hash);
        auto match = range.second;
        for(auto candidate = range.first; candidate != range.second;
                ++candidate) {
            if(sameSurfaceStyle(
                    consolidated[candidate->second], cell)) {
                match = candidate;
                break;
            }
        }
        if(match == range.second) {
            styleIndices.emplace(hash, consolidated.size());
            consolidated.emplace_back(std::move(cell));
            continue;
        }
        auto& destination = consolidated[match->second];
        appendMovedPaths(destination.paths, cell.paths);
        destination.bounds.include(cell.bounds);
    }
    return consolidated;
}

std::vector<Paths64> executeNormalizedBooleanComponents(
    ClipType clipType, const Paths64& subjects, const Paths64& clips,
    ComplexityBudget& complexityBudget)
{
    preflightNormalizedBoolean(complexityBudget, subjects, clips);
    PolyTree64 tree;
    Clipper64 clipper;
    clipper.AddSubject(subjects);
    clipper.AddClip(clips);
    if(!clipper.Execute(clipType, FillRule::NonZero, tree))
        throw std::runtime_error("clipper_boolean_failed");
    recordPolyTreeOutput(tree, complexityBudget);
    return polyTreeComponents(tree);
}

SurfaceCell blendedCell(const SurfaceCell& destination,
                        const SurfaceCell& source, Paths64 paths)
{
    SurfaceCell result;
    result.paths = std::move(paths);
    result.bounds = pathsBounds(result.paths);
    const double retainedDestination = 1.0 - source.alpha;
    result.alpha = source.alpha
        + destination.alpha * retainedDestination;
    for(size_t component = 0; component < 3; ++component) {
        result.premultiplied_rgb[component] =
            source.premultiplied_rgb[component]
            + destination.premultiplied_rgb[component]
                * retainedDestination;
    }
    result.contributors.reserve(checkedSizeSum(
        destination.contributors.size(), source.contributors.size()));
    if(retainedDestination > 0.0) {
        for(const auto& contributor : destination.contributors) {
            const double weight = contributor.weight
                * retainedDestination;
            if(weight > 0.0) {
                auto retained = contributor;
                retained.weight = weight;
                result.contributors.emplace_back(std::move(retained));
            }
        }
    }
    for(const auto& contributor : source.contributors) {
        if(contributor.weight > 0.0)
            result.contributors.push_back(contributor);
    }
    return result;
}

void appendComponentCells(
    Surface& destination, const SurfaceCell& style,
    std::vector<Paths64> components,
    ComplexityBudget& complexityBudget);

void appendSpatialCell(
    Surface& destination, const SurfaceCell& style, Paths64 paths,
    ComplexityBudget& complexityBudget, size_t depth)
{
    constexpr size_t MAX_CELL_POINTS = 512;
    constexpr size_t MAX_TILE_DEPTH = 16;
    const GridBounds bounds = pathsBounds(paths);
    const int64_t width = bounds.valid
        ? bounds.max_x - bounds.min_x : 0;
    const int64_t height = bounds.valid
        ? bounds.max_y - bounds.min_y : 0;
    if(pathPointCount(paths) <= MAX_CELL_POINTS
            || depth >= MAX_TILE_DEPTH
            || (width <= 1 && height <= 1)) {
        SurfaceCell component;
        updateSurfaceCellGeometry(component, std::move(paths));
        component.premultiplied_rgb = style.premultiplied_rgb;
        component.alpha = style.alpha;
        component.contributors = style.contributors;
        destination.emplace_back(std::move(component));
        return;
    }

    Clipper2Lib::Rect64 firstRect;
    Clipper2Lib::Rect64 secondRect;
    if(width >= height && width > 1) {
        const int64_t middle = bounds.min_x + width / 2;
        firstRect = Clipper2Lib::Rect64(
            bounds.min_x, bounds.min_y, middle, bounds.max_y);
        secondRect = Clipper2Lib::Rect64(
            middle, bounds.min_y, bounds.max_x, bounds.max_y);
    } else {
        const int64_t middle = bounds.min_y + height / 2;
        firstRect = Clipper2Lib::Rect64(
            bounds.min_x, bounds.min_y, bounds.max_x, middle);
        secondRect = Clipper2Lib::Rect64(
            bounds.min_x, middle, bounds.max_x, bounds.max_y);
    }
    consumeBooleanInputs(complexityBudget, paths);
    auto first = Clipper2Lib::RectClip(firstRect, paths);
    consumeClipperOutput(complexityBudget, first);
    consumeBooleanInputs(complexityBudget, paths);
    auto second = Clipper2Lib::RectClip(secondRect, paths);
    consumeClipperOutput(complexityBudget, second);
    if(!first.empty()) {
        appendSpatialCell(
            destination, style, std::move(first),
            complexityBudget, depth + 1);
    }
    if(!second.empty()) {
        appendSpatialCell(
            destination, style, std::move(second),
            complexityBudget, depth + 1);
    }
}

void appendComponentCells(
    Surface& destination, const SurfaceCell& style,
    std::vector<Paths64> components,
    ComplexityBudget& complexityBudget)
{
    for(auto& componentPaths : components) {
        appendSpatialCell(
            destination, style, std::move(componentPaths),
            complexityBudget, 0);
    }
}

void compositeSurfaceOntoSurface(Surface& destination, Surface source,
                                 ComplexityBudget& complexityBudget)
{
    if(source.empty())
        return;
    if(destination.empty()) {
        destination = std::move(source);
        return;
    }

    std::vector<GridBounds> sourceBounds;
    sourceBounds.reserve(source.size());
    for(const auto& cell : source)
        sourceBounds.push_back(cell.bounds);
    const PackedGridBoundsIndex sourceIndex(std::move(sourceBounds));

    std::vector<Paths64> destinationCoverageBySource(source.size());
    Surface next;
    next.reserve(checkedSizeSum(destination.size(), source.size()));
    for(auto& destinationCell : destination) {
        const auto candidates = sourceIndex.matches(
            destinationCell.bounds, complexityBudget);
        Paths64 sourceCoverage;
        bool hasIntersection = false;
        for(const size_t sourceCellIndex : candidates) {
            Paths64 selectedDestinationPaths;
            Paths64 selectedSourcePaths;
            const auto& destinationPaths = relevantComponentPaths(
                destinationCell, source[sourceCellIndex].bounds,
                complexityBudget, selectedDestinationPaths);
            const auto& sourcePathsForIntersection = relevantComponentPaths(
                source[sourceCellIndex], destinationCell.bounds,
                complexityBudget, selectedSourcePaths);
            auto intersectionComponents =
                executeNormalizedBooleanComponents(
                ClipType::Intersection,
                destinationPaths,
                sourcePathsForIntersection,
                complexityBudget);
            if(intersectionComponents.empty())
                continue;
            hasIntersection = true;

            const auto& sourcePaths = source[sourceCellIndex].paths;
            const size_t sourceCoverageSize = checkedSizeSum(
                sourceCoverage.size(), sourcePaths.size());
            sourceCoverage.reserve(sourceCoverageSize);
            sourceCoverage.insert(
                sourceCoverage.end(), sourcePaths.begin(), sourcePaths.end());

            auto& destinationCoverage =
                destinationCoverageBySource[sourceCellIndex];
            const size_t destinationCoverageSize = checkedSizeSum(
                destinationCoverage.size(), destinationCell.paths.size());
            destinationCoverage.reserve(destinationCoverageSize);
            destinationCoverage.insert(
                destinationCoverage.end(),
                destinationCell.paths.begin(), destinationCell.paths.end());
            const auto blendedStyle = blendedCell(
                destinationCell, source[sourceCellIndex], {});
            appendComponentCells(
                next, blendedStyle,
                std::move(intersectionComponents), complexityBudget);
        }

        if(!hasIntersection) {
            next.emplace_back(std::move(destinationCell));
            continue;
        }

        auto destinationOnly = executeNormalizedBooleanComponents(
            ClipType::Difference,
            destinationCell.paths, sourceCoverage, complexityBudget);
        appendComponentCells(
            next, destinationCell,
            std::move(destinationOnly), complexityBudget);
    }

    for(size_t sourceCellIndex = 0;
            sourceCellIndex < source.size(); ++sourceCellIndex) {
        auto& sourceCell = source[sourceCellIndex];
        const auto& destinationCoverage =
            destinationCoverageBySource[sourceCellIndex];
        if(destinationCoverage.empty()) {
            next.emplace_back(std::move(sourceCell));
            continue;
        }
        auto sourceOnly = executeNormalizedBooleanComponents(
            ClipType::Difference,
            sourceCell.paths, destinationCoverage, complexityBudget);
        if(sourceOnly.empty())
            continue;
        appendComponentCells(
            next, sourceCell,
            std::move(sourceOnly), complexityBudget);
    }
    destination = std::move(next);
}

Surface surfaceForPaint(PaintGeometry& paint,
                        ComplexityBudget& complexityBudget)
{
    if(paint.paths.empty() || !(paint.rgba_f64[3] > 0.0))
        return {};
    Surface surface;
    SurfaceCell style;
    style.alpha = paint.rgba_f64[3];
    for(size_t component = 0; component < 3; ++component) {
        style.premultiplied_rgb[component] =
            paint.rgba_f64[component] * style.alpha;
    }
    style.contributors = std::move(paint.contributors);
    appendComponentCells(
        surface, style, std::move(paint.components), complexityBudget);
    return surface;
}

void applyGroupOpacity(Surface& surface, double opacity)
{
    if(opacity == 1.0)
        return;
    if(!(opacity > 0.0)) {
        surface.clear();
        return;
    }
    for(auto& cell : surface) {
        cell.alpha *= opacity;
        for(double& component : cell.premultiplied_rgb)
            component *= opacity;
        for(auto& contributor : cell.contributors)
            contributor.weight *= opacity;
    }
}

Surface renderProgramNode(
    size_t nodeIndex,
    const std::vector<PaintReplay::ProgramNode>& programNodes,
    std::vector<PaintGeometry>& paints,
    ComplexityBudget& complexityBudget);

Surface renderProgramChildren(
    const std::vector<size_t>& children, size_t begin, size_t end,
    const std::vector<PaintReplay::ProgramNode>& programNodes,
    std::vector<PaintGeometry>& paints,
    ComplexityBudget& complexityBudget)
{
    if(begin == end)
        return {};
    if(end - begin == 1) {
        return renderProgramNode(
            children[begin], programNodes, paints, complexityBudget);
    }
    const size_t middle = begin + (end - begin) / 2;
    auto destination = renderProgramChildren(
        children, begin, middle,
        programNodes, paints, complexityBudget);
    auto source = renderProgramChildren(
        children, middle, end,
        programNodes, paints, complexityBudget);
    compositeSurfaceOntoSurface(
        destination, std::move(source), complexityBudget);
    return destination;
}

Surface renderProgramNode(
    size_t nodeIndex,
    const std::vector<PaintReplay::ProgramNode>& programNodes,
    std::vector<PaintGeometry>& paints,
    ComplexityBudget& complexityBudget)
{
    if(nodeIndex >= programNodes.size())
        throw std::runtime_error("invalid_paint_program");
    const auto& node = programNodes[nodeIndex];
    if(node.kind == PaintReplay::ProgramNode::Kind::Paint) {
        if(node.paint_index >= paints.size())
            throw std::runtime_error("invalid_paint_program");
        return surfaceForPaint(
            paints[node.paint_index], complexityBudget);
    }

    auto surface = renderProgramChildren(
        node.children, 0, node.children.size(),
        programNodes, paints, complexityBudget);
    applyGroupOpacity(surface, node.opacity);
    return surface;
}

struct AlphaComposite {
    std::vector<PaintGeometry> visible;
    Paths64 silhouette;
};

AlphaComposite compositeAlphaProgram(
    std::vector<PaintGeometry>& paints,
    const std::vector<PaintReplay::ProgramNode>& programNodes,
    const PhysicalDomain& domain)
{
    if(domain.complexity_budget == nullptr || programNodes.empty())
        throw std::logic_error("missing_alpha_compositor_state");
    auto& complexityBudget = *domain.complexity_budget;
    auto surface = renderProgramNode(
        0, programNodes, paints, complexityBudget);

    AlphaComposite composite;
    std::vector<CoverageBatch> silhouetteBatches;
    const auto mergeSilhouetteBatch = [&](CoverageBatch left,
                                          CoverageBatch right) {
        CoverageBatch merged;
        if(!left.bounds.intersects(right.bounds)) {
            appendMovedPaths(left.paths, right.paths);
            merged.paths = std::move(left.paths);
        } else {
            merged.paths = mergeNormalizedCoverage(
                std::move(left.paths), std::move(right.paths),
                complexityBudget);
        }
        merged.bounds = left.bounds;
        merged.bounds.include(right.bounds);
        merged.paint_count = checkedSizeSum(
            left.paint_count, right.paint_count);
        return merged;
    };
    for(const auto& cell : surface) {
        CoverageBatch batch;
        batch.paths = cell.paths;
        batch.bounds = cell.bounds;
        batch.paint_count = 1;
        while(!silhouetteBatches.empty()
                && silhouetteBatches.back().weight()
                    == batch.weight()) {
            auto previous = std::move(silhouetteBatches.back());
            silhouetteBatches.pop_back();
            batch = mergeSilhouetteBatch(
                std::move(previous), std::move(batch));
        }
        silhouetteBatches.emplace_back(std::move(batch));
    }
    for(auto& batch : silhouetteBatches) {
        composite.silhouette = mergeNormalizedCoverage(
            std::move(composite.silhouette),
            std::move(batch.paths), complexityBudget);
    }

    surface = consolidateSurface(std::move(surface));
    composite.visible.reserve(surface.size());
    for(auto& cell : surface) {
        if(!(cell.alpha > 0.0))
            continue;
        PaintGeometry geometry;
        geometry.paths = std::move(cell.paths);
        geometry.bounds = cell.bounds;
        geometry.rgba_f64[3] = cell.alpha;
        for(size_t component = 0; component < 3; ++component) {
            geometry.rgba_f64[component] = std::clamp(
                cell.premultiplied_rgb[component] / cell.alpha,
                0.0, 1.0);
        }
        for(size_t component = 0; component < 4; ++component) {
            geometry.rgba[component] = compatibilityColorByte(
                geometry.rgba_f64[component]);
        }
        geometry.contributors = std::move(cell.contributors);
        if(geometry.contributors.size() == 1) {
            const auto& contributor = geometry.contributors.front();
            geometry.draw_index = contributor.draw_index;
            geometry.source_index = contributor.source_index;
            geometry.source_kind = contributor.source_kind;
        } else {
            geometry.draw_index = -1;
            geometry.source_index = -1;
            geometry.source_kind = SourceKind::Composite;
        }
        composite.visible.emplace_back(std::move(geometry));
    }
    return composite;
}

bool requiresAlphaCompositing(
    const std::vector<lunasvg::PaintCommand>& commands)
{
    return std::any_of(
        commands.begin(), commands.end(),
        [](const lunasvg::PaintCommand& command) {
            if(command.kind == lunasvg::PaintCommandKind::GroupBegin)
                return command.group_opacity != 1.0;
            return (command.kind == lunasvg::PaintCommandKind::Fill
                    || command.kind == lunasvg::PaintCommandKind::Stroke)
                && command.paint_opacity != 1.0;
        });
}

std::vector<Paths64> partitionNormalizedPaths(
    Paths64 paths, ComplexityBudget& complexityBudget)
{
    if(paths.empty())
        return {};
    if(paths.size() == 1)
        return {paths};

    const auto bounds = individualPathBounds(paths);
    const PackedGridBoundsIndex index(bounds);
    std::vector<size_t> parents(paths.size());
    std::vector<uint8_t> ranks(paths.size(), 0);
    std::iota(parents.begin(), parents.end(), size_t{0});
    const auto findRoot = [&](size_t item) {
        size_t root = item;
        while(parents[root] != root)
            root = parents[root];
        while(parents[item] != item) {
            const size_t parent = parents[item];
            parents[item] = root;
            item = parent;
        }
        return root;
    };
    const auto unite = [&](size_t first, size_t second) {
        size_t firstRoot = findRoot(first);
        size_t secondRoot = findRoot(second);
        if(firstRoot == secondRoot)
            return;
        if(ranks[firstRoot] < ranks[secondRoot])
            std::swap(firstRoot, secondRoot);
        parents[secondRoot] = firstRoot;
        if(ranks[firstRoot] == ranks[secondRoot])
            ++ranks[firstRoot];
    };
    for(size_t pathIndex = 0; pathIndex < paths.size(); ++pathIndex) {
        const auto matches = index.matches(
            bounds[pathIndex], complexityBudget);
        for(const size_t match : matches) {
            if(match > pathIndex)
                unite(pathIndex, match);
        }
    }

    constexpr size_t NO_GROUP = std::numeric_limits<size_t>::max();
    std::vector<size_t> rootGroups(paths.size(), NO_GROUP);
    std::vector<Paths64> groups;
    groups.reserve(paths.size());
    for(size_t pathIndex = 0; pathIndex < paths.size(); ++pathIndex) {
        const size_t root = findRoot(pathIndex);
        size_t& groupIndex = rootGroups[root];
        if(groupIndex == NO_GROUP) {
            groupIndex = groups.size();
            groups.emplace_back();
        }
        groups[groupIndex].push_back(std::move(paths[pathIndex]));
    }
    return groups;
}

struct PaintPathsLess {
    const std::vector<PaintGeometry>& paints;

    bool operator()(size_t left, size_t right) const
    {
        const auto& leftPaths = paints[left].paths;
        const auto& rightPaths = paints[right].paths;
        return std::lexicographical_compare(
            leftPaths.begin(), leftPaths.end(),
            rightPaths.begin(), rightPaths.end(),
            [](const Path64& first, const Path64& second) {
                return std::lexicographical_compare(
                    first.begin(), first.end(), second.begin(), second.end(),
                    [](const Point64& firstPoint, const Point64& secondPoint) {
                        return firstPoint.x < secondPoint.x
                            || (firstPoint.x == secondPoint.x
                                && firstPoint.y < secondPoint.y);
                    });
            });
    }
};

CompositedPaths compositePaints(const std::vector<PaintGeometry>& paints,
                                const PhysicalDomain& domain)
{
    auto& complexityBudget = *domain.complexity_budget;
    CompositedPaths composited;
    composited.visible.resize(paints.size());
    size_t retainedPointCount = 0;
    size_t retainedRingCount = 0;
    const auto retainGeometry = [&](const Paths64& paths) {
        const size_t points = pathPointCount(paths);
        retainedPointCount = checkedSizeSum(retainedPointCount, points);
        retainedRingCount = checkedSizeSum(
            retainedRingCount, paths.size());
    };

    // Keep later paint coverage in binary-sized spatial batches. Overlapping
    // paths are normalized while batches merge, and each resulting path has a
    // packed bounds entry. A subject component therefore queries at most
    // log2(N) indexes and sends only spatially relevant coverage rings to
    // Clipper, without rebuilding the entire later-paint suffix per draw.
    std::vector<CoverageBatch> coverageBatches;
    // Store indices into immutable paints; compare geometry directly with
    // logarithmic lookup and no copied paths or content fingerprints.
    std::set<size_t, PaintPathsLess> laterPaints(PaintPathsLess{paints});
    const auto mergeCoverage = [&](CoverageBatch left,
                                   CoverageBatch right) {
        CoverageBatch merged;
        if(!left.bounds.intersects(right.bounds)) {
            left.paths.reserve(checkedSizeSum(
                left.paths.size(), right.paths.size()));
            for(auto& path : right.paths)
                left.paths.emplace_back(std::move(path));
            merged.paths = std::move(left.paths);
        } else {
            merged.paths = mergeNormalizedCoverage(
                std::move(left.paths), std::move(right.paths),
                complexityBudget);
        }
        merged.paint_count = checkedSizeSum(
            left.paint_count, right.paint_count);
        merged.index = std::make_unique<PackedGridBoundsIndex>(
            individualPathBounds(merged.paths));
        merged.bounds = left.bounds;
        merged.bounds.include(right.bounds);
        return merged;
    };

    for(size_t reverseIndex = paints.size(); reverseIndex > 0; --reverseIndex) {
        const size_t index = reverseIndex - 1;
        if(!laterPaints.insert(index).second) {
            composited.visible[index] = {};
        } else {
            Paths64 visible;
            for(auto& subject : partitionNormalizedPaths(
                    paints[index].paths, complexityBudget)) {
                const GridBounds subjectBounds = pathsBounds(subject);
                Paths64 occluders;
                for(const auto& batch : coverageBatches) {
                    if(!batch.bounds.intersects(subjectBounds))
                        continue;
                    const auto matches = batch.index->matches(
                        subjectBounds, complexityBudget);
                    occluders.reserve(checkedSizeSum(
                        occluders.size(), matches.size()));
                    for(const size_t match : matches)
                        occluders.push_back(batch.paths.at(match));
                }
                if(!occluders.empty()) {
                    preflightNormalizedBoolean(
                        complexityBudget, subject, occluders);
                    subject = executeClipperBoolean(
                        ClipType::Difference, FillRule::NonZero,
                        subject, &occluders, complexityBudget);
                    consumeClipperOutput(complexityBudget, subject);
                }
                const size_t required = checkedSizeSum(
                    visible.size(), subject.size());
                visible.reserve(required);
                for(auto& path : subject)
                    visible.emplace_back(std::move(path));
            }
            retainGeometry(visible);
            composited.visible[index] = std::move(visible);
            if(!composited.visible[index].empty()) {
                CoverageBatch batch;
                // Coverage is the union of source paint regions, not the
                // partitioned visible pieces. Integer difference can place a
                // visible boundary one grid unit inside its occluder; using
                // those pieces for the silhouette would turn that numeric
                // seam into a false component. The raw paint is exact input
                // coverage, while the visible bounds index below remains the
                // spatial accelerator for lower-paint subtraction.
                batch.paths = paints[index].paths;
                batch.paint_count = 1;
                batch.index = std::make_unique<PackedGridBoundsIndex>(
                    individualPathBounds(batch.paths));
                batch.bounds = pathsBounds(batch.paths);
                while(!coverageBatches.empty()
                        && coverageBatches.back().weight()
                            == batch.weight()) {
                    auto previous = std::move(coverageBatches.back());
                    coverageBatches.pop_back();
                    batch = mergeCoverage(
                        std::move(previous), std::move(batch));
                }
                coverageBatches.emplace_back(std::move(batch));
            }
        }
    }

    for(auto& batch : coverageBatches) {
        composited.silhouette = mergeNormalizedCoverage(
            std::move(composited.silhouette),
            std::move(batch.paths), complexityBudget);
    }
    retainGeometry(composited.silhouette);
    return composited;
}

std::shared_ptr<NativeResult> buildResult(RecorderResult recording,
                                          double targetWidthMm,
                                          double toleranceMm)
{
    auto result = std::make_shared<NativeResult>();
    const auto buildStarted = std::chrono::steady_clock::now();
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
    result->input_paint_count = static_cast<uint64_t>(std::count_if(
        recording.commands.begin(), recording.commands.end(),
        [](const lunasvg::PaintCommand& command) {
            return command.kind == lunasvg::PaintCommandKind::Fill
                || command.kind == lunasvg::PaintCommandKind::Stroke;
        }));
    requireFiniteRecording(recording.commands, recording.viewport);
    ComplexityBudget complexityBudget;
    result->max_flattening_error_mm = toleranceMm * 0.4;
    const bool hasClipCommands = std::any_of(
        recording.commands.begin(), recording.commands.end(),
        [](const lunasvg::PaintCommand& command) {
            return command.kind == lunasvg::PaintCommandKind::ClipBegin;
        });
    const double maximumInputErrorSource =
        maximumInputPrecisionErrorSource(
            recording.commands, recording.viewport,
            !hasClipCommands);
    SourceBounds sourceBounds = exactPaintBounds(
        recording.commands, complexityBudget);
    includeViewport(sourceBounds, recording.viewport);
    if(!sourceBounds.valid()) {
        result->reason_code = "empty_geometry";
        return result;
    }
    const double initialScale = targetWidthMm
        / (sourceBounds.max_x - sourceBounds.min_x);
    if(!isPositiveFinite(initialScale)
            || !std::isfinite(maximumInputErrorSource)
            || maximumInputErrorSource * initialScale
                > toleranceMm * 0.6) {
        result->status = "unsupported";
        result->reason_code = "unsupported_input_precision";
        return result;
    }

    const bool hasStrokeCommands = std::any_of(
        recording.commands.begin(), recording.commands.end(),
        [](const lunasvg::PaintCommand& command) {
            return command.kind == lunasvg::PaintCommandKind::Stroke;
        });
    const double maximumFinalFlatteningBudgetMm = toleranceMm
        * (hasClipCommands ? 0.35 : 0.4);
    const double finalQuantizationBudgetMm = toleranceMm
        * (hasClipCommands ? 0.05 : 0.15);
    const double strokeQuantizationBudgetMm = toleranceMm * 0.05;
    const double budgetGridStepMm = finalQuantizationBudgetMm
        * std::sqrt(2.0);
    ClipBoundsPlan boundsPlan;
    if(hasClipCommands) {
        boundsPlan = buildClipBoundsPlan(
            recording.commands, complexityBudget);
    } else {
        boundsPlan.coordinate_bounds = sourceBounds;
    }
    if(hasClipCommands && !boundsPlan.coordinate_bounds.valid()) {
        result->status = "unsupported";
        result->reason_code = "unsupported_clipped_geometry";
        return result;
    }
    const bool needsClipBoundsPass = hasClipCommands
        && boundsPlan.clipped_paint_bounds.valid();
    if(needsClipBoundsPass) {
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
            nullptr,
            &complexityBudget,
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
            nullptr,
            &complexityBudget,
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
    const double inputAndQuantizationErrorMm =
        maximumInputErrorSource * result->scale_factor
        + result->max_quantization_error_mm;
    if(inputAndQuantizationErrorMm
            > toleranceMm * 0.6) {
        result->status = "unsupported";
        result->reason_code = "unsupported_input_precision";
        return result;
    }
    // Input decoding, curve flattening, and grid quantization share one
    // physical boundary budget. A fixed flattening slice needlessly rejects
    // accurate paths whose conservative input allowance is larger than the
    // common case. Tighten flattening for those paths instead of charging
    // both stages independently and falling back.
    const double remainingBoundaryBudgetMm =
        toleranceMm * 0.6 - inputAndQuantizationErrorMm;
    const double finalFlatteningBudgetMm = std::min(
        maximumFinalFlatteningBudgetMm,
        remainingBoundaryBudgetMm
            * 0.95);
    if(!isPositiveFinite(finalFlatteningBudgetMm)) {
        result->status = "unsupported";
        result->reason_code = "unsupported_input_precision";
        return result;
    }
    result->max_flattening_error_mm = finalFlatteningBudgetMm;
    TopologyTrace topologyTrace;
    const PhysicalDomain domain{
        sourceBounds.min_x,
        sourceBounds.min_y,
        result->scale_factor,
        gridStepMm,
        finalFlatteningBudgetMm,
        strokeQuantizationBudgetMm,
        &topologyTrace,
        &complexityBudget,
    };

    const auto replayStarted = std::chrono::steady_clock::now();
    result->bounds_seconds = std::chrono::duration<double>(
        replayStarted - buildStarted).count();
    auto replay = replayPaintCommands(recording.commands, domain);
    result->replay_worker_count = static_cast<uint32_t>(
        replay.worker_count);
    const auto topologyStarted = std::chrono::steady_clock::now();
    result->replay_seconds = std::chrono::duration<double>(
        topologyStarted - replayStarted).count();
    if(!replay.reason_code.empty()) {
        result->reason_code = replay.reason_code;
        return result;
    }
    result->unprintable_fragments = std::move(
        replay.unprintable_fragments);
    if(!hasNonEmptyPaint(replay.paints)) {
        if(!resultCensusIsValid(*result))
            throw std::runtime_error("native_result_census_failed");
        result->status = "supported";
        result->reason_code.clear();
        return result;
    }
    auto paints = std::move(replay.paints);
    auto programNodes = std::move(replay.program_nodes);
    const bool alphaCompositingRequired = requiresAlphaCompositing(
        recording.commands);
    const double maximumRecordedBoundaryErrorSource =
        maximumRelevantBoundaryErrorSource(
            topologyTrace, sourceBounds, recording.viewport);
    const double maximumBoundaryErrorMm =
        maximumRecordedBoundaryErrorSource * result->scale_factor
        + result->max_quantization_error_mm;
    if(!std::isfinite(maximumBoundaryErrorMm)
            || maximumBoundaryErrorMm > toleranceMm * 0.6) {
        result->status = "unsupported";
        result->reason_code = "unsupported_input_precision";
        return result;
    }
    const auto rawNormalizationStarted = std::chrono::steady_clock::now();
    result->topology_seconds = std::chrono::duration<double>(
        rawNormalizationStarted - topologyStarted).count();
    if(!hasNonEmptyPaint(paints)) {
        result->reason_code = "empty_geometry";
        return result;
    }

    for(auto& paint : paints) {
        if(paint.paths.empty())
            continue;
        auto* canonicalComponents = alphaCompositingRequired
            ? &paint.components : nullptr;
        if(!appendGeometry(
                result->raw, paint, complexityBudget,
                canonicalComponents)) {
            appendUnprintableFragment(
                result->unprintable_fragments,
                UnprintableReason::AreaCollapse, paint);
            paint.paths.clear();
            paint.components.clear();
            paint.bounds = {};
        }
    }
    const auto compositeStarted = std::chrono::steady_clock::now();
    result->normalization_raw_seconds = std::chrono::duration<double>(
        compositeStarted - rawNormalizationStarted).count();
    if(!hasNonEmptyPaint(paints)) {
        if(!resultCensusIsValid(*result))
            throw std::runtime_error("native_result_census_failed");
        result->status = "supported";
        result->reason_code.clear();
        return result;
    }
    std::vector<PaintGeometry> visiblePaints;
    Paths64 silhouettePaths;
    if(alphaCompositingRequired) {
        auto alphaComposite = compositeAlphaProgram(
            paints, programNodes, domain);
        visiblePaints = std::move(alphaComposite.visible);
        silhouettePaths = std::move(alphaComposite.silhouette);
    } else {
        auto opaqueComposite = compositePaints(paints, domain);
        visiblePaints.reserve(paints.size());
        for(size_t index = 0; index < paints.size(); ++index) {
            if(opaqueComposite.visible[index].empty())
                continue;
            auto visible = paints[index];
            visible.paths = std::move(opaqueComposite.visible[index]);
            visible.bounds = pathsBounds(visible.paths);
            visiblePaints.emplace_back(std::move(visible));
        }
        silhouettePaths = std::move(opaqueComposite.silhouette);
    }
    const auto exportStarted = std::chrono::steady_clock::now();
    result->composite_seconds = std::chrono::duration<double>(
        exportStarted - compositeStarted).count();
    result->normalization_visible_seconds = 0.0;

    GeometryCollection visibleCollection;
    for(auto& visible : visiblePaints) {
        if(!visible.paths.empty()
                && !appendGeometry(
                    visibleCollection, visible, complexityBudget)) {
            appendUnprintableFragment(
                result->unprintable_fragments,
                UnprintableReason::AreaCollapse, visible);
        }
    }
    result->visible = std::move(visibleCollection);

    PaintGeometry silhouette;
    silhouette.paths = std::move(silhouettePaths);
    silhouette.bounds = pathsBounds(silhouette.paths);
    silhouette.rgba = {{0, 0, 0, 255}};
    silhouette.rgba_f64 = {{0.0, 0.0, 0.0, 1.0}};
    silhouette.draw_index = 0;
    silhouette.source_index = -1;
    silhouette.source_kind = SourceKind::Silhouette;
    if(!silhouette.paths.empty()
            && !appendGeometry(
                result->silhouette, silhouette, complexityBudget))
        throw std::runtime_error("silhouette_hierarchy_collapse");

    if(!resultCensusIsValid(*result))
        throw std::runtime_error("native_result_census_failed");

    result->export_seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - exportStarted).count();

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
    uint64_t inputPaintCount = 0;
    double completedRecorderSeconds = 0.0;
    auto countPaintCommands = [](const RecorderResult& recording) {
        return static_cast<uint64_t>(std::count_if(
            recording.commands.begin(), recording.commands.end(),
            [](const lunasvg::PaintCommand& command) {
                return command.kind == lunasvg::PaintCommandKind::Fill
                    || command.kind == lunasvg::PaintCommandKind::Stroke;
            }));
    };
    if(!isPositiveFinite(targetWidthMm) || !isPositiveFinite(toleranceMm)) {
        auto result = std::make_shared<NativeResult>();
        result->reason_code = "invalid_physical_parameters";
        return result;
    }
    try {
        const auto recorderStarted = std::chrono::steady_clock::now();
        auto recording = loader();
        const auto recorderFinished = std::chrono::steady_clock::now();
        completedRecorderSeconds = std::chrono::duration<double>(
            recorderFinished - recorderStarted).count();
        inputPaintCount = countPaintCommands(recording);
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
                                    return value == 0.0f;
                                });
                    })) {
            auto result = std::make_shared<NativeResult>();
            result->status = "unsupported";
            result->reason_code = "unsupported_zero_length_dash";
            result->input_paint_count = inputPaintCount;
            result->recorder_seconds = completedRecorderSeconds;
            return result;
        }
        if(!allowStrokes && recording.status == "supported") {
            recording.commands.erase(
                std::remove_if(
                    recording.commands.begin(), recording.commands.end(),
                    [](const lunasvg::PaintCommand& command) {
                        return command.kind
                            == lunasvg::PaintCommandKind::Stroke;
                    }),
                recording.commands.end());
            inputPaintCount = countPaintCommands(recording);
        }
        auto result = buildResult(
            std::move(recording), targetWidthMm, toleranceMm);
        const auto kernelFinished = std::chrono::steady_clock::now();
        result->recorder_seconds = std::chrono::duration<double>(
            recorderFinished - recorderStarted).count();
        result->kernel_seconds = std::chrono::duration<double>(
            kernelFinished - recorderFinished).count();
        return result;
    } catch(const InputPrecisionError&) {
        auto result = std::make_shared<NativeResult>();
        result->status = "unsupported";
        result->reason_code = "unsupported_input_precision";
        result->input_paint_count = inputPaintCount;
        result->recorder_seconds = completedRecorderSeconds;
        return result;
    } catch(const StrokeInputPrecisionError&) {
        auto result = std::make_shared<NativeResult>();
        result->status = "unsupported";
        result->reason_code = "unsupported_input_precision";
        result->input_paint_count = inputPaintCount;
        result->recorder_seconds = completedRecorderSeconds;
        return result;
    } catch(const ComplexityLimitError&) {
        auto result = std::make_shared<NativeResult>();
        result->status = "unsupported";
        result->reason_code = "unsupported_complexity";
        result->input_paint_count = inputPaintCount;
        result->recorder_seconds = completedRecorderSeconds;
        return result;
    } catch(const std::range_error&) {
        auto result = std::make_shared<NativeResult>();
        result->reason_code = "numeric_range_error";
        result->input_paint_count = inputPaintCount;
        result->recorder_seconds = completedRecorderSeconds;
        return result;
    } catch(const std::bad_alloc&) {
        auto result = std::make_shared<NativeResult>();
        result->reason_code = "allocation_failed";
        result->input_paint_count = inputPaintCount;
        result->recorder_seconds = completedRecorderSeconds;
        return result;
    } catch(const std::exception&) {
        auto result = std::make_shared<NativeResult>();
        result->reason_code = "native_geometry_error";
        result->input_paint_count = inputPaintCount;
        result->recorder_seconds = completedRecorderSeconds;
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
