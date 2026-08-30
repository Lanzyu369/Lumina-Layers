#ifndef LUMINA_SVG_CORE_STROKE_EXPANDER_H
#define LUMINA_SVG_CORE_STROKE_EXPANDER_H

#include <lunasvg.h>

#include <vector>

namespace lumina_svg_core {

struct LocalPoint {
    double x{0};
    double y{0};
};

using LocalPath = std::vector<LocalPoint>;
using LocalPaths = std::vector<LocalPath>;

// Flattens and dashes in local coordinates, then expands the centerline with
// Clipper2 before the caller applies the complete affine transform.
LocalPaths expandStrokeLocal(const lunasvg::PaintCommand& command,
                             double localFlattenTolerance,
                             double localGridStep);

} // namespace lumina_svg_core

#endif // LUMINA_SVG_CORE_STROKE_EXPANDER_H
