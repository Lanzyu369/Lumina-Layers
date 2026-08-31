#include "lumina_svg_core/stroke_expander.h"

#include <clipper2/clipper.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <utility>
#include <vector>

namespace lumina_svg_core {
namespace {

struct LocalSubpath {
    LocalPath points;
    bool closed{false};
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
                  double tolerance, unsigned depth, LocalPath& output)
{
    if(depth >= 32
            || (pointSegmentDistance(control1, start, end) <= tolerance
                && pointSegmentDistance(control2, start, end) <= tolerance)) {
        output.push_back(end);
        return;
    }
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
    flattenCubic(start, p01, p012, midpoint, tolerance, depth + 1, output);
    flattenCubic(midpoint, p123, p23, end, tolerance, depth + 1, output);
}

std::vector<LocalSubpath> flattenPath(const lunasvg::PaintCommand& command,
                                      double tolerance)
{
    std::vector<LocalSubpath> output;
    LocalSubpath currentSubpath;
    LocalPoint currentPoint;
    LocalPoint subpathStart;
    bool hasCurrentPoint = false;
    size_t pointIndex = 0;
    auto finish = [&]() {
        currentSubpath.points.erase(
            std::unique(
                currentSubpath.points.begin(), currentSubpath.points.end(),
                [](const LocalPoint& left, const LocalPoint& right) {
                    return left.x == right.x && left.y == right.y;
                }),
            currentSubpath.points.end());
        if(!currentSubpath.points.empty())
            output.emplace_back(std::move(currentSubpath));
        currentSubpath = {};
    };

    for(const auto verb : command.path_verbs) {
        switch(verb) {
        case lunasvg::PaintPathVerb::MoveTo: {
            finish();
            const auto& point = command.path_points.at(pointIndex++);
            currentPoint = {point.x, point.y};
            subpathStart = currentPoint;
            hasCurrentPoint = true;
            currentSubpath.points.push_back(currentPoint);
            break;
        }
        case lunasvg::PaintPathVerb::LineTo: {
            const auto& point = command.path_points.at(pointIndex++);
            if(currentSubpath.points.empty() && hasCurrentPoint)
                currentSubpath.points.push_back(currentPoint);
            currentPoint = {point.x, point.y};
            currentSubpath.points.push_back(currentPoint);
            break;
        }
        case lunasvg::PaintPathVerb::CubicTo: {
            const auto& first = command.path_points.at(pointIndex++);
            const auto& second = command.path_points.at(pointIndex++);
            const auto& last = command.path_points.at(pointIndex++);
            const LocalPoint control1{first.x, first.y};
            const LocalPoint control2{second.x, second.y};
            const LocalPoint end{last.x, last.y};
            if(currentSubpath.points.empty() && hasCurrentPoint)
                currentSubpath.points.push_back(currentPoint);
            flattenCubic(currentPoint, control1, control2, end,
                         tolerance, 0, currentSubpath.points);
            currentPoint = end;
            break;
        }
        case lunasvg::PaintPathVerb::Close:
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

std::vector<double> normalizedDashArray(const std::vector<float>& source)
{
    std::vector<double> dashArray;
    dashArray.reserve(source.size() * 2);
    for(const auto value : source)
        dashArray.push_back(std::abs(static_cast<double>(value)));
    if(dashArray.size() % 2 == 1) {
        const auto copy = dashArray;
        dashArray.insert(dashArray.end(), copy.begin(), copy.end());
    }
    const double total = std::accumulate(dashArray.begin(), dashArray.end(), 0.0);
    if(total <= std::numeric_limits<double>::epsilon())
        dashArray.clear();
    return dashArray;
}

std::vector<LocalSubpath> dashSubpath(const LocalSubpath& subpath,
                                      const std::vector<double>& dashArray,
                                      double dashOffset)
{
    if(dashArray.empty())
        return {subpath};

    const double total = std::accumulate(dashArray.begin(), dashArray.end(), 0.0);
    double phase = std::fmod(dashOffset, total);
    if(phase < 0)
        phase += total;
    size_t dashIndex = 0;
    while(phase >= dashArray[dashIndex]
            && dashArray[dashIndex] > 0) {
        phase -= dashArray[dashIndex];
        dashIndex = (dashIndex + 1) % dashArray.size();
    }
    double dashRemaining = dashArray[dashIndex] - phase;

    std::vector<LocalSubpath> output;
    LocalSubpath active;
    auto advanceDash = [&]() {
        size_t guard = 0;
        do {
            dashIndex = (dashIndex + 1) % dashArray.size();
            dashRemaining = dashArray[dashIndex];
            ++guard;
        } while(dashRemaining <= std::numeric_limits<double>::epsilon()
                && guard <= dashArray.size());
    };
    auto finishActive = [&]() {
        if(active.points.size() >= 2)
            output.emplace_back(std::move(active));
        active = {};
    };

    const size_t segmentCount = subpath.closed
        ? subpath.points.size() : subpath.points.size() - 1;
    for(size_t segmentIndex = 0; segmentIndex < segmentCount; ++segmentIndex) {
        LocalPoint cursor = subpath.points[segmentIndex];
        const LocalPoint end = subpath.points[
            (segmentIndex + 1) % subpath.points.size()];
        const double dx = end.x - cursor.x;
        const double dy = end.y - cursor.y;
        double segmentRemaining = std::hypot(dx, dy);
        if(segmentRemaining <= std::numeric_limits<double>::epsilon())
            continue;
        const double ux = dx / segmentRemaining;
        const double uy = dy / segmentRemaining;
        while(segmentRemaining > std::numeric_limits<double>::epsilon()) {
            if(dashRemaining <= std::numeric_limits<double>::epsilon())
                advanceDash();
            const bool isPainted = dashIndex % 2 == 0;
            const double step = std::min(segmentRemaining, dashRemaining);
            const LocalPoint next{cursor.x + ux * step, cursor.y + uy * step};
            if(isPainted) {
                if(active.points.empty())
                    active.points.push_back(cursor);
                active.points.push_back(next);
            }
            cursor = next;
            segmentRemaining -= step;
            dashRemaining -= step;
            if(dashRemaining <= std::numeric_limits<double>::epsilon()) {
                if(isPainted)
                    finishActive();
                advanceDash();
            }
        }
    }
    finishActive();
    if(subpath.closed && !output.empty()) {
        auto samePoint = [](const LocalPoint& left, const LocalPoint& right) {
            const double scale = std::max({
                1.0,
                std::abs(left.x), std::abs(left.y),
                std::abs(right.x), std::abs(right.y),
            });
            return std::hypot(left.x - right.x, left.y - right.y)
                <= std::numeric_limits<double>::epsilon() * scale * 32.0;
        };
        if(output.size() >= 2
                && samePoint(
                    output.back().points.back(),
                    output.front().points.front())) {
            LocalSubpath merged = std::move(output.back());
            output.pop_back();
            const auto& first = output.front();
            merged.points.insert(
                merged.points.end(),
                first.points.begin() + 1, first.points.end());
            output.erase(output.begin());
            output.insert(output.begin(), std::move(merged));
        }
        auto& seam = output.front();
        if(seam.points.size() >= 2
                && samePoint(seam.points.front(), seam.points.back())) {
            seam.points.pop_back();
            seam.closed = true;
        }
    }
    return output;
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
        throw std::range_error("numeric_range_error");
    return static_cast<int64_t>(std::llround(value));
}

LocalPath pointCap(const LocalPoint& point,
                   lunasvg::PaintLineCap cap,
                   double radius,
                   double flattenTolerance)
{
    constexpr double PI = 3.141592653589793238462643383279502884;
    if(cap == lunasvg::PaintLineCap::Butt)
        return {};
    if(cap == lunasvg::PaintLineCap::Square) {
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
    const size_t segmentCount = std::clamp<size_t>(
        halfAngle > 0
            ? static_cast<size_t>(std::ceil(PI / halfAngle))
            : 4096,
        8, 4096);
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

LocalPaths expandStrokeLocal(const lunasvg::PaintCommand& command,
                             double localFlattenTolerance,
                             double localGridStep)
{
    if(!(std::isfinite(command.stroke.width) && command.stroke.width > 0)
            || !(std::isfinite(localFlattenTolerance)
                 && localFlattenTolerance > 0)
            || !(std::isfinite(localGridStep) && localGridStep > 0))
        return {};

    const auto dashArray = normalizedDashArray(command.stroke.dash_array);
    std::vector<LocalSubpath> strokeSubpaths;
    for(const auto& subpath : flattenPath(command, localFlattenTolerance)) {
        auto dashed = dashSubpath(subpath, dashArray,
                                  command.stroke.dash_offset);
        strokeSubpaths.insert(strokeSubpaths.end(),
                              std::make_move_iterator(dashed.begin()),
                              std::make_move_iterator(dashed.end()));
    }

    LocalPaths output;
    const double delta = command.stroke.width * 0.5 / localGridStep;
    const double arcTolerance = localFlattenTolerance / localGridStep;
    for(const auto& subpath : strokeSubpaths) {
        if(subpath.points.size() == 1) {
            auto cap = pointCap(
                subpath.points.front(), command.stroke.line_cap,
                command.stroke.width * 0.5, localFlattenTolerance);
            if(!cap.empty())
                output.emplace_back(std::move(cap));
            continue;
        }
        Clipper2Lib::Path64 path;
        path.reserve(subpath.points.size());
        for(const auto& point : subpath.points) {
            const Clipper2Lib::Point64 quantized(
                quantizeLocal(point.x / localGridStep),
                quantizeLocal(point.y / localGridStep));
            if(path.empty() || path.back() != quantized)
                path.push_back(quantized);
        }
        if(path.size() < 2)
            continue;
        auto expanded = Clipper2Lib::InflatePaths(
            {path}, delta, joinType(command.stroke.line_join),
            endType(command.stroke.line_cap, subpath.closed),
            command.stroke.miter_limit, arcTolerance);
        for(const auto& ring : expanded) {
            if(ring.size() < 3)
                continue;
            LocalPath localRing;
            localRing.reserve(ring.size());
            for(const auto& point : ring) {
                localRing.push_back({point.x * localGridStep,
                                     point.y * localGridStep});
            }
            output.emplace_back(std::move(localRing));
        }
    }
    return output;
}

} // namespace lumina_svg_core
