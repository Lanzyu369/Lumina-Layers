#ifndef LUMINA_SVG_CORE_PAINT_COMMAND_H
#define LUMINA_SVG_CORE_PAINT_COMMAND_H

#include <lunasvg.h>

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace lumina_svg_core {

inline constexpr uint32_t RECORDER_SCHEMA_VERSION = 4;

static_assert(
    RECORDER_SCHEMA_VERSION == lunasvg::PAINT_COMMAND_SCHEMA_VERSION,
    "LunaSVG paint-command schema must match the wrapper schema");

struct RecorderResult {
    std::string status{"invalid"};
    std::string reason_code{"invalid_svg"};
    uint32_t schema_version{RECORDER_SCHEMA_VERSION};
    lunasvg::Box bounds;
    lunasvg::Box viewport;
    bool image_vectorizer_origin{false};
    bool has_non_scaling_stroke{false};
    std::vector<lunasvg::PaintCommand> commands;
};

RecorderResult recordPaintCommands(const std::string& filename);
RecorderResult recordPaintCommandsPath(const std::filesystem::path& filename);
RecorderResult recordPaintCommandsSvg(const std::string& svg);

} // namespace lumina_svg_core

#endif // LUMINA_SVG_CORE_PAINT_COMMAND_H
