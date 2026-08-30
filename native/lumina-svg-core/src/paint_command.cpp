#include "lumina_svg_core/paint_command.h"

#include <memory>
#include <utility>

namespace lumina_svg_core {
namespace {

RecorderResult finishRecording(std::unique_ptr<lunasvg::Document> document)
{
    if(!document)
        return {};

    auto recorded = document->recordPaintCommands();
    RecorderResult result;
    result.schema_version = recorded.schema_version;
    result.bounds = recorded.bounds;
    if(!recorded.capability_issues.empty()) {
        result.status = "unsupported";
        result.reason_code = recorded.capability_issues.front();
        return result;
    }

    result.status = "supported";
    result.reason_code.clear();
    result.commands = std::move(recorded.commands);
    return result;
}

} // namespace

RecorderResult recordPaintCommands(const std::string& filename)
{
    return finishRecording(lunasvg::Document::loadFromFile(filename));
}

RecorderResult recordPaintCommandsSvg(const std::string& svg)
{
    return finishRecording(lunasvg::Document::loadFromData(svg));
}

} // namespace lumina_svg_core
