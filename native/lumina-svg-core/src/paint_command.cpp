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
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace lumina_svg_core {
namespace {

constexpr size_t MAX_SVG_BYTES = 64 * 1024 * 1024;
constexpr size_t MAX_XML_ELEMENTS = 250'000;
constexpr size_t MAX_XML_DEPTH = 128;
constexpr size_t MAX_USE_ELEMENTS = 16;
constexpr size_t MAX_ATTRIBUTES_PER_ELEMENT = 4'096;
constexpr size_t MAX_CSS_BYTES = 1024 * 1024;
constexpr size_t MAX_CSS_RULES = 20'000;
constexpr size_t MAX_CSS_DECLARATIONS = 100'000;
constexpr size_t MAX_CSS_SELECTOR_TOKENS = 100'000;
constexpr size_t MAX_CSS_RULE_MATCH_WORK = 5'000'000;
constexpr size_t MAX_CSS_SELECTOR_MATCH_WORK = 20'000'000;
constexpr size_t MAX_CSS_DECLARATION_MATCH_WORK = 20'000'000;
constexpr size_t MAX_PATH_TOKENS_PER_ATTRIBUTE = 500'000;
constexpr size_t MAX_PATH_TOKENS = 2'000'000;
constexpr size_t MAX_POINT_VALUES_PER_ATTRIBUTE = 500'000;
constexpr size_t MAX_POINT_VALUES = 1'000'000;
constexpr size_t MAX_DASH_VALUES = 100'000;

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

RecorderResult unsupportedFontRelativeLength()
{
    RecorderResult result;
    result.status = "unsupported";
    result.reason_code = "unsupported_font_relative_length";
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
    bool attribute_limit_exceeded{false};
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
        if(tag.attributes.size() >= MAX_ATTRIBUTES_PER_ELEMENT) {
            tag.attribute_limit_exceeded = true;
            return true;
        }
        tag.attributes.push_back({
            attributeName,
            svg.substr(valueStart, valueEnd - valueStart),
        });
        cursor = valueEnd + 1;
    }
    return false;
}

bool consumeCount(size_t count, size_t limit, size_t& total)
{
    if(count > limit || total > limit - count)
        return false;
    total += count;
    return true;
}

bool isAsciiDigit(char value)
{
    return value >= '0' && value <= '9';
}

bool startsNumericToken(std::string_view value, size_t index)
{
    const char current = value[index];
    const char previous = index == 0 ? '\0' : value[index - 1];
    const char next = index + 1 < value.size() ? value[index + 1] : '\0';
    if(current == '+' || current == '-') {
        return previous != 'e' && previous != 'E'
            && (isAsciiDigit(next) || next == '.');
    }
    if(current == '.')
        return isAsciiDigit(next) && !isAsciiDigit(previous);
    if(!isAsciiDigit(current))
        return false;
    return !isAsciiDigit(previous) && previous != '.'
        && previous != '+' && previous != '-'
        && previous != 'e' && previous != 'E';
}

bool isCssIdentifierCharacter(char value)
{
    const auto character = static_cast<unsigned char>(value);
    return std::isalnum(character) || value == '_' || value == '-';
}

bool containsFontRelativeLengthUnit(std::string_view value)
{
    for(size_t index = 0; index < value.size(); ++index) {
        if(!startsNumericToken(value, index))
            continue;
        size_t cursor = index;
        if(value[cursor] == '+' || value[cursor] == '-')
            ++cursor;
        while(cursor < value.size() && isAsciiDigit(value[cursor]))
            ++cursor;
        if(cursor < value.size() && value[cursor] == '.') {
            ++cursor;
            while(cursor < value.size() && isAsciiDigit(value[cursor]))
                ++cursor;
        }
        if(cursor < value.size()
                && (value[cursor] == 'e' || value[cursor] == 'E')) {
            size_t exponent = cursor + 1;
            if(exponent < value.size()
                    && (value[exponent] == '+' || value[exponent] == '-'))
                ++exponent;
            const size_t exponentDigits = exponent;
            while(exponent < value.size()
                    && isAsciiDigit(value[exponent]))
                ++exponent;
            if(exponent > exponentDigits)
                cursor = exponent;
        }
        while(cursor < value.size() && isXmlSpace(value[cursor]))
            ++cursor;
        if(cursor + 1 >= value.size()
                || (value[cursor] != 'e' && value[cursor] != 'E')
                || (value[cursor + 1] != 'm'
                    && value[cursor + 1] != 'M'
                    && value[cursor + 1] != 'x'
                    && value[cursor + 1] != 'X'))
            continue;
        const size_t afterUnit = cursor + 2;
        if(afterUnit == value.size()
                || !isCssIdentifierCharacter(value[afterUnit]))
            return true;
    }
    return false;
}

bool consumeNumericTokens(std::string_view value, size_t localLimit,
                          size_t totalLimit, size_t& total)
{
    size_t local = 0;
    for(size_t index = 0; index < value.size(); ++index) {
        if(!startsNumericToken(value, index))
            continue;
        if(!consumeCount(1, localLimit, local)
                || !consumeCount(1, totalLimit, total))
            return false;
    }
    return true;
}

struct ParserAllocationBudget {
    size_t xml_elements{0};
    size_t css_bytes{0};
    size_t css_rules{0};
    size_t css_declarations{0};
    size_t stylesheet_declarations{0};
    size_t css_selector_tokens{0};
    size_t path_tokens{0};
    size_t point_values{0};
    size_t dash_values{0};
};

bool consumeDashValuesFromCss(std::string_view css,
                              ParserAllocationBudget& budget)
{
    constexpr std::string_view PROPERTY = "stroke-dasharray";
    size_t offset = 0;
    while((offset = css.find(PROPERTY, offset)) != std::string_view::npos) {
        const auto colon = css.find(':', offset + PROPERTY.size());
        if(colon == std::string_view::npos)
            return true;
        auto end = css.find_first_of(";}", colon + 1);
        if(end == std::string_view::npos)
            end = css.size();
        if(!consumeNumericTokens(
                css.substr(colon + 1, end - colon - 1),
                MAX_DASH_VALUES, MAX_DASH_VALUES,
                budget.dash_values))
            return false;
        offset = end;
    }
    return true;
}

bool consumeCss(std::string_view css, bool inlineStyle,
                ParserAllocationBudget& budget)
{
    if(!consumeCount(css.size(), MAX_CSS_BYTES, budget.css_bytes))
        return false;
    size_t braceDepth = 0;
    char quote = 0;
    bool inComment = false;
    bool inSelectorIdentifier = false;
    bool selectorHasToken = false;
    bool pendingDescendantCombinator = false;
    auto consumeSelectorToken = [&]() {
        return consumeCount(
            1, MAX_CSS_SELECTOR_TOKENS,
            budget.css_selector_tokens);
    };
    for(size_t index = 0; index < css.size(); ++index) {
        const char value = css[index];
        if(inComment) {
            if(value == '*' && index + 1 < css.size()
                    && css[index + 1] == '/') {
                inComment = false;
                ++index;
            }
            continue;
        }
        if(quote != 0) {
            if(value == '\\' && index + 1 < css.size()) {
                ++index;
                continue;
            }
            if(value == quote)
                quote = 0;
            continue;
        }
        if(value == '/' && index + 1 < css.size()
                && css[index + 1] == '*') {
            inComment = true;
            ++index;
            continue;
        }
        if(value == '\'' || value == '"') {
            quote = value;
            continue;
        }
        if(value == '{') {
            if(!consumeCount(1, MAX_CSS_RULES, budget.css_rules)
                    || (!inlineStyle && !selectorHasToken))
                return false;
            ++braceDepth;
            inSelectorIdentifier = false;
            selectorHasToken = false;
            pendingDescendantCombinator = false;
            continue;
        }
        if(value == '}') {
            if(braceDepth > 0)
                --braceDepth;
            inSelectorIdentifier = false;
            selectorHasToken = false;
            pendingDescendantCombinator = false;
            continue;
        }
        if(!inlineStyle && braceDepth == 0) {
            if(isXmlSpace(value)) {
                pendingDescendantCombinator = selectorHasToken;
                inSelectorIdentifier = false;
                continue;
            }
            if(isCssIdentifierCharacter(value)) {
                if(!inSelectorIdentifier) {
                    if(pendingDescendantCombinator
                            && !consumeSelectorToken())
                        return false;
                    if(!consumeSelectorToken())
                        return false;
                }
                inSelectorIdentifier = true;
                selectorHasToken = true;
                pendingDescendantCombinator = false;
                continue;
            }
            inSelectorIdentifier = false;
            pendingDescendantCombinator = false;
            if(value == ',' || value == '.' || value == '#'
                    || value == ':' || value == '[' || value == ']'
                    || value == '*' || value == '>' || value == '+'
                    || value == '~' || value == '|') {
                if(!consumeSelectorToken())
                    return false;
                selectorHasToken = value != ',';
            }
            continue;
        }
        if(value == ':' && (inlineStyle || braceDepth > 0)) {
            if(!consumeCount(
                    1, MAX_CSS_DECLARATIONS,
                    budget.css_declarations))
                return false;
            if(!inlineStyle
                    && !consumeCount(
                        1, MAX_CSS_DECLARATIONS,
                        budget.stylesheet_declarations))
                return false;
        }
    }
    return consumeDashValuesFromCss(css, budget);
}

bool consumePathTokens(std::string_view path,
                       ParserAllocationBudget& budget)
{
    size_t local = 0;
    for(size_t index = 0; index < path.size(); ++index) {
        const auto value = static_cast<unsigned char>(path[index]);
        if(!std::isalpha(value) && !startsNumericToken(path, index))
            continue;
        if(!consumeCount(1, MAX_PATH_TOKENS_PER_ATTRIBUTE, local)
                || !consumeCount(
                    1, MAX_PATH_TOKENS, budget.path_tokens))
            return false;
    }
    return true;
}

std::string_view localXmlName(std::string_view name)
{
    const auto separator = name.rfind(':');
    return separator == std::string_view::npos
        ? name : name.substr(separator + 1);
}

struct XmlEndTagView {
    size_t start{std::string_view::npos};
    size_t end{std::string_view::npos};
};

bool findMatchingXmlEndTag(std::string_view svg, size_t offset,
                           std::string_view expectedName,
                           XmlEndTagView& endTag)
{
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
        if(!startsWith(remainder, "</")) {
            ++offset;
            continue;
        }
        size_t cursor = offset + 2;
        while(cursor < svg.size() && isXmlSpace(svg[cursor]))
            ++cursor;
        const size_t nameStart = cursor;
        while(cursor < svg.size() && !isXmlSpace(svg[cursor])
                && svg[cursor] != '>')
            ++cursor;
        const auto name = svg.substr(nameStart, cursor - nameStart);
        while(cursor < svg.size() && isXmlSpace(svg[cursor]))
            ++cursor;
        if(cursor >= svg.size())
            return false;
        if(svg[cursor] == '>' && name == expectedName) {
            endTag = {offset, cursor};
            return true;
        }
        offset = cursor + 1;
    }
    return false;
}

