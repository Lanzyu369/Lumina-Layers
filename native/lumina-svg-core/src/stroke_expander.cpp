#include "lumina_svg_core/stroke_expander.h"

#include "complexity_budget.h"
#include "clipper_safety.h"

#include <clipper2/clipper.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <numeric>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

namespace lumina_svg_core {
namespace {

struct LocalSubpath {
    LocalPath points;
    bool closed{false};
    bool has_draw_segment{false};
    int32_t source_subpath_index{-1};
};

double pointSegmentDistance(const LocalPoint& point,
                            const LocalPoint& segmentStart,
                            const LocalPoint& segmentEnd)
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

void flattenCubic(const LocalPoint& start, const LocalPoint& control1,
                  const LocalPoint& control2, const LocalPoint& end,
                  double tolerance, double arcLengthErrorBudget,
                  unsigned depth, LocalPath& output,
                  ComplexityBudget& complexityBudget)
{
    const double chordLength = std::hypot(
        end.x - start.x, end.y - start.y);
    const double controlPolygonLength =
        std::hypot(control1.x - start.x, control1.y - start.y)
        + std::hypot(
            control2.x - control1.x, control2.y - control1.y)
        + std::hypot(end.x - control2.x, end.y - control2.y);
    const double arcLengthUncertainty = std::max(
        0.0, controlPolygonLength - chordLength);
    if(!std::isfinite(arcLengthUncertainty))
        throw StrokeInputPrecisionError("nonfinite_cubic_arc_length");
    const bool withinGeometricTolerance =
        pointSegmentDistance(control1, start, end) <= tolerance
        && pointSegmentDistance(control2, start, end) <= tolerance;
    if(withinGeometricTolerance
            && arcLengthUncertainty <= arcLengthErrorBudget) {
        complexityBudget.consumeGeneratedPoints();
        output.push_back(end);
        return;
    }
    if(depth >= 32 || !(arcLengthErrorBudget > 0.0))
        throw StrokeInputPrecisionError("cubic_flattening_depth");
    const LocalPoint p01{(start.x + control1.x) * 0.5,
                         (start.y + control1.y) * 0.5};
    const LocalPoint p12{(control1.x + control2.x) * 0.5,
                         (control1.y + control2.y) * 0.5};
    const LocalPoint p23{(control2.x + end.x) * 0.5,
                         (control2.y + end.y) * 0.5};
    const LocalPoint p012{(p01.x + p12.x) * 0.5,
                          (p01.y + p12.y) * 0.5};
    const LocalPoint p123{(p12.x + p23.x) * 0.5,
                          (p12.y + p23.y) * 0.5};
    const LocalPoint midpoint{(p012.x + p123.x) * 0.5,
                              (p012.y + p123.y) * 0.5};
    flattenCubic(
        start, p01, p012, midpoint, tolerance,
        arcLengthErrorBudget * 0.5, depth + 1,
        output, complexityBudget);
    flattenCubic(
        midpoint, p123, p23, end, tolerance,
        arcLengthErrorBudget * 0.5, depth + 1,
        output, complexityBudget);
}

std::vector<LocalSubpath> flattenPath(const lunasvg::PaintCommand& command,
                                      double tolerance,
                                      double cubicArcLengthErrorBudget,
                                      ComplexityBudget& complexityBudget)
{
    std::vector<LocalSubpath> output;
    LocalSubpath currentSubpath;
    LocalPoint currentPoint;
    LocalPoint subpathStart;
    bool hasCurrentPoint = false;
    size_t pointIndex = 0;
    int32_t nextSubpathIndex = 0;
    auto finish = [&]() {
        currentSubpath.points.erase(
            std::unique(
                currentSubpath.points.begin(), currentSubpath.points.end(),
                [](const LocalPoint& left, const LocalPoint& right) {
                    return left.x == right.x && left.y == right.y;
                }),
            currentSubpath.points.end());
        if(currentSubpath.has_draw_segment
                && !currentSubpath.points.empty())
            output.emplace_back(std::move(currentSubpath));
        currentSubpath = {};
    };

    for(const auto verb : command.path_verbs) {
        switch(verb) {
        case lunasvg::PaintPathVerb::MoveTo: {
            finish();
            currentSubpath.source_subpath_index = nextSubpathIndex++;
            const auto& point = command.path_points.at(pointIndex++);
            currentPoint = {point.x, point.y};
            subpathStart = currentPoint;
            hasCurrentPoint = true;
            complexityBudget.consumeGeneratedPoints();
            currentSubpath.points.push_back(currentPoint);
            break;
        }
        case lunasvg::PaintPathVerb::LineTo: {
            currentSubpath.has_draw_segment = true;
            const auto& point = command.path_points.at(pointIndex++);
            if(currentSubpath.points.empty() && hasCurrentPoint) {
                complexityBudget.consumeGeneratedPoints();
                currentSubpath.points.push_back(currentPoint);
            }
            currentPoint = {point.x, point.y};
            complexityBudget.consumeGeneratedPoints();
            currentSubpath.points.push_back(currentPoint);
            break;
        }
        case lunasvg::PaintPathVerb::CubicTo: {
            currentSubpath.has_draw_segment = true;
            const auto& first = command.path_points.at(pointIndex++);
            const auto& second = command.path_points.at(pointIndex++);
            const auto& last = command.path_points.at(pointIndex++);
            const LocalPoint control1{first.x, first.y};
            const LocalPoint control2{second.x, second.y};
            const LocalPoint end{last.x, last.y};
            if(currentSubpath.points.empty() && hasCurrentPoint) {
                complexityBudget.consumeGeneratedPoints();
                currentSubpath.points.push_back(currentPoint);
            }
            flattenCubic(currentPoint, control1, control2, end,
                         tolerance, cubicArcLengthErrorBudget, 0,
                         currentSubpath.points,
                         complexityBudget);
            currentPoint = end;
            break;
        }
        case lunasvg::PaintPathVerb::Close:
            currentSubpath.has_draw_segment = true;
            currentSubpath.closed = true;
            finish();
            if(hasCurrentPoint)
                currentPoint = subpathStart;
            break;
        }
    }
    finish();
    return output;
}

std::vector<double> normalizedDashArray(const std::vector<double>& source)
{
    std::vector<double> dashArray;
    dashArray.reserve(checkedSizeProduct(source.size(), size_t{2}));
    for(const auto value : source)
        dashArray.push_back(std::abs(static_cast<double>(value)));
    if(dashArray.size() % 2 == 1) {
        const auto copy = dashArray;
        dashArray.insert(dashArray.end(), copy.begin(), copy.end());
    }
    const double total = std::accumulate(dashArray.begin(), dashArray.end(), 0.0);
    if(total <= 0.0)
        dashArray.clear();
    return dashArray;
}

double commandPathLengthUpperBound(const lunasvg::PaintCommand& command)
{
    double length = 0;
    LocalPoint current;
    LocalPoint subpathStart;
    bool hasCurrentPoint = false;
    size_t pointIndex = 0;
    auto add = [&](const LocalPoint& end) {
        length += std::hypot(end.x - current.x, end.y - current.y);
        current = end;
    };
    for(const auto verb : command.path_verbs) {
        switch(verb) {
        case lunasvg::PaintPathVerb::MoveTo: {
            const auto& point = command.path_points.at(pointIndex++);
            current = {point.x, point.y};
            subpathStart = current;
            hasCurrentPoint = true;
            break;
        }
        case lunasvg::PaintPathVerb::LineTo: {
            const auto& point = command.path_points.at(pointIndex++);
            add({point.x, point.y});
            break;
        }
        case lunasvg::PaintPathVerb::CubicTo: {
            const auto& first = command.path_points.at(pointIndex++);
            const auto& second = command.path_points.at(pointIndex++);
            const auto& end = command.path_points.at(pointIndex++);
            add({first.x, first.y});
            add({second.x, second.y});
            add({end.x, end.y});
            break;
        }
        case lunasvg::PaintPathVerb::Close:
            if(hasCurrentPoint)
                add(subpathStart);
            break;
        }
        if(!std::isfinite(length))
            throw StrokeInputPrecisionError("nonfinite_path_length");
    }
    return length;
}

void validateDashExpansion(
    const lunasvg::PaintCommand& command,
    const std::vector<double>& dashArray)
{
    if(dashArray.empty())
        return;
    double minimumPositive = std::numeric_limits<double>::infinity();
    for(const double value : dashArray) {
        if(value > 0)
            minimumPositive = std::min(minimumPositive, value);
    }
    if(!std::isfinite(minimumPositive))
        return;
    const double stepUpperBound = std::ceil(
        commandPathLengthUpperBound(command) / minimumPositive)
        + static_cast<double>(command.path_verbs.size()) + 2.0;
    if(!std::isfinite(stepUpperBound))
        throw ComplexityLimitError();
}

std::vector<LocalSubpath> dashSubpath(const LocalSubpath& subpath,
                                      const std::vector<double>& dashArray,
                                      double dashOffset,
                                      ComplexityBudget& complexityBudget)
{
    if(dashArray.empty()) {
        complexityBudget.consumeGeneratedPoints(subpath.points.size());
        complexityBudget.consumeGeneratedRings();
        return {subpath};
    }

    const double total = std::accumulate(dashArray.begin(), dashArray.end(), 0.0);
    double phase = std::fmod(dashOffset, total);
    if(phase < 0)
        phase += total;
    size_t dashIndex = 0;
    while(phase > dashArray[dashIndex]
            && dashArray[dashIndex] > 0) {
        phase -= dashArray[dashIndex];
        dashIndex = (dashIndex + 1) % dashArray.size();
    }
    double dashRemaining = dashArray[dashIndex] - phase;

    // A zero-length drawing subpath still has stroke-cap semantics. Its
    // visibility is determined by the dash phase at arclength zero; a pure
    // MoveTo never reaches this function because flattenPath drops it.
    if(subpath.points.size() == 1) {
        // At an exact interval boundary, SVG's terminating-dash algorithm
        // retains the adjacent zero-length painted interval. Thus either
        // side of the boundary can contribute a cap.
        if(dashIndex % 2 != 0 && dashRemaining != 0.0)
            return {};
        complexityBudget.consumeGeneratedPoints();
        complexityBudget.consumeGeneratedRings();
        return {subpath};
    }

    std::vector<LocalSubpath> output;
    LocalSubpath active;
    active.source_subpath_index = subpath.source_subpath_index;
    auto advanceDash = [&]() {
        size_t guard = 0;
        do {
            dashIndex = (dashIndex + 1) % dashArray.size();
            dashRemaining = dashArray[dashIndex];
            ++guard;
        } while(dashRemaining <= 0.0
                && guard <= dashArray.size());
    };
    auto finishActive = [&]() {
        if(active.points.size() >= 2) {
            complexityBudget.consumeGeneratedRings();
            output.emplace_back(std::move(active));
        }
        active = {};
        active.source_subpath_index = subpath.source_subpath_index;
    };

    // An offset exactly at the end of a painted dash contributes a
    // zero-length painted interval at the path start. Preserve it as a point
    // subpath so round/square caps survive before advancing into the gap.
    if(dashRemaining == 0.0) {
        if(dashIndex % 2 == 0) {
            complexityBudget.consumeGeneratedPoints();
            complexityBudget.consumeGeneratedRings();
            LocalSubpath pointSubpath;
            pointSubpath.source_subpath_index = subpath.source_subpath_index;
            pointSubpath.points.push_back(subpath.points.front());
            pointSubpath.has_draw_segment = true;
            output.emplace_back(std::move(pointSubpath));
        }
        advanceDash();
    }

    const size_t segmentCount = subpath.closed
        ? subpath.points.size() : subpath.points.size() - 1;
    for(size_t segmentIndex = 0; segmentIndex < segmentCount; ++segmentIndex) {
        LocalPoint cursor = subpath.points[segmentIndex];
        const LocalPoint end = subpath.points[
            (segmentIndex + 1) % subpath.points.size()];
        const double dx = end.x - cursor.x;
        const double dy = end.y - cursor.y;
        double segmentRemaining = std::hypot(dx, dy);
        if(segmentRemaining <= 0.0)
            continue;
        const double ux = dx / segmentRemaining;
        const double uy = dy / segmentRemaining;
        while(segmentRemaining > 0.0) {
            if(dashRemaining <= 0.0)
                advanceDash();
            const bool isPainted = dashIndex % 2 == 0;
            const double step = std::min(segmentRemaining, dashRemaining);
            bool consumesSegment = step == segmentRemaining;
            LocalPoint next = consumesSegment
                ? end
                : LocalPoint{cursor.x + ux * step, cursor.y + uy * step};
            // Repeated decimal dash lengths can leave a one-ULP scalar
            // remainder after the computed coordinate has already reached the
            // exact segment endpoint. Finish the segment at that endpoint
            // instead of attempting a zero-progress iteration.
            if(!consumesSegment
                    && next.x == end.x && next.y == end.y)
                consumesSegment = true;
            const double nextSegmentRemaining = consumesSegment
                ? 0.0 : segmentRemaining - step;
            const double nextDashRemaining = dashRemaining - step;
            if(!(step > 0.0))
                throw StrokeInputPrecisionError("dash_nonpositive_step");
            if(next.x == cursor.x && next.y == cursor.y)
                throw StrokeInputPrecisionError("dash_coordinate_progress");
            if(nextSegmentRemaining == segmentRemaining
                    && step < segmentRemaining)
                throw StrokeInputPrecisionError("dash_segment_progress");
            if(nextDashRemaining == dashRemaining
                    && step < dashRemaining)
                throw StrokeInputPrecisionError("dash_pattern_progress");
            if(isPainted) {
                if(active.points.empty())
                    complexityBudget.consumeGeneratedPoints();
                if(active.points.empty())
                    active.points.push_back(cursor);
                complexityBudget.consumeGeneratedPoints();
                active.points.push_back(next);
            }
            cursor = next;
            segmentRemaining = nextSegmentRemaining;
            dashRemaining = nextDashRemaining;
            if(dashRemaining <= 0.0) {
                if(isPainted)
                    finishActive();
                advanceDash();
            }
        }
    }
    finishActive();
    if(subpath.closed && output.size() == 1
            && output.front().points.size() >= 3
            && output.front().points.front().x
                == output.front().points.back().x
            && output.front().points.front().y
                == output.front().points.back().y) {
        output.front().points.pop_back();
        output.front().closed = true;
    }
    if(subpath.closed && output.size() >= 2
            && output.front().points.size() >= 2
            && output.back().points.size() >= 2
            && output.front().points.front().x
                == subpath.points.front().x
            && output.front().points.front().y
                == subpath.points.front().y
            && output.back().points.back().x
                == subpath.points.front().x
            && output.back().points.back().y
                == subpath.points.front().y) {
        LocalSubpath wrapped = std::move(output.back());
        output.pop_back();
        auto& head = output.front();
        wrapped.points.insert(
            wrapped.points.end(),
            head.points.begin() + 1, head.points.end());
        wrapped.has_draw_segment = true;
        head = std::move(wrapped);
    }
    return output;
}

void simplifyOpenSubpath(LocalSubpath& subpath, double tolerance,
                         ComplexityBudget& complexityBudget)
{
    if(subpath.points.size() <= 2 || !(tolerance > 0.0))
        return;
    std::vector<bool> keep(subpath.points.size(), false);
    keep.front() = true;
    keep.back() = true;
    std::vector<std::pair<size_t, size_t>> ranges{
        {0, subpath.points.size() - 1}};
    while(!ranges.empty()) {
        const auto [begin, end] = ranges.back();
        ranges.pop_back();
        size_t splitIndex = begin;
        double maximumDistance = 0.0;
        complexityBudget.consumeStrokeSimplificationComparisons(
            end - begin - 1);
        for(size_t index = begin + 1; index < end; ++index) {
            const double distance = pointSegmentDistance(
                subpath.points[index], subpath.points[begin],
                subpath.points[end]);
            if(distance > maximumDistance) {
                maximumDistance = distance;
                splitIndex = index;
            }
        }
        if(maximumDistance <= tolerance)
            continue;
        keep[splitIndex] = true;
        ranges.emplace_back(begin, splitIndex);
        ranges.emplace_back(splitIndex, end);
    }
    LocalPath simplified;
    simplified.reserve(static_cast<size_t>(std::count(
        keep.begin(), keep.end(), true)));
    for(size_t index = 0; index < subpath.points.size(); ++index) {
        if(keep[index])
            simplified.push_back(subpath.points[index]);
    }
    complexityBudget.consumeGeneratedPoints(simplified.size());
    subpath.points = std::move(simplified);
}

size_t offsetArcStepUpperBound(double delta, double arcTolerance)
{
    constexpr double PI = 3.141592653589793238462643383279502884;
    constexpr double DEFAULT_ARC_RATIO = 0.002;
    const double absoluteDelta = std::abs(delta);
    if(!(std::isfinite(absoluteDelta) && absoluteDelta > 0))
        throw ComplexityLimitError();
    const double effectiveTolerance = arcTolerance > 1.0e-12
        ? std::min(absoluteDelta, arcTolerance)
        : absoluteDelta * DEFAULT_ARC_RATIO;
    const double angle = std::acos(std::clamp(
        1.0 - effectiveTolerance / absoluteDelta, -1.0, 1.0));
    const double steps = std::min(
        angle > 0 ? PI / angle
                  : std::numeric_limits<double>::infinity(),
        absoluteDelta * PI);
    if(!std::isfinite(steps)
            || steps > static_cast<double>(
                std::numeric_limits<size_t>::max()))
        throw ComplexityLimitError();
    return std::max<size_t>(1, static_cast<size_t>(std::ceil(steps)));
}

Clipper2Lib::JoinType joinType(lunasvg::PaintLineJoin join)
{
    switch(join) {
    case lunasvg::PaintLineJoin::Round: return Clipper2Lib::JoinType::Round;
    case lunasvg::PaintLineJoin::Bevel: return Clipper2Lib::JoinType::Bevel;
    case lunasvg::PaintLineJoin::Miter: return Clipper2Lib::JoinType::Miter;
    }
    return Clipper2Lib::JoinType::Miter;
}

Clipper2Lib::EndType endType(lunasvg::PaintLineCap cap, bool closed)
{
    if(closed)
        return Clipper2Lib::EndType::Joined;
    switch(cap) {
    case lunasvg::PaintLineCap::Round: return Clipper2Lib::EndType::Round;
    case lunasvg::PaintLineCap::Square: return Clipper2Lib::EndType::Square;
    case lunasvg::PaintLineCap::Butt: return Clipper2Lib::EndType::Butt;
    }
    return Clipper2Lib::EndType::Butt;
}

int64_t quantizeLocal(double value)
{
    constexpr double safeCoordinate = 1.0e15;
    if(!std::isfinite(value) || std::abs(value) > safeCoordinate)
        throw StrokeInputPrecisionError("local_coordinate_range");
    return static_cast<int64_t>(std::llround(value));
}

double storedUlp(double value)
{
    if(!std::isfinite(value))
        return std::numeric_limits<double>::infinity();
    const double upward = std::nextafter(
        value, std::numeric_limits<double>::infinity());
    const double downward = std::nextafter(
        value, -std::numeric_limits<double>::infinity());
    return std::max(
        std::abs(static_cast<double>(upward) - value),
        std::abs(static_cast<double>(value) - downward));
}

double miterThreshold(double miterLimit)
{
    return miterLimit <= 1.0
        ? 1.0 : 2.0 / (miterLimit * miterLimit) - 1.0;
}

struct LocalJoinGeometry {
    double cosine{1.0};
    double incoming_length{0.0};
    double outgoing_length{0.0};
};

std::optional<LocalJoinGeometry> localJoinGeometry(
    const LocalPath& points, size_t index, bool closed)
{
    if(points.size() < 3 || (!closed
            && (index == 0 || index + 1 == points.size())))
        return std::nullopt;
    const size_t previousIndex = index == 0
        ? points.size() - 1 : index - 1;
    const size_t nextIndex = (index + 1) % points.size();
    const double incomingX = points[index].x - points[previousIndex].x;
    const double incomingY = points[index].y - points[previousIndex].y;
    const double outgoingX = points[nextIndex].x - points[index].x;
    const double outgoingY = points[nextIndex].y - points[index].y;
    const double incomingLength = std::hypot(incomingX, incomingY);
    const double outgoingLength = std::hypot(outgoingX, outgoingY);
    if(!(std::isfinite(incomingLength) && incomingLength > 0)
            || !(std::isfinite(outgoingLength) && outgoingLength > 0))
        return std::nullopt;
    return LocalJoinGeometry{
        std::clamp(
            (incomingX * outgoingX + incomingY * outgoingY)
                / (incomingLength * outgoingLength),
            -1.0, 1.0),
        incomingLength,
        outgoingLength,
    };
}

bool hasStableMiterClassification(
    const LocalSubpath& subpath, double centerlineQuantizationError,
    const lunasvg::PaintStrokeStyle& stroke)
{
    constexpr double STROKE_OPERATION_ULPS = 4.0;
    if(stroke.line_join != lunasvg::PaintLineJoin::Miter
            || subpath.points.size() < 3)
        return true;

    const double limitError = storedUlp(stroke.miter_limit)
        * STROKE_OPERATION_ULPS;
    const double minimumLimit = std::max(
        1.0, static_cast<double>(stroke.miter_limit) - limitError);
    const double maximumLimit = static_cast<double>(stroke.miter_limit)
        + limitError;
    const double minimumThreshold = miterThreshold(maximumLimit);
    const double maximumThreshold = miterThreshold(minimumLimit);
    const size_t firstIndex = subpath.closed ? 0 : 1;
    const size_t endIndex = subpath.closed
        ? subpath.points.size() : subpath.points.size() - 1;
    for(size_t index = firstIndex; index < endIndex; ++index) {
        const auto geometry = localJoinGeometry(
            subpath.points, index, subpath.closed);
        if(!geometry)
            continue;
        const double incomingVectorError = 2.0
            * centerlineQuantizationError;
        const double outgoingVectorError = incomingVectorError;
        if(geometry->incoming_length <= incomingVectorError
                || geometry->outgoing_length <= outgoingVectorError)
            return false;
        const double incomingDirectionError = 2.0 * incomingVectorError
            / (geometry->incoming_length - incomingVectorError);
        const double outgoingDirectionError = 2.0 * outgoingVectorError
            / (geometry->outgoing_length - outgoingVectorError);
        const double cosineError = incomingDirectionError
            + outgoingDirectionError
            + incomingDirectionError * outgoingDirectionError;
        const double minimumCosine = std::max(
            -1.0, geometry->cosine - cosineError);
        const double maximumCosine = std::min(
            1.0, geometry->cosine + cosineError);
        const bool alwaysMiter = minimumCosine > maximumThreshold;
        const bool alwaysBevel = maximumCosine <= minimumThreshold;
        if(!alwaysMiter && !alwaysBevel)
            return false;
    }
    return true;
}

double strokeQuantizationAmplification(
    const LocalSubpath& subpath,
    const lunasvg::PaintStrokeStyle& stroke,
    double radius)
{
    constexpr double POSITION_SAFETY = 16.0;
    double amplification = 2.0;
    if(subpath.points.size() < 2)
        return amplification;
    const double limitError = storedUlp(stroke.miter_limit) * 4.0;
    const double maximumLimit = std::max(
        1.0, static_cast<double>(stroke.miter_limit) + limitError);
    const double threshold = miterThreshold(maximumLimit);
    const size_t firstIndex = subpath.closed ? 0 : 1;
    const size_t endIndex = subpath.closed
        ? subpath.points.size() : subpath.points.size() - 1;
    for(size_t index = firstIndex; index < endIndex; ++index) {
        const auto geometry = localJoinGeometry(
            subpath.points, index, subpath.closed);
        if(!geometry)
            continue;
        const double minimumLength = std::min(
            geometry->incoming_length, geometry->outgoing_length);
        double joinRatio = 1.0;
        if(stroke.line_join == lunasvg::PaintLineJoin::Miter
                && geometry->cosine > threshold) {
            const double denominator = 1.0 + geometry->cosine;
            if(!(denominator > 0.0))
                throw StrokeInputPrecisionError("miter_denominator");
            joinRatio = std::min(
                maximumLimit, std::sqrt(2.0 / denominator));
        }
        const double candidate = 2.0
            + POSITION_SAFETY * radius
                * joinRatio * joinRatio / minimumLength;
        if(!std::isfinite(candidate))
            throw StrokeInputPrecisionError("stroke_grid_amplification");
        amplification = std::max(amplification, candidate);
    }
    if(!subpath.closed
            && stroke.line_cap != lunasvg::PaintLineCap::Butt) {
        const double firstLength = std::hypot(
            subpath.points[1].x - subpath.points[0].x,
            subpath.points[1].y - subpath.points[0].y);
        const size_t last = subpath.points.size() - 1;
        const double lastLength = std::hypot(
            subpath.points[last].x - subpath.points[last - 1].x,
            subpath.points[last].y - subpath.points[last - 1].y);
        const double minimumLength = std::min(firstLength, lastLength);
        if(std::isfinite(minimumLength) && minimumLength > 0.0)
            amplification = std::max(
                amplification,
                2.0 + POSITION_SAFETY * radius / minimumLength);
    }
    return amplification;
}

double effectiveStrokeGridStep(
    const LocalSubpath& subpath,
    const lunasvg::PaintStrokeStyle& stroke,
    double radius, double maximumGridStep)
{
    const double amplification = strokeQuantizationAmplification(
        subpath, stroke, radius);
    double gridStep = maximumGridStep / amplification;
    for(size_t attempt = 0; attempt < 16; ++attempt) {
        if(std::isfinite(gridStep) && gridStep > 0.0
                && hasStableMiterClassification(
                    subpath, gridStep / std::sqrt(2.0), stroke))
            return gridStep;
        gridStep *= 0.25;
    }
    throw StrokeInputPrecisionError("miter_classification_grid");
}

LocalPath pointCap(const LocalPoint& point,
                   lunasvg::PaintLineCap cap,
                   double radius,
                   double flattenTolerance,
                   ComplexityBudget& complexityBudget,
                   bool enforcePhysicalTolerance)
{
    constexpr double PI = 3.141592653589793238462643383279502884;
    if(cap == lunasvg::PaintLineCap::Butt)
        return {};
    if(cap == lunasvg::PaintLineCap::Square) {
        complexityBudget.consumeGeneratedPoints(4);
        complexityBudget.consumeGeneratedRings();
        return {
            {point.x - radius, point.y - radius},
            {point.x + radius, point.y - radius},
            {point.x + radius, point.y + radius},
            {point.x - radius, point.y + radius},
        };
    }

    const double cosine = std::clamp(
        1.0 - flattenTolerance / radius, -1.0, 1.0);
    const double halfAngle = std::acos(cosine);
    const double requiredSegments = halfAngle > 0
        ? std::ceil(PI / halfAngle)
        : std::numeric_limits<double>::infinity();
    if(!std::isfinite(requiredSegments)
            || requiredSegments > static_cast<double>(
                std::numeric_limits<size_t>::max()))
        throw ComplexityLimitError("stroke_point_cap_segments");
    const size_t segmentCount = std::max<size_t>(
        8, static_cast<size_t>(std::ceil(requiredSegments)));
    complexityBudget.consumeGeneratedPoints(segmentCount);
    complexityBudget.consumeGeneratedRings();
    LocalPath ring;
    ring.reserve(segmentCount);
    for(size_t index = 0; index < segmentCount; ++index) {
        const double angle = 2.0 * PI
            * static_cast<double>(index)
            / static_cast<double>(segmentCount);
        ring.push_back({
            point.x + radius * std::cos(angle),
            point.y + radius * std::sin(angle),
        });
    }
    return ring;
}

} // namespace

StrokeExpansion expandStrokeLocal(const lunasvg::PaintCommand& command,
                                  double localFlattenTolerance,
                                  double localGridStep,
                                  ComplexityBudget& complexityBudget,
                                  bool enforcePhysicalTolerance)
{
    if(!(std::isfinite(command.stroke.width) && command.stroke.width > 0)
            || !(std::isfinite(localFlattenTolerance)
                 && localFlattenTolerance > 0)
            || !(std::isfinite(localGridStep) && localGridStep > 0))
        return {};

    const auto dashArray = normalizedDashArray(command.stroke.dash_array);
    validateDashExpansion(command, dashArray);
    const size_t cubicCount = static_cast<size_t>(std::count(
        command.path_verbs.begin(), command.path_verbs.end(),
        lunasvg::PaintPathVerb::CubicTo));
    const bool requiresDashArcLengthBudget =
        !dashArray.empty() && cubicCount > 0;
    const bool requiresOffsetArcBudget =
        command.stroke.line_cap == lunasvg::PaintLineCap::Round
        || command.stroke.line_join == lunasvg::PaintLineJoin::Round;
    const double centerlineBudget = localFlattenTolerance
        * (requiresOffsetArcBudget ? 0.5 : 1.0);
    const double flattenTolerance = requiresDashArcLengthBudget
        ? centerlineBudget * 0.1 : centerlineBudget;
    const double cubicArcLengthErrorBudget = requiresDashArcLengthBudget
        ? centerlineBudget * 0.5 / static_cast<double>(cubicCount)
        : std::numeric_limits<double>::infinity();
    const double dashedSimplificationTolerance = centerlineBudget * 0.4;
    std::vector<LocalSubpath> strokeSubpaths;
    for(const auto& subpath : flattenPath(
            command, flattenTolerance, cubicArcLengthErrorBudget,
            complexityBudget)) {
        auto dashed = dashSubpath(subpath, dashArray,
                                  command.stroke.dash_offset,
                                  complexityBudget);
        if(requiresDashArcLengthBudget) {
            for(auto& dashedSubpath : dashed) {
                simplifyOpenSubpath(
                    dashedSubpath, dashedSimplificationTolerance,
                    complexityBudget);
            }
        }
        strokeSubpaths.insert(strokeSubpaths.end(),
                              std::make_move_iterator(dashed.begin()),
                              std::make_move_iterator(dashed.end()));
    }

    StrokeExpansion output;
    const double offsetArcTolerance = requiresOffsetArcBudget
        ? localFlattenTolerance - centerlineBudget
        : localFlattenTolerance;
    for(const auto& subpath : strokeSubpaths) {
        if(subpath.points.size() == 1) {
            auto cap = pointCap(
                subpath.points.front(), command.stroke.line_cap,
                command.stroke.width * 0.5, offsetArcTolerance,
                complexityBudget, enforcePhysicalTolerance);
            if(!cap.empty())
                output.paths.push_back({
                    std::move(cap), subpath.source_subpath_index,
                });
            continue;
        }
        double effectiveGridStep = effectiveStrokeGridStep(
            subpath, command.stroke, command.stroke.width * 0.5,
            localGridStep);
        // This is an int64 numeric-range floor, not a print-resolution grid.
        // Exact short segments can require a very fine directional grid for
        // square or round caps, but Clipper's offset radius must still remain
        // representable. The 1e15 cell domain remains far below any physical
        // cleanup threshold and preserves the source segment itself.
        effectiveGridStep = std::max(
            effectiveGridStep,
            std::abs(static_cast<double>(command.stroke.width))
                * 0.5 / 1.0e15);
        // Keep both the discarded bounds pass and the final replay comfortably
        // inside Clipper's robust integer range. This floor is relative to the
        // path origin, so large source offsets do not erase short segments.
        // It is a numeric representation limit, not a printer-resolution grid.
        const auto& origin = subpath.points.front();
        double localMagnitude = std::abs(
            static_cast<double>(command.stroke.width)) * 0.5;
        for(const auto& point : subpath.points) {
            localMagnitude = std::max(
                localMagnitude, std::abs(point.x - origin.x));
            localMagnitude = std::max(
                localMagnitude, std::abs(point.y - origin.y));
        }
        effectiveGridStep = std::max(
            effectiveGridStep, localMagnitude / 5.0e14);
        const double delta = command.stroke.width * 0.5
            / effectiveGridStep;
        const double arcTolerance = offsetArcTolerance
            / effectiveGridStep;
        if(!(std::isfinite(delta) && delta > 0.0 && delta <= 1.0e15))
            throw StrokeInputPrecisionError("stroke_offset_range");
        const LocalPoint quantizationOrigin = subpath.points.front();
        Clipper2Lib::Path64 path;
        path.reserve(subpath.points.size());
        for(const auto& point : subpath.points) {
            const Clipper2Lib::Point64 quantized(
                quantizeLocal(
                    (point.x - quantizationOrigin.x) / effectiveGridStep),
                quantizeLocal(
                    (point.y - quantizationOrigin.y) / effectiveGridStep));
            if(path.empty() || path.back() != quantized)
                path.push_back(quantized);
        }
        if(path.size() < 2) {
            output.collapsed_subpath_indices.push_back(
                subpath.source_subpath_index);
            continue;
        }
        const size_t worstCaseVerticesPerPoint =
            command.stroke.line_join == lunasvg::PaintLineJoin::Round
                || (!subpath.closed
                    && command.stroke.line_cap
                        == lunasvg::PaintLineCap::Round)
            ? checkedSizeSum(
                offsetArcStepUpperBound(delta, arcTolerance), size_t{2})
            : 4;
        const size_t outputPointUpperBound = checkedSizeProduct(
            path.size(), worstCaseVerticesPerPoint);
        complexityBudget.ensureGeneratedPointCapacity(
            outputPointUpperBound);
        // The point estimate bounds the transient allocation. It does not
        // imply that every three possible points become a separate ring;
        // charge the actual InflatePaths rings below.
        Clipper2Lib::Paths64 offsetPaths;
        offsetPaths.emplace_back(std::move(path));
        Clipper2Lib::ClipperOffset offset(
            command.stroke.miter_limit, arcTolerance);
        validateClipperOffsetRange(
            delta, command.stroke.miter_limit);
        offset.AddPaths(
            offsetPaths, joinType(command.stroke.line_join),
            endType(command.stroke.line_cap, subpath.closed));
        Clipper2Lib::Paths64 expanded;
        offset.Execute(delta, expanded);
        size_t expandedPointCount = 0;
        for(const auto& ring : expanded)
            expandedPointCount = checkedSizeSum(
                expandedPointCount, ring.size());
        complexityBudget.consumeClipperOutputPoints(expandedPointCount);
        complexityBudget.consumeClipperOutputRings(expanded.size());
        const size_t outputSizeBefore = output.paths.size();
        for(const auto& ring : expanded) {
            if(ring.size() < 3)
                continue;
            complexityBudget.consumeGeneratedPoints(ring.size());
            complexityBudget.consumeGeneratedRings();
            LocalPath localRing;
            localRing.reserve(ring.size());
            for(const auto& point : ring) {
                localRing.push_back({
                    quantizationOrigin.x + point.x * effectiveGridStep,
                    quantizationOrigin.y + point.y * effectiveGridStep,
                });
            }
            output.paths.push_back({
                std::move(localRing), subpath.source_subpath_index,
            });
        }
        if(output.paths.size() == outputSizeBefore)
            output.collapsed_subpath_indices.push_back(
                subpath.source_subpath_index);
    }
    return output;
}

} // namespace lumina_svg_core
