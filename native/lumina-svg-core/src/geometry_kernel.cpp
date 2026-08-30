#include "lumina_svg_core/geometry_kernel.h"

#include "lumina_svg_core/paint_command.h"

#include <clipper2/clipper.h>

#include <algorithm>
#include <array>
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
};

struct PaintGeometry {
    Paths64 paths;
    std::array<uint8_t, 4> rgba{{0, 0, 0, 0}};
    int32_t draw_index{-1};
    int32_t source_index{-1};
    SourceKind source_kind{SourceKind::Fill};
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

double pointLineDistance(const PointD& point,
                         const PointD& lineStart,
                         const PointD& lineEnd)
{
    const double dx = lineEnd.x - lineStart.x;
    const double dy = lineEnd.y - lineStart.y;
    const double length = std::hypot(dx, dy);
    if(length <= std::numeric_limits<double>::epsilon())
        return std::hypot(point.x - lineStart.x, point.y - lineStart.y);
    return std::abs(dy * point.x - dx * point.y
                    + lineEnd.x * lineStart.y - lineEnd.y * lineStart.x)
        / length;
}

void flattenCubic(const PointD& start, const PointD& control1,
                  const PointD& control2, const PointD& end,
                  double tolerance, unsigned depth,
                  std::vector<PointD>& output)
{
    if(depth >= 32
            || (pointLineDistance(control1, start, end) <= tolerance
                && pointLineDistance(control2, start, end) <= tolerance)) {
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
    const auto sourceBounds = exactFillBounds(recording.commands);
    if(!sourceBounds.valid()) {
        result->reason_code = "empty_geometry";
        return result;
    }

    const double sourceWidth = sourceBounds.max_x - sourceBounds.min_x;
    const double sourceHeight = sourceBounds.max_y - sourceBounds.min_y;
    result->bbox = {{sourceBounds.min_x, sourceBounds.min_y,
                     sourceWidth, sourceHeight}};
    result->scale_factor = targetWidthMm / sourceWidth;
    result->max_flattening_error_mm = toleranceMm * 0.4;
    result->max_quantization_error_mm = toleranceMm * 0.2;
    const double gridStepMm = result->max_quantization_error_mm
        * std::sqrt(2.0);
    result->grid_to_source_unit = gridStepMm / result->scale_factor;
    const PhysicalDomain domain{
        sourceBounds.min_x,
        sourceBounds.min_y,
        result->scale_factor,
        gridStepMm,
        result->max_flattening_error_mm,
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
        if(command.kind != lunasvg::PaintCommandKind::Fill)
            continue;

        PaintGeometry paint;
        paint.paths = applyActiveClips(normalizeFill(command, domain), activeClips);
        paint.rgba = command.rgba;
        paint.draw_index = drawIndex++;
        paint.source_index = command.source_index;
        paint.source_kind = SourceKind::Fill;
        paints.emplace_back(std::move(paint));
    }
    if(!activeClips.empty()) {
        result->reason_code = "invalid_clip_stack";
        return result;
    }

    for(const auto& paint : paints)
        appendGeometry(result->raw, paint);

    std::vector<Paths64> visiblePaths(paints.size());
    Paths64 laterPaint;
    for(size_t reverseIndex = paints.size(); reverseIndex > 0; --reverseIndex) {
        const size_t index = reverseIndex - 1;
        visiblePaths[index] = laterPaint.empty()
            ? paints[index].paths
            : Clipper2Lib::Difference(paints[index].paths, laterPaint,
                                      FillRule::NonZero);
        if(laterPaint.empty())
            laterPaint = paints[index].paths;
        else {
            auto combined = laterPaint;
            combined.insert(combined.end(), paints[index].paths.begin(),
                            paints[index].paths.end());
            laterPaint = Clipper2Lib::Union(combined, FillRule::NonZero);
        }
    }

    for(size_t index = 0; index < paints.size(); ++index) {
        auto visible = paints[index];
        visible.paths = std::move(visiblePaths[index]);
        appendGeometry(result->visible, visible);
    }

    PaintGeometry silhouette;
    silhouette.paths = std::move(laterPaint);
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
        return buildResult(loader(), targetWidthMm, toleranceMm);
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
