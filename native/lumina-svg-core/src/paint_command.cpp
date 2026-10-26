#include "lumina_svg_core/paint_command.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <locale>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace lumina_svg_core {
namespace {

RecorderResult finishRecording(std::unique_ptr<lunasvg::Document> document);

bool startsWith(std::string_view value, std::string_view prefix)
{
    return value.size() >= prefix.size()
        && value.substr(0, prefix.size()) == prefix;
}

bool isXmlSpace(char value)
{
    return value == ' ' || value == '\t'
        || value == '\r' || value == '\n';
}

std::optional<std::string> declaredXmlEncoding(std::string_view svg)
{
    constexpr std::string_view UTF8_BOM{"\xEF\xBB\xBF", 3};
    if(startsWith(svg, UTF8_BOM))
        svg.remove_prefix(UTF8_BOM.size());
    if(!startsWith(svg, "<?xml"))
        return std::nullopt;
    svg.remove_prefix(5);
    const auto declarationEnd = svg.find("?>");
    if(declarationEnd == std::string_view::npos)
        return std::nullopt;
    auto declaration = svg.substr(0, declarationEnd);
    size_t offset = 0;
    while(offset < declaration.size()) {
        while(offset < declaration.size()
                && isXmlSpace(declaration[offset]))
            ++offset;
        if(offset == declaration.size())
            break;
        const size_t nameStart = offset;
        while(offset < declaration.size()
                && (std::isalnum(
                        static_cast<unsigned char>(declaration[offset]))
                    || declaration[offset] == '_'
                    || declaration[offset] == ':'
                    || declaration[offset] == '-'
                    || declaration[offset] == '.'))
            ++offset;
        if(offset == nameStart)
            return std::nullopt;
        const auto name = declaration.substr(nameStart, offset - nameStart);
        while(offset < declaration.size()
                && isXmlSpace(declaration[offset]))
            ++offset;
        if(offset == declaration.size() || declaration[offset] != '=')
            return std::nullopt;
        ++offset;
        while(offset < declaration.size()
                && isXmlSpace(declaration[offset]))
            ++offset;
        if(offset == declaration.size()
                || (declaration[offset] != '\''
                    && declaration[offset] != '"'))
            return std::nullopt;
        const char quote = declaration[offset++];
        const size_t valueStart = offset;
        const auto valueEnd = declaration.find(quote, offset);
        if(valueEnd == std::string_view::npos)
            return std::nullopt;
        offset = valueEnd + 1;
        if(name == "encoding")
            return std::string(
                declaration.substr(valueStart, valueEnd - valueStart));
    }
    return std::nullopt;
}

bool hasUnsupportedXmlEncoding(std::string_view svg)
{
    constexpr std::string_view UTF32_BE_BOM{"\x00\x00\xFE\xFF", 4};
    constexpr std::string_view UTF32_LE_BOM{"\xFF\xFE\x00\x00", 4};
    constexpr std::string_view UTF16_BE_BOM{"\xFE\xFF", 2};
    constexpr std::string_view UTF16_LE_BOM{"\xFF\xFE", 2};
    constexpr std::string_view UTF32_BE_SIGNATURE{"\x00\x00\x00\x3C", 4};
    constexpr std::string_view UTF32_LE_SIGNATURE{"\x3C\x00\x00\x00", 4};
    constexpr std::string_view UTF16_BE_SIGNATURE{"\x00\x3C\x00\x3F", 4};
    constexpr std::string_view UTF16_LE_SIGNATURE{"\x3C\x00\x3F\x00", 4};
    constexpr std::string_view EBCDIC_SIGNATURE{"\x4C\x6F\xA7\x94", 4};
    if(startsWith(svg, UTF32_BE_BOM)
            || startsWith(svg, UTF32_LE_BOM)
            || startsWith(svg, UTF16_BE_BOM)
            || startsWith(svg, UTF16_LE_BOM)
            || startsWith(svg, UTF32_BE_SIGNATURE)
            || startsWith(svg, UTF32_LE_SIGNATURE)
            || startsWith(svg, UTF16_BE_SIGNATURE)
            || startsWith(svg, UTF16_LE_SIGNATURE)
            || startsWith(svg, EBCDIC_SIGNATURE))
        return true;

    auto encoding = declaredXmlEncoding(svg);
    if(!encoding.has_value())
        return false;
    std::transform(
        encoding->begin(), encoding->end(), encoding->begin(),
        [](unsigned char character) {
            return static_cast<char>(std::tolower(character));
        });
    return *encoding != "utf-8";
}

RecorderResult unsupportedXmlEncoding()
{
    RecorderResult result;
    result.status = "unsupported";
    result.reason_code = "unsupported_xml_encoding";
    return result;
}

RecorderResult unsupportedComplexity()
{
    RecorderResult result;
    result.status = "unsupported";
    result.reason_code = "unsupported_complexity";
    return result;
}

RecorderResult unsupportedNamespace()
{
    RecorderResult result;
    result.status = "unsupported";
    result.reason_code = "unsupported_namespace";
    return result;
}

RecorderResult unsupportedXmlName()
{
    RecorderResult result;
    result.status = "unsupported";
    result.reason_code = "unsupported_xml_name";
    return result;
}

RecorderResult unsupportedDoctype()
{
    RecorderResult result;
    result.status = "unsupported";
    result.reason_code = "unsupported_doctype";
    return result;
}

struct XmlAttributeView {
    std::string_view name;
    std::string_view value;
};

struct XmlStartTagView {
    std::string_view name;
    std::vector<XmlAttributeView> attributes;
    size_t end{std::string_view::npos};
    bool self_closing{false};
};

bool parseStartTag(std::string_view svg, size_t offset,
                   XmlStartTagView& tag)
{
    size_t cursor = offset + 1;
    while(cursor < svg.size() && isXmlSpace(svg[cursor]))
        ++cursor;
    const size_t nameStart = cursor;
    while(cursor < svg.size()
            && !isXmlSpace(svg[cursor])
            && svg[cursor] != '/' && svg[cursor] != '>')
        ++cursor;
    if(cursor == nameStart)
        return false;
    tag.name = svg.substr(nameStart, cursor - nameStart);

    while(cursor < svg.size()) {
        while(cursor < svg.size() && isXmlSpace(svg[cursor]))
            ++cursor;
        if(cursor >= svg.size())
            return false;
        if(svg[cursor] == '>') {
            tag.end = cursor;
            return true;
        }
        if(svg[cursor] == '/') {
            ++cursor;
            while(cursor < svg.size() && isXmlSpace(svg[cursor]))
                ++cursor;
            if(cursor >= svg.size() || svg[cursor] != '>')
                return false;
            tag.self_closing = true;
            tag.end = cursor;
            return true;
        }

        const size_t attributeNameStart = cursor;
        while(cursor < svg.size()
                && !isXmlSpace(svg[cursor])
                && svg[cursor] != '=' && svg[cursor] != '/'
                && svg[cursor] != '>')
            ++cursor;
        if(cursor == attributeNameStart)
            return false;
        const auto attributeName = svg.substr(
            attributeNameStart, cursor - attributeNameStart);
        while(cursor < svg.size() && isXmlSpace(svg[cursor]))
            ++cursor;
        if(cursor >= svg.size() || svg[cursor] != '=')
            return false;
        ++cursor;
        while(cursor < svg.size() && isXmlSpace(svg[cursor]))
            ++cursor;
        if(cursor >= svg.size()
                || (svg[cursor] != '\'' && svg[cursor] != '"'))
            return false;
        const char quote = svg[cursor++];
        const size_t valueStart = cursor;
        const auto valueEnd = svg.find(quote, cursor);
        if(valueEnd == std::string_view::npos)
            return false;
        tag.attributes.push_back({
            attributeName,
            svg.substr(valueStart, valueEnd - valueStart),
        });
        cursor = valueEnd + 1;
    }
    return false;
}

bool hasDoctypeDeclaration(std::string_view svg)
{
    size_t offset = 0;
    while((offset = svg.find('<', offset)) != std::string_view::npos) {
        const auto remainder = svg.substr(offset);
        if(startsWith(remainder, "<!--")) {
            const auto end = svg.find("-->", offset + 4);
            if(end == std::string_view::npos)
                return false;
            offset = end + 3;
            continue;
        }
        if(startsWith(remainder, "<![CDATA[")) {
            const auto end = svg.find("]]>", offset + 9);
            if(end == std::string_view::npos)
                return false;
            offset = end + 3;
            continue;
        }
        if(startsWith(remainder, "<?")) {
            const auto end = svg.find("?>", offset + 2);
            if(end == std::string_view::npos)
                return false;
            offset = end + 2;
            continue;
        }
        if(startsWith(remainder, "<!DOCTYPE"))
            return true;
        ++offset;
    }
    return false;
}

enum class NamespaceValidation {
    Supported,
    Invalid,
    Unsupported,
    UnsupportedXmlName,
};

enum class XmlNameValidation {
    Ascii,
    NonAscii,
    Invalid,
};

bool decodeUtf8CodePoint(std::string_view value, size_t& offset,
                         uint32_t& codePoint)
{
    if(offset >= value.size())
        return false;
    const auto first = static_cast<unsigned char>(value[offset]);
    size_t length = 0;
    if(first < 0x80) {
        codePoint = first;
        length = 1;
    } else if((first & 0xE0) == 0xC0) {
        codePoint = first & 0x1F;
        length = 2;
    } else if((first & 0xF0) == 0xE0) {
        codePoint = first & 0x0F;
        length = 3;
    } else if((first & 0xF8) == 0xF0) {
        codePoint = first & 0x07;
        length = 4;
    } else {
        return false;
    }
    if(length > value.size() - offset)
        return false;
    for(size_t index = 1; index < length; ++index) {
        const auto next = static_cast<unsigned char>(value[offset + index]);
        if((next & 0xC0) != 0x80)
            return false;
        codePoint = (codePoint << 6) | (next & 0x3F);
    }
    if((length == 2 && codePoint < 0x80)
            || (length == 3 && codePoint < 0x800)
            || (length == 4 && codePoint < 0x10000)
            || codePoint > 0x10FFFF
            || (codePoint >= 0xD800 && codePoint <= 0xDFFF))
        return false;
    offset += length;
    return true;
}

bool isXmlNameStartCodePoint(uint32_t value)
{
    return value == ':' || value == '_'
        || (value >= 'A' && value <= 'Z')
        || (value >= 'a' && value <= 'z')
        || (value >= 0xC0 && value <= 0xD6)
        || (value >= 0xD8 && value <= 0xF6)
        || (value >= 0xF8 && value <= 0x2FF)
        || (value >= 0x370 && value <= 0x37D)
        || (value >= 0x37F && value <= 0x1FFF)
        || (value >= 0x200C && value <= 0x200D)
        || (value >= 0x2070 && value <= 0x218F)
        || (value >= 0x2C00 && value <= 0x2FEF)
        || (value >= 0x3001 && value <= 0xD7FF)
        || (value >= 0xF900 && value <= 0xFDCF)
        || (value >= 0xFDF0 && value <= 0xFFFD)
        || (value >= 0x10000 && value <= 0xEFFFF);
}

bool isXmlNameCodePoint(uint32_t value)
{
    return isXmlNameStartCodePoint(value)
        || value == '-' || value == '.'
        || (value >= '0' && value <= '9')
        || value == 0xB7
        || (value >= 0x0300 && value <= 0x036F)
        || (value >= 0x203F && value <= 0x2040);
}

XmlNameValidation validateXmlName(std::string_view value)
{
    if(value.empty())
        return XmlNameValidation::Invalid;
    bool nonAscii = false;
    size_t offset = 0;
    size_t index = 0;
    while(offset < value.size()) {
        uint32_t codePoint = 0;
        if(!decodeUtf8CodePoint(value, offset, codePoint))
            return XmlNameValidation::Invalid;
        if((index == 0 && !isXmlNameStartCodePoint(codePoint))
                || (index != 0 && !isXmlNameCodePoint(codePoint)))
            return XmlNameValidation::Invalid;
        nonAscii = nonAscii || codePoint >= 0x80;
        ++index;
    }
    return nonAscii
        ? XmlNameValidation::NonAscii
        : XmlNameValidation::Ascii;
}

std::optional<std::string_view> qNamePrefix(std::string_view name)
{
    const auto separator = name.find(':');
    if(separator == std::string_view::npos)
        return std::string_view{};
    if(separator == 0 || separator + 1 == name.size()
            || name.find(':', separator + 1) != std::string_view::npos)
        return std::nullopt;
    return name.substr(0, separator);
}

bool namespaceUriEquals(std::string_view encoded,
                        std::string_view expected)
{
    size_t expectedOffset = 0;
    while(!encoded.empty()) {
        char decoded = encoded.front();
        if(decoded != '&') {
            encoded.remove_prefix(1);
        } else {
            const auto end = encoded.find(';');
            if(end == std::string_view::npos)
                return false;
            const auto reference = encoded.substr(1, end - 1);
            if(reference == "amp") decoded = '&';
            else if(reference == "lt") decoded = '<';
            else if(reference == "gt") decoded = '>';
            else if(reference == "quot") decoded = '"';
            else if(reference == "apos") decoded = '\'';
            else if(!reference.empty() && reference.front() == '#') {
                size_t offset = 1;
                int base = 10;
                if(offset < reference.size()
                        && (reference[offset] == 'x'
                            || reference[offset] == 'X')) {
                    base = 16;
                    ++offset;
                }
                if(offset == reference.size())
                    return false;
                uint32_t value = 0;
                for(; offset < reference.size(); ++offset) {
                    const unsigned char digit = reference[offset];
                    uint32_t numeric = 0;
                    if(digit >= '0' && digit <= '9')
                        numeric = digit - '0';
                    else if(base == 16 && digit >= 'a' && digit <= 'f')
                        numeric = digit - 'a' + 10;
                    else if(base == 16 && digit >= 'A' && digit <= 'F')
                        numeric = digit - 'A' + 10;
                    else
                        return false;
                    if(value > (0x7FU - numeric)
                            / static_cast<uint32_t>(base))
                        return false;
                    value = value * static_cast<uint32_t>(base) + numeric;
                }
                decoded = static_cast<char>(value);
            } else {
                return false;
            }
            encoded.remove_prefix(end + 1);
        }
        if(expectedOffset >= expected.size()
                || expected[expectedOffset++] != decoded)
            return false;
    }
    return expectedOffset == expected.size();
}

NamespaceValidation validateNamespaceBindings(std::string_view svg)
{
    constexpr std::string_view XML_NAMESPACE =
        "http://www.w3.org/XML/1998/namespace";
    constexpr std::string_view SVG_NAMESPACE =
        "http://www.w3.org/2000/svg";
    constexpr std::string_view XLINK_NAMESPACE =
        "http://www.w3.org/1999/xlink";
    struct NamespaceChange {
        std::string_view prefix;
        bool existed{false};
        std::string_view previous;
    };
    std::unordered_map<std::string_view, std::string_view> bindings;
    bindings.emplace("xml", XML_NAMESPACE);
    std::vector<std::vector<NamespaceChange>> namespaceScopes;
    std::vector<std::string_view> openElementNames;
    bool unsupportedNamespaceSeen = false;
    const auto restoreBindings = [&bindings](
        const std::vector<NamespaceChange>& changes) {
        for(auto change = changes.rbegin(); change != changes.rend();
                ++change) {
            if(change->existed)
                bindings.insert_or_assign(change->prefix, change->previous);
            else
                bindings.erase(change->prefix);
        }
    };
    size_t offset = 0;
    while((offset = svg.find('<', offset)) != std::string_view::npos) {
        if(startsWith(svg.substr(offset), "<!--")) {
            const auto end = svg.find("-->", offset + 4);
            if(end == std::string_view::npos)
                return NamespaceValidation::Supported;
            offset = end + 3;
            continue;
        }
        if(startsWith(svg.substr(offset), "<![CDATA[")) {
            const auto end = svg.find("]]>", offset + 9);
            if(end == std::string_view::npos)
                return NamespaceValidation::Supported;
            offset = end + 3;
            continue;
        }
        if(startsWith(svg.substr(offset), "<?")) {
            const auto end = svg.find("?>", offset + 2);
            if(end == std::string_view::npos)
                return NamespaceValidation::Supported;
            offset = end + 2;
            continue;
        }
        if(startsWith(svg.substr(offset), "<!")) {
            const auto end = svg.find('>', offset + 2);
            if(end == std::string_view::npos)
                return NamespaceValidation::Supported;
            offset = end + 1;
            continue;
        }

        if(offset + 1 < svg.size() && svg[offset + 1] == '/') {
            size_t cursor = offset + 2;
            while(cursor < svg.size() && isXmlSpace(svg[cursor]))
                ++cursor;
            const size_t nameStart = cursor;
            while(cursor < svg.size()
                    && !isXmlSpace(svg[cursor]) && svg[cursor] != '>')
                ++cursor;
            const auto closingName = svg.substr(
                nameStart, cursor - nameStart);
            const auto closingNameValidation = validateXmlName(closingName);
            if(closingNameValidation == XmlNameValidation::Invalid)
                return NamespaceValidation::Invalid;
            if(closingNameValidation == XmlNameValidation::NonAscii)
                return NamespaceValidation::UnsupportedXmlName;
            if(!qNamePrefix(closingName).has_value())
                return NamespaceValidation::Invalid;
            if(openElementNames.empty()
                    || openElementNames.back() != closingName)
                return NamespaceValidation::Invalid;
            const auto end = svg.find('>', cursor);
            if(end == std::string_view::npos)
                return NamespaceValidation::Supported;
            openElementNames.pop_back();
            if(namespaceScopes.empty())
                return NamespaceValidation::Invalid;
            restoreBindings(namespaceScopes.back());
            namespaceScopes.pop_back();
            offset = end + 1;
            continue;
        }

        XmlStartTagView tag;
        if(!parseStartTag(svg, offset, tag))
            return NamespaceValidation::Supported;
        const auto tagNameValidation = validateXmlName(tag.name);
        if(tagNameValidation == XmlNameValidation::Invalid)
            return NamespaceValidation::Invalid;
        if(tagNameValidation == XmlNameValidation::NonAscii)
            return NamespaceValidation::UnsupportedXmlName;
        for(const auto& attribute : tag.attributes) {
            const auto attributeNameValidation =
                validateXmlName(attribute.name);
            if(attributeNameValidation == XmlNameValidation::Invalid)
                return NamespaceValidation::Invalid;
            if(attributeNameValidation == XmlNameValidation::NonAscii)
                return NamespaceValidation::UnsupportedXmlName;
        }
        std::vector<NamespaceChange> changes;
        const auto bindPrefix = [&bindings, &changes](
            std::string_view prefix, std::string_view uri) {
            const auto existing = bindings.find(prefix);
            changes.push_back({
                prefix,
                existing != bindings.end(),
                existing == bindings.end()
                    ? std::string_view{} : existing->second,
            });
            bindings.insert_or_assign(prefix, uri);
        };
        for(const auto& attribute : tag.attributes) {
            if(attribute.name == "xmlns") {
                bindPrefix(std::string_view{}, attribute.value);
                continue;
            }
            if(!startsWith(attribute.name, "xmlns:"))
                continue;
            const auto declaredPrefix = attribute.name.substr(6);
            if(declaredPrefix.empty()
                    || declaredPrefix.find(':') != std::string_view::npos)
                return NamespaceValidation::Invalid;
            if(declaredPrefix == "xml") {
                if(!namespaceUriEquals(attribute.value, XML_NAMESPACE))
                    unsupportedNamespaceSeen = true;
            } else if(declaredPrefix == "xmlns"
                    || attribute.value.empty()) {
                return NamespaceValidation::Invalid;
            } else if(declaredPrefix == "xlink"
                    && !namespaceUriEquals(
                        attribute.value, XLINK_NAMESPACE)) {
                unsupportedNamespaceSeen = true;
            }
            bindPrefix(declaredPrefix, attribute.value);
        }

        const auto elementPrefix = qNamePrefix(tag.name);
        if(!elementPrefix.has_value())
            return NamespaceValidation::Invalid;
        if(elementPrefix->empty()) {
            const auto defaultBinding = bindings.find(std::string_view{});
            if(defaultBinding != bindings.end()
                    && !namespaceUriEquals(
                        defaultBinding->second, SVG_NAMESPACE))
                unsupportedNamespaceSeen = true;
        } else {
            const auto binding = bindings.find(*elementPrefix);
            if(binding == bindings.end())
                return NamespaceValidation::Invalid;
            if(!namespaceUriEquals(binding->second, SVG_NAMESPACE))
                unsupportedNamespaceSeen = true;
        }
        for(const auto& attribute : tag.attributes) {
            if(attribute.name == "xmlns"
                    || startsWith(attribute.name, "xmlns:"))
                continue;
            const auto attributePrefix = qNamePrefix(attribute.name);
            if(!attributePrefix.has_value())
                return NamespaceValidation::Invalid;
            if(attributePrefix->empty())
                continue;
            const auto binding = bindings.find(*attributePrefix);
            if(binding == bindings.end())
                return NamespaceValidation::Invalid;
            if(*attributePrefix == "xlink"
                    && !namespaceUriEquals(
                        binding->second, XLINK_NAMESPACE))
                unsupportedNamespaceSeen = true;
            if(*attributePrefix != "xlink"
                    && namespaceUriEquals(
                        binding->second, XLINK_NAMESPACE))
                unsupportedNamespaceSeen = true;
        }
        if(tag.self_closing) {
            restoreBindings(changes);
        } else {
            namespaceScopes.push_back(std::move(changes));
            openElementNames.push_back(tag.name);
        }
        offset = tag.end + 1;
    }
    return unsupportedNamespaceSeen
        ? NamespaceValidation::Unsupported
        : NamespaceValidation::Supported;
}

RecorderResult recordUtf8Svg(std::string_view svg)
{
    if(hasUnsupportedXmlEncoding(svg))
        return unsupportedXmlEncoding();
    if(hasDoctypeDeclaration(svg))
        return unsupportedDoctype();
    const auto namespaceValidation = validateNamespaceBindings(svg);
    if(namespaceValidation == NamespaceValidation::Invalid)
        return {};
    if(namespaceValidation == NamespaceValidation::Unsupported)
        return unsupportedNamespace();
    if(namespaceValidation == NamespaceValidation::UnsupportedXmlName)
        return unsupportedXmlName();
    constexpr std::string_view UTF8_BOM{"\xEF\xBB\xBF", 3};
    if(startsWith(svg, UTF8_BOM))
        svg.remove_prefix(UTF8_BOM.size());
    try {
        return finishRecording(
            lunasvg::Document::loadFromData(std::string(svg)));
    } catch(const std::length_error&) {
        return unsupportedComplexity();
    }
}

lunasvg::Box documentViewport(lunasvg::Document& document)
{
    // Paint commands already include the root viewBox-to-viewport transform.
    // Keep the viewport in that same recorded coordinate domain. Returning
    // the raw viewBox origin here would combine source and post-transform
    // coordinates when the kernel computes Lumina's canonical bbox.
    auto text = document.documentElement().getAttribute("viewBox");
    std::replace(text.begin(), text.end(), ',', ' ');
    std::istringstream stream(text);
    stream.imbue(std::locale::classic());
    double sourceX = 0;
    double sourceY = 0;
    double sourceWidth = 0;
    double sourceHeight = 0;
    std::string trailing;
    if(stream >> sourceX >> sourceY >> sourceWidth >> sourceHeight
            && !(stream >> trailing)
            && std::isfinite(sourceX) && std::isfinite(sourceY)
            && std::isfinite(sourceWidth) && std::isfinite(sourceHeight)
            && sourceWidth > 0 && sourceHeight > 0) {
        const float width = document.width();
        const float height = document.height();
        if(std::isfinite(width) && std::isfinite(height)
                && width > 0 && height > 0)
            return lunasvg::Box(0, 0, width, height);
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
    result.has_non_scaling_stroke = std::any_of(
        result.commands.begin(), result.commands.end(),
        [](const lunasvg::PaintCommand& command) {
            return command.kind == lunasvg::PaintCommandKind::Stroke
                && command.non_scaling_stroke;
        });
    return result;
}

} // namespace

RecorderResult recordPaintCommands(const std::string& filename)
{
    return recordPaintCommandsPath(std::filesystem::u8path(filename));
}

RecorderResult recordPaintCommandsPath(const std::filesystem::path& filename)
{
    std::error_code fileSizeError;
    const auto fileSize = std::filesystem::file_size(
        filename, fileSizeError);
    std::ifstream stream(filename, std::ios::binary);
    if(!stream)
        return {};
    std::string svg;
    if(!fileSizeError)
        svg.reserve(static_cast<size_t>(fileSize));
    std::array<char, 64 * 1024> buffer;
    while(stream) {
        stream.read(buffer.data(), buffer.size());
        const auto count = stream.gcount();
        if(count <= 0)
            break;
        const auto byteCount = static_cast<size_t>(count);
        svg.append(buffer.data(), byteCount);
    }
    if(stream.bad())
        return {};
    return recordUtf8Svg(svg);
}

RecorderResult recordPaintCommandsSvg(const std::string& svg)
{
    return recordUtf8Svg(svg);
}

} // namespace lumina_svg_core
