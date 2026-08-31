#include "lumina_svg_core/paint_command.h"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iterator>
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
    return {};
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
    result.image_vectorizer_origin = recorded.image_vectorizer_origin;
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
    return recordPaintCommandsPath(std::filesystem::u8path(filename));
}

RecorderResult recordPaintCommandsPath(const std::filesystem::path& filename)
{
    std::ifstream stream(filename, std::ios::binary);
    if(!stream)
        return {};
    std::string svg{
        std::istreambuf_iterator<char>(stream),
        std::istreambuf_iterator<char>()};
    if(stream.bad())
        return {};
    return finishRecording(lunasvg::Document::loadFromData(svg));
}

RecorderResult recordPaintCommandsSvg(const std::string& svg)
{
    return finishRecording(lunasvg::Document::loadFromData(svg));
}

} // namespace lumina_svg_core
