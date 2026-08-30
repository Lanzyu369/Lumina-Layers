#ifndef LUMINA_SVG_CORE_PAINT_COMMAND_H
#define LUMINA_SVG_CORE_PAINT_COMMAND_H

#include <lunasvg.h>

#include <cstdint>
#include <string>
#include <vector>

namespace lumina_svg_core {

inline constexpr uint32_t RECORDER_SCHEMA_VERSION = 1;

struct RecorderResult {
    std::string status{"invalid"};
    std::string reason_code{"invalid_svg"};
    uint32_t schema_version{RECORDER_SCHEMA_VERSION};
    lunasvg::Box bounds;
    lunasvg::Box viewport;
    std::vector<lunasvg::PaintCommand> commands;
};

RecorderResult recordPaintCommands(const std::string& filename);
RecorderResult recordPaintCommandsSvg(const std::string& svg);

} // namespace lumina_svg_core

#endif // LUMINA_SVG_CORE_PAINT_COMMAND_H
