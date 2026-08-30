#include "lumina_svg_core/paint_command.h"

#include <algorithm>
#include <cmath>
#include <locale>
#include <memory>
#include <sstream>
#include <string>
#include <utility>

namespace lumina_svg_core {
namespace {

lunasvg::Box documentViewport(lunasvg::Document& document)
{
    auto text = document.documentElement().getAttribute("viewBox");
    std::replace(text.begin(), text.end(), ',', ' ');
    std::istringstream stream(text);
    stream.imbue(std::locale::classic());
    double x = 0;
    double y = 0;
    double width = 0;
    double height = 0;
    std::string trailing;
    if(stream >> x >> y >> width >> height
            && !(stream >> trailing)
            && std::isfinite(x) && std::isfinite(y)
            && std::isfinite(width) && std::isfinite(height)
            && width > 0 && height > 0) {
        return lunasvg::Box(
            static_cast<float>(x), static_cast<float>(y),
            static_cast<float>(width), static_cast<float>(height));
    }
    return lunasvg::Box(0, 0, document.width(), document.height());
}

RecorderResult finishRecording(std::unique_ptr<lunasvg::Document> document)
{
    if(!document)
        return {};

    auto recorded = document->recordPaintCommands();
    RecorderResult result;
    result.schema_version = recorded.schema_version;
    result.bounds = recorded.bounds;
    result.viewport = documentViewport(*document);
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
