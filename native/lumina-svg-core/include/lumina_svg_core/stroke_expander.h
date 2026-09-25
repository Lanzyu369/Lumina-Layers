#ifndef LUMINA_SVG_CORE_STROKE_EXPANDER_H
#define LUMINA_SVG_CORE_STROKE_EXPANDER_H

#include <lunasvg.h>

#include <cstdint>
#include <stdexcept>
#include <vector>

namespace lumina_svg_core {

class ComplexityBudget;

struct LocalPoint {
    double x{0};
    double y{0};
};

using LocalPath = std::vector<LocalPoint>;

struct ExpandedStrokePath {
    LocalPath points;
    int32_t source_subpath_index{-1};
};

struct StrokeExpansion {
    std::vector<ExpandedStrokePath> paths;
    std::vector<int32_t> collapsed_subpath_indices;
};

class StrokeInputPrecisionError : public std::runtime_error {
public:
    explicit StrokeInputPrecisionError(
        const char* detail = "stroke_input_precision")
        : std::runtime_error(detail)
    {}
};

// Flattens and dashes in local coordinates, then expands the centerline with
// Clipper2 before the caller applies the complete affine transform.
StrokeExpansion expandStrokeLocal(
    const lunasvg::PaintCommand& command,
    double localFlattenTolerance,
    double localGridStep,
    ComplexityBudget& complexityBudget,
    bool enforcePhysicalTolerance = true);

} // namespace lumina_svg_core

#endif // LUMINA_SVG_CORE_STROKE_EXPANDER_H