bool exceedsCssApplicationWork(const ParserAllocationBudget& budget)
{
    const auto exceedsProduct = [](size_t left, size_t right,
                                   size_t limit) {
        return left != 0 && right > limit / left;
    };
    return exceedsProduct(
               budget.xml_elements, budget.css_rules,
               MAX_CSS_RULE_MATCH_WORK)
        || exceedsProduct(
               budget.xml_elements, budget.css_selector_tokens,
               MAX_CSS_SELECTOR_MATCH_WORK)
        || exceedsProduct(
               budget.xml_elements, budget.stylesheet_declarations,
               MAX_CSS_DECLARATION_MATCH_WORK);
}

bool isFontRelativeLengthAttribute(std::string_view name)
{
    name = localXmlName(name);
    return name == "x" || name == "y" || name == "x1" || name == "y1"
        || name == "x2" || name == "y2" || name == "cx" || name == "cy"
        || name == "r" || name == "rx" || name == "ry"
        || name == "width" || name == "height" || name == "dx"
        || name == "dy" || name == "stroke-width"
        || name == "stroke-dasharray" || name == "stroke-dashoffset"
        || name == "font-size" || name == "letter-spacing"
        || name == "word-spacing";
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

bool hasUnsupportedFontRelativeLengths(std::string_view svg)
{
    size_t offset = 0;
    bool sawRootSvg = false;
    while((offset = svg.find('<', offset)) != std::string_view::npos) {
        if(startsWith(svg.substr(offset), "<!--")) {
            const auto end = svg.find("-->", offset + 4);
            if(end == std::string_view::npos)
                return false;
            offset = end + 3;
            continue;
        }
        if(startsWith(svg.substr(offset), "<![CDATA[")) {
            const auto end = svg.find("]]>", offset + 9);
            if(end == std::string_view::npos)
                return false;
            offset = end + 3;
            continue;
        }
        if(startsWith(svg.substr(offset), "<?")) {
            const auto end = svg.find("?>", offset + 2);
            if(end == std::string_view::npos)
                return false;
            offset = end + 2;
            continue;
        }
        if(startsWith(svg.substr(offset), "<!")) {
            const auto end = svg.find('>', offset + 2);
            if(end == std::string_view::npos)
                return false;
            offset = end + 1;
            continue;
        }
        if(offset + 1 < svg.size() && svg[offset + 1] == '/') {
            const auto end = svg.find('>', offset + 2);
            if(end == std::string_view::npos)
                return false;
            offset = end + 1;
            continue;
        }

        XmlStartTagView tag;
        if(!parseStartTag(svg, offset, tag))
            return false;
        if(localXmlName(tag.name) == "svg") {
            if(sawRootSvg)
                return false;
            sawRootSvg = true;
        }
        for(const auto& attribute : tag.attributes) {
            if((isFontRelativeLengthAttribute(attribute.name)
                    || localXmlName(attribute.name) == "style")
                    && containsFontRelativeLengthUnit(attribute.value))
                return true;
        }
        if(!tag.self_closing && localXmlName(tag.name) == "style") {
            XmlEndTagView close;
            if(!findMatchingXmlEndTag(
                    svg, tag.end + 1, tag.name, close))
                return false;
            if(containsFontRelativeLengthUnit(
                    svg.substr(
                        tag.end + 1,
                        close.start - tag.end - 1)))
                return true;
            offset = close.end + 1;
            continue;
        }
        offset = tag.end + 1;
    }
    return false;
}

bool exceedsParserAllocationBudgets(std::string_view svg)
{
    ParserAllocationBudget budget;
    size_t offset = 0;
    while((offset = svg.find('<', offset)) != std::string_view::npos) {
        if(startsWith(svg.substr(offset), "<!--")) {
            const auto end = svg.find("-->", offset + 4);
            if(end == std::string_view::npos)
                return false;
            offset = end + 3;
            continue;
        }
        if(startsWith(svg.substr(offset), "<![CDATA[")) {
            const auto end = svg.find("]]>", offset + 9);
            if(end == std::string_view::npos)
                return false;
            offset = end + 3;
            continue;
        }
        if(startsWith(svg.substr(offset), "<?")) {
            const auto end = svg.find("?>", offset + 2);
            if(end == std::string_view::npos)
                return false;
            offset = end + 2;
            continue;
        }
        if(startsWith(svg.substr(offset), "<!")) {
            const auto end = svg.find('>', offset + 2);
            if(end == std::string_view::npos)
                return false;
            offset = end + 1;
            continue;
        }
        if(offset + 1 < svg.size() && svg[offset + 1] == '/') {
            const auto end = svg.find('>', offset + 2);
            if(end == std::string_view::npos)
                return false;
            offset = end + 1;
            continue;
        }

        XmlStartTagView tag;
        if(!parseStartTag(svg, offset, tag))
            return false;
        if(tag.attribute_limit_exceeded)
            return true;
        if(!consumeCount(
                1, MAX_XML_ELEMENTS, budget.xml_elements))
            return true;
        for(const auto& attribute : tag.attributes) {
            if(attribute.name == "d") {
                if(!consumePathTokens(attribute.value, budget))
                    return true;
            } else if(attribute.name == "points") {
                if(!consumeNumericTokens(
                        attribute.value, MAX_POINT_VALUES_PER_ATTRIBUTE,
                        MAX_POINT_VALUES, budget.point_values))
                    return true;
            } else if(attribute.name == "stroke-dasharray") {
                if(!consumeNumericTokens(
                        attribute.value, MAX_DASH_VALUES,
                        MAX_DASH_VALUES, budget.dash_values))
                    return true;
            } else if(attribute.name == "style") {
                if(!consumeCss(attribute.value, true, budget))
                    return true;
            }
        }

        if(!tag.self_closing && localXmlName(tag.name) == "style") {
            XmlEndTagView close;
            if(!findMatchingXmlEndTag(
                    svg, tag.end + 1, tag.name, close))
                return true;
            if(!consumeCss(
                    svg.substr(
                        tag.end + 1,
                        close.start - tag.end - 1),
                    false, budget))
                return true;
            offset = close.end + 1;
            continue;
        }
        offset = tag.end + 1;
    }
    return exceedsCssApplicationWork(budget);
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

NamespaceValidation validateNamespaceBindings(std::string_view svg)
{
    constexpr std::string_view XML_NAMESPACE =
        "http://www.w3.org/XML/1998/namespace";
    constexpr std::string_view SVG_NAMESPACE =
        "http://www.w3.org/2000/svg";
    constexpr std::string_view XLINK_NAMESPACE =
        "http://www.w3.org/1999/xlink";
    auto prefixIsBound = [](std::string_view prefix, bool xlinkBound) {
        return prefix == "xml" || (prefix == "xlink" && xlinkBound);
    };
    std::vector<bool> inheritedXlinkBindings;
    std::vector<std::string_view> openElementNames;
    bool xlinkBound = false;
    bool unsupportedNamespaceSeen = false;
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
            const auto prefix = qNamePrefix(
                svg.substr(nameStart, cursor - nameStart));
            const auto closingName = svg.substr(
                nameStart, cursor - nameStart);
            const auto closingNameValidation = validateXmlName(closingName);
            if(closingNameValidation == XmlNameValidation::Invalid)
                return NamespaceValidation::Invalid;
            if(closingNameValidation == XmlNameValidation::NonAscii)
                return NamespaceValidation::UnsupportedXmlName;
            if(!prefix.has_value())
                return NamespaceValidation::Invalid;
            if(!prefix->empty()
                    && !prefixIsBound(*prefix, xlinkBound)
                    && !unsupportedNamespaceSeen)
                return NamespaceValidation::Invalid;
            if(openElementNames.empty()
                    || openElementNames.back() != closingName)
                return NamespaceValidation::Invalid;
            const auto end = svg.find('>', cursor);
            if(end == std::string_view::npos)
                return NamespaceValidation::Supported;
            openElementNames.pop_back();
            if(!inheritedXlinkBindings.empty()) {
                xlinkBound = inheritedXlinkBindings.back();
                inheritedXlinkBindings.pop_back();
            }
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
        const bool inheritedXlinkBound = xlinkBound;
        for(const auto& attribute : tag.attributes) {
            if(attribute.name == "xmlns") {
                if(attribute.value != SVG_NAMESPACE)
                    unsupportedNamespaceSeen = true;
                continue;
            }
            if(!startsWith(attribute.name, "xmlns:"))
                continue;
            const auto declaredPrefix = attribute.name.substr(6);
            if(declaredPrefix.empty()
                    || declaredPrefix.find(':') != std::string_view::npos)
                return NamespaceValidation::Invalid;
            if(declaredPrefix == "xml") {
                if(attribute.value != XML_NAMESPACE)
                    unsupportedNamespaceSeen = true;
            } else if(declaredPrefix == "xlink") {
                if(attribute.value != XLINK_NAMESPACE)
                    unsupportedNamespaceSeen = true;
                else
                    xlinkBound = true;
            } else if(declaredPrefix == "xmlns"
                    || attribute.value.empty()) {
                return NamespaceValidation::Invalid;
            } else {
                unsupportedNamespaceSeen = true;
            }
        }

        const auto elementPrefix = qNamePrefix(tag.name);
        if(!elementPrefix.has_value())
            return NamespaceValidation::Invalid;
        if(!elementPrefix->empty()
                && !prefixIsBound(*elementPrefix, xlinkBound)
                && !unsupportedNamespaceSeen)
            return NamespaceValidation::Invalid;
        for(const auto& attribute : tag.attributes) {
            if(attribute.name == "xmlns"
                    || startsWith(attribute.name, "xmlns:"))
                continue;
            const auto attributePrefix = qNamePrefix(attribute.name);
            if(!attributePrefix.has_value())
                return NamespaceValidation::Invalid;
            if(!attributePrefix->empty()
                    && !prefixIsBound(*attributePrefix, xlinkBound)
                    && !unsupportedNamespaceSeen)
                return NamespaceValidation::Invalid;
        }
        if(tag.self_closing) {
            xlinkBound = inheritedXlinkBound;
        } else {
            inheritedXlinkBindings.push_back(inheritedXlinkBound);
            openElementNames.push_back(tag.name);
        }
        offset = tag.end + 1;
    }
    return unsupportedNamespaceSeen
        ? NamespaceValidation::Unsupported
        : NamespaceValidation::Supported;
}

bool exceedsXmlComplexity(std::string_view svg)
{
    if(svg.size() > MAX_SVG_BYTES)
        return true;

    size_t elementCount = 0;
    size_t useElementCount = 0;
    size_t depth = 0;
    size_t offset = 0;
    while((offset = svg.find('<', offset)) != std::string_view::npos) {
        if(startsWith(svg.substr(offset), "<!--")) {
            const auto end = svg.find("-->", offset + 4);
            if(end == std::string_view::npos)
                return false;
            offset = end + 3;
            continue;
        }
        if(startsWith(svg.substr(offset), "<![CDATA[")) {
            const auto end = svg.find("]]>", offset + 9);
            if(end == std::string_view::npos)
                return false;
            offset = end + 3;
            continue;
        }
        if(startsWith(svg.substr(offset), "<?")) {
            const auto end = svg.find("?>", offset + 2);
            if(end == std::string_view::npos)
                return false;
            offset = end + 2;
            continue;
        }
        if(startsWith(svg.substr(offset), "<!")) {
            const auto end = svg.find('>', offset + 2);
            if(end == std::string_view::npos)
                return false;
            offset = end + 1;
            continue;
        }

        size_t cursor = offset + 1;
        const bool closing = cursor < svg.size() && svg[cursor] == '/';
        if(closing)
            ++cursor;
        while(cursor < svg.size() && isXmlSpace(svg[cursor]))
            ++cursor;
        const size_t nameStart = cursor;
        while(cursor < svg.size()
                && !isXmlSpace(svg[cursor])
                && svg[cursor] != '/' && svg[cursor] != '>')
            ++cursor;
        auto localName = svg.substr(nameStart, cursor - nameStart);
        const auto namespaceSeparator = localName.rfind(':');
        if(namespaceSeparator != std::string_view::npos)
            localName.remove_prefix(namespaceSeparator + 1);
        char quote = 0;
        size_t tagEnd = std::string_view::npos;
        for(; cursor < svg.size(); ++cursor) {
            const char value = svg[cursor];
            if(quote != 0) {
                if(value == quote)
                    quote = 0;
                continue;
            }
            if(value == '\'' || value == '"') {
                quote = value;
                continue;
            }
            if(value == '>') {
                tagEnd = cursor;
                break;
            }
        }
        if(tagEnd == std::string_view::npos)
            return false;

        if(closing) {
            if(depth > 0)
                --depth;
        } else {
            if(++elementCount > MAX_XML_ELEMENTS)
                return true;
            if(localName == "use" && ++useElementCount > MAX_USE_ELEMENTS)
                return true;
            size_t last = tagEnd;
            while(last > offset && isXmlSpace(svg[last - 1]))
                --last;
            const bool selfClosing = last > offset && svg[last - 1] == '/';
            if(!selfClosing && ++depth > MAX_XML_DEPTH)
                return true;
        }
        offset = tagEnd + 1;
    }
    return false;
}

RecorderResult recordUtf8Svg(std::string_view svg)
{
    if(hasUnsupportedXmlEncoding(svg))
        return unsupportedXmlEncoding();
    if(hasDoctypeDeclaration(svg))
        return unsupportedDoctype();
    if(exceedsXmlComplexity(svg))
        return unsupportedComplexity();
    if(exceedsParserAllocationBudgets(svg))
        return unsupportedComplexity();
    if(hasUnsupportedFontRelativeLengths(svg))
        return unsupportedFontRelativeLength();
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
    return finishRecording(lunasvg::Document::loadFromData(std::string(svg)));
}

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
    std::error_code fileSizeError;
    const auto fileSize = std::filesystem::file_size(
        filename, fileSizeError);
    if(!fileSizeError && fileSize > MAX_SVG_BYTES)
        return unsupportedComplexity();

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
        if(byteCount > MAX_SVG_BYTES - svg.size())
            return unsupportedComplexity();
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
