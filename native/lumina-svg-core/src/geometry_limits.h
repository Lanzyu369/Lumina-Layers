#ifndef LUMINA_SVG_CORE_GEOMETRY_LIMITS_H
#define LUMINA_SVG_CORE_GEOMETRY_LIMITS_H

#include <cstddef>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>

namespace lumina_svg_core {

class ComplexityLimitError : public std::runtime_error {
public:
    explicit ComplexityLimitError(const char* reason = "counter_overflow")
        : std::runtime_error(reason) {}

    explicit ComplexityLimitError(std::string reason)
        : std::runtime_error(std::move(reason)) {}
};

inline size_t checkedSizeProduct(size_t left, size_t right)
{
    if(left != 0 && right > std::numeric_limits<size_t>::max() / left)
        throw ComplexityLimitError("size_product_overflow");
    return left * right;
}

inline size_t checkedSizeSum(size_t left, size_t right)
{
    if(right > std::numeric_limits<size_t>::max() - left)
        throw ComplexityLimitError("size_sum_overflow");
    return left + right;
}

} // namespace lumina_svg_core

#endif // LUMINA_SVG_CORE_GEOMETRY_LIMITS_H
