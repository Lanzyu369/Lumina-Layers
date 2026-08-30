#ifndef LUMINA_SVG_CORE_GEOMETRY_KERNEL_H
#define LUMINA_SVG_CORE_GEOMETRY_KERNEL_H

#include "lumina_svg_core/result.h"

#include <memory>
#include <string>

namespace lumina_svg_core {

std::shared_ptr<NativeResult> analyzeSvg(const std::string& filename,
                                         double targetWidthMm,
                                         double toleranceMm);
std::shared_ptr<NativeResult> analyzeSvgData(const std::string& svg,
                                             double targetWidthMm,
                                             double toleranceMm);

} // namespace lumina_svg_core

#endif // LUMINA_SVG_CORE_GEOMETRY_KERNEL_H
