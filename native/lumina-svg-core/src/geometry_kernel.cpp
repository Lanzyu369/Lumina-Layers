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
#include <stdexcept>
#include <string>
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

struct PhysicalDomain {
    double bbox_x{0};
    double bbox_y{0};
    double source_to_mm{0};
    double grid_step_mm{0};
    double flatten_budget_mm{0};
    double stroke_quantization_budget_mm{0};
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

    std::vector<size_t> laterOverlaps(size_t paintIndex) const
    {
        std::vector<size_t> matches;
        if(m_nodes.empty() || !m_paints[paintIndex].bounds.valid)
            return matches;
        queryNode(0, paintIndex, m_paints[paintIndex].bounds, matches);
        std::sort(matches.begin(), matches.end());
        return matches;
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
                   std::vector<size_t>& matches) const
    {
        const auto& node = m_nodes[nodeIndex];
        if(!node.bounds.intersects(query))
            return;
        if(node.leaf) {
            for(size_t offset = node.begin; offset < node.end; ++offset) {
                const size_t candidate = m_indices[offset];
                if(candidate > paintIndex
                        && m_paints[candidate].bounds.intersects(query))
                    matches.push_back(candidate);
            }
            return;
        }
        queryNode(node.left, paintIndex, query, matches);
        queryNode(node.right, paintIndex, query, matches);
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

SourceBounds exactFillBounds(const std::vector<lunasvg::PaintCommand>& commands)
{
    SourceBounds bounds;
    for(const auto& command : commands) {
        if(command.kind != lunasvg::PaintCommandKind::Fill)
            continue;
        size_t pointIndex = 0;
        PointD current;
        for(const auto verb : command.path_verbs) {
            switch(verb) {
            case lunasvg::PaintPathVerb::MoveTo:
            case lunasvg::PaintPathVerb::LineTo: {
                const auto& point = command.path_points.at(pointIndex++);
                current = {point.x, point.y};
                bounds.include(transformPoint(command.transform, current));
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
                includeCubicExtrema(transformedStart, transformedFirst,
                                    transformedSecond, transformedLast, bounds);
                current = {last.x, last.y};
                break;
            }
            case lunasvg::PaintPathVerb::Close:
                break;
            }
        }
    }
    return bounds;
}

SourceBounds exactPaintBounds(const std::vector<lunasvg::PaintCommand>& commands)
{
    auto bounds = exactFillBounds(commands);
    for(const auto& command : commands) {
        if(command.kind != lunasvg::PaintCommandKind::Stroke)
            continue;
        const double singularValue = maximumSingularValue(command.transform);
        if(!isPositiveFinite(singularValue))
            continue;
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

double pointSegmentDistance(const PointD& point,
                            const PointD& segmentStart,
                            const PointD& segmentEnd)
{
    const double dx = segmentEnd.x - segmentStart.x;
    const double dy = segmentEnd.y - segmentStart.y;
    const double lengthSquared = dx * dx + dy * dy;
    if(lengthSquared <= std::numeric_limits<double>::epsilon())
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

void flattenCubic(const PointD& start, const PointD& control1,
                  const PointD& control2, const PointD& end,
                  double tolerance, unsigned depth,
                  std::vector<PointD>& output)
{
    if(depth >= 32
            || (pointSegmentDistance(control1, start, end) <= tolerance
                && pointSegmentDistance(control2, start, end) <= tolerance)) {
        output.push_back(end);
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
    flattenCubic(start, p01, p012, midpoint, tolerance, depth + 1, output);
    flattenCubic(midpoint, p123, p23, end, tolerance, depth + 1, output);
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

void finishSubpath(std::vector<PointD>& points,
                   const lunasvg::PaintCommand& command,
                   const PhysicalDomain& domain,
                   Paths64& paths)
{
    if(points.size() < 3) {
        points.clear();
        return;
    }
    Path64 path;
    path.reserve(points.size());
    for(const auto& point : points) {
        const auto gridPoint = toGridPoint(point, command.transform, domain);
        if(path.empty() || path.back() != gridPoint)
            path.push_back(gridPoint);
    }
    if(path.size() > 1 && path.front() == path.back())
        path.pop_back();
    if(path.size() >= 3)
        paths.emplace_back(std::move(path));
    points.clear();
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
    PointD current;
    size_t pointIndex = 0;
    for(const auto verb : command.path_verbs) {
        switch(verb) {
        case lunasvg::PaintPathVerb::MoveTo: {
            finishSubpath(subpath, command, domain, paths);
            const auto& point = command.path_points.at(pointIndex++);
            current = {point.x, point.y};
            subpath.push_back(current);
            break;
        }
        case lunasvg::PaintPathVerb::LineTo: {
            const auto& point = command.path_points.at(pointIndex++);
            current = {point.x, point.y};
            subpath.push_back(current);
            break;
        }
        case lunasvg::PaintPathVerb::CubicTo: {
            const auto& first = command.path_points.at(pointIndex++);
            const auto& second = command.path_points.at(pointIndex++);
            const auto& last = command.path_points.at(pointIndex++);
            const PointD control1{first.x, first.y};
            const PointD control2{second.x, second.y};
            const PointD end{last.x, last.y};
            flattenCubic(current, control1, control2, end,
                         localTolerance, 0, subpath);
            current = end;
            break;
        }
        case lunasvg::PaintPathVerb::Close:
            finishSubpath(subpath, command, domain, paths);
            break;
        }
    }
    finishSubpath(subpath, command, domain, paths);
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
    for(const auto& ring : expandStrokeLocal(
            command, localFlattenTolerance, localGridStep)) {
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

std::shared_ptr<NativeResult> buildResult(RecorderResult recording,
                                          double targetWidthMm,
                                          double toleranceMm)
{
    auto result = std::make_shared<NativeResult>();
    if(!isPositiveFinite(targetWidthMm) || !isPositiveFinite(toleranceMm)) {
        result->reason_code = "invalid_physical_parameters";
        return result;
    }
    if(recording.status != "supported") {
        result->status = recording.status;
        result->reason_code = recording.reason_code;
        return result;
    }
    auto sourceBounds = exactPaintBounds(recording.commands);
    if(!sourceBounds.valid()) {
        result->reason_code = "empty_geometry";
        return result;
    }
    if(isPositiveFinite(recording.viewport.w)
            && isPositiveFinite(recording.viewport.h)) {
        sourceBounds.include(
            {recording.viewport.x, recording.viewport.y});
        sourceBounds.include(
            {recording.viewport.x + recording.viewport.w,
             recording.viewport.y + recording.viewport.h});
    }

    const double sourceWidth = sourceBounds.max_x - sourceBounds.min_x;
    const double sourceHeight = sourceBounds.max_y - sourceBounds.min_y;
    result->bbox = {{sourceBounds.min_x, sourceBounds.min_y,
                     sourceWidth, sourceHeight}};
    result->scale_factor = targetWidthMm / sourceWidth;
    result->max_flattening_error_mm = toleranceMm * 0.4;
    result->max_quantization_error_mm = toleranceMm * 0.2;
    const double finalQuantizationBudgetMm = toleranceMm * 0.15;
    const double strokeQuantizationBudgetMm = toleranceMm * 0.05;
    const double gridStepMm = finalQuantizationBudgetMm
        * std::sqrt(2.0);
    result->grid_to_source_unit = gridStepMm / result->scale_factor;
    const PhysicalDomain domain{
        sourceBounds.min_x,
        sourceBounds.min_y,
        result->scale_factor,
        gridStepMm,
        result->max_flattening_error_mm,
        strokeQuantizationBudgetMm,
    };

    std::vector<Paths64> activeClips;
    std::vector<PaintGeometry> paints;
    paints.reserve(recording.commands.size());
    int32_t drawIndex = 0;
    for(const auto& command : recording.commands) {
        if(command.kind == lunasvg::PaintCommandKind::ClipBegin) {
            activeClips.push_back(normalizeFill(command, domain));
            continue;
        }
        if(command.kind == lunasvg::PaintCommandKind::ClipEnd) {
            if(activeClips.empty()) {
                result->reason_code = "invalid_clip_stack";
                return result;
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
        paints.emplace_back(std::move(paint));
    }
    if(!activeClips.empty()) {
        result->reason_code = "invalid_clip_stack";
        return result;
    }

    for(const auto& paint : paints)
        appendGeometry(result->raw, paint);

    const PackedBoundsIndex boundsIndex(paints);
    std::vector<Paths64> visiblePaths(paints.size());
    for(size_t reverseIndex = paints.size(); reverseIndex > 0; --reverseIndex) {
        const size_t index = reverseIndex - 1;
        const auto overlaps = boundsIndex.laterOverlaps(index);
        if(overlaps.empty()) {
            visiblePaths[index] = paints[index].paths;
            continue;
        }
        Paths64 laterOverlaps;
        for(const size_t overlapIndex : overlaps) {
            const auto& paths = paints[overlapIndex].paths;
            laterOverlaps.insert(laterOverlaps.end(), paths.begin(), paths.end());
        }
        laterOverlaps = Clipper2Lib::Union(laterOverlaps, FillRule::NonZero);
        visiblePaths[index] = Clipper2Lib::Difference(
            paints[index].paths, laterOverlaps, FillRule::NonZero);
    }

    for(size_t index = 0; index < paints.size(); ++index) {
        auto visible = paints[index];
        visible.paths = std::move(visiblePaths[index]);
        appendGeometry(result->visible, visible);
    }

    Paths64 allPaints;
    for(const auto& paint : paints) {
        allPaints.insert(allPaints.end(), paint.paths.begin(), paint.paths.end());
    }

    PaintGeometry silhouette;
    silhouette.paths = Clipper2Lib::Union(allPaints, FillRule::NonZero);
    silhouette.bounds = pathsBounds(silhouette.paths);
    silhouette.rgba = {{0, 0, 0, 255}};
    silhouette.draw_index = 0;
    silhouette.source_index = -1;
    silhouette.source_kind = SourceKind::Silhouette;
    appendGeometry(result->silhouette, silhouette);

    result->status = "supported";
    result->reason_code.clear();
    return result;
}

template<typename Loader>
std::shared_ptr<NativeResult> analyzeWith(Loader&& loader,
                                          double targetWidthMm,
                                          double toleranceMm)
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
        auto result = buildResult(
            std::move(recording), targetWidthMm, toleranceMm);
        const auto kernelFinished = std::chrono::steady_clock::now();
        result->recorder_seconds = std::chrono::duration<double>(
            recorderFinished - recorderStarted).count();
        result->kernel_seconds = std::chrono::duration<double>(
            kernelFinished - recorderFinished).count();
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
                                         double toleranceMm)
{
    return analyzeWith(
        [&filename]() { return recordPaintCommands(filename); },
        targetWidthMm, toleranceMm);
}

std::shared_ptr<NativeResult> analyzeSvgData(const std::string& svg,
                                             double targetWidthMm,
                                             double toleranceMm)
{
    return analyzeWith(
        [&svg]() { return recordPaintCommandsSvg(svg); },
        targetWidthMm, toleranceMm);
}

} // namespace lumina_svg_core
