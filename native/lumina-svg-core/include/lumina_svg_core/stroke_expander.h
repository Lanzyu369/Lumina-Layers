#ifndef LUMINA_SVG_CORE_STROKE_EXPANDER_H
#define LUMINA_SVG_CORE_STROKE_EXPANDER_H

#include <lunasvg.h>

#include <stdexcept>
#include <vector>

namespace lumina_svg_core {

class ComplexityBudget;

struct LocalPoint {
    double x{0};
    double y{0};
};

using LocalPath = std::vector<LocalPoint>;
using LocalPaths = std::vector<LocalPath>;

class StrokeInputPrecisionError : public std::runtime_error {
public:
    StrokeInputPrecisionError()
        : std::runtime_error("stroke input precision is ambiguous")
    {}
};

// Flattens and dashes in local coordinates, then expands the centerline with
// Clipper2 before the caller applies the complete affine transform.
LocalPaths expandStrokeLocal(const lunasvg::PaintCommand& command,
                             double localFlattenTolerance,
                             double localGridStep,
                             ComplexityBudget& complexityBudget);

} // namespace lumina_svg_core

#endif // LUMINA_SVG_CORE_STROKE_EXPANDER_H
