#include "lumina_svg_core/result.h"

#include <algorithm>

namespace lumina_svg_core {

uint64_t GeometryCollection::geometryCount() const
{
    return geometry_offsets.empty() ? 0 : geometry_offsets.size() - 1;
}

uint64_t GeometryCollection::componentCount() const
{
    return polygon_offsets.empty() ? 0 : polygon_offsets.size() - 1;
}

uint64_t GeometryCollection::holeCount() const
{
    return static_cast<uint64_t>(std::count_if(
        hole_parent.begin(), hole_parent.end(),
        [](int64_t parent) { return parent >= 0; }));
}

uint64_t UnprintableFragmentCollection::count() const
{
    return static_cast<uint64_t>(reason_ids.size());
}

} // namespace lumina_svg_core
