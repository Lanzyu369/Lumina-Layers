#ifndef LUMINA_SVG_CORE_COMPLEXITY_BUDGET_H
#define LUMINA_SVG_CORE_COMPLEXITY_BUDGET_H

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

// Tracks actual geometry work only to catch size_t overflow. It does not
// impose an input, memory, or execution budget and is never an admission gate.
class ComplexityBudget {
public:
    void consumeGeneratedPoints(size_t count = 1)
    {
        consume(m_generatedPoints, count, "generated_points");
    }

    void ensureGeneratedPointCapacity(size_t count) const
    {
        ensure(m_generatedPoints, count);
    }

    void consumeGeneratedRings(size_t count = 1)
    {
        consume(m_generatedRings, count, "generated_rings");
    }

    void consumeBooleanInputPoints(size_t count)
    {
        consume(m_booleanInputPoints, count, "boolean_input_points");
    }

    void consumeResultPoints(size_t count)
    {
        consume(m_resultPoints, count, "result_points");
    }

    void consumeClipperOutputPoints(size_t count)
    {
        consume(m_clipperOutputPoints, count, "clipper_output_points");
    }

    void consumeClipperOutputRings(size_t count)
    {
        consume(m_clipperOutputRings, count, "clipper_output_rings");
    }

    void consumeCompositorBoundsCandidates(size_t count = 1)
    {
        consume(m_compositorBoundsCandidates, count,
                "compositor_bounds_candidates");
    }

    void consumeStrokeSimplificationComparisons(size_t count = 1)
    {
        consume(m_strokeSimplificationComparisons, count,
                "stroke_simplification_comparisons");
    }

    void mergeFrom(const ComplexityBudget& other)
    {
        mergeCounter(m_generatedPoints, other.m_generatedPoints);
        mergeCounter(m_generatedRings, other.m_generatedRings);
        mergeCounter(m_booleanInputPoints, other.m_booleanInputPoints);
        mergeCounter(m_resultPoints, other.m_resultPoints);
        mergeCounter(m_clipperOutputPoints, other.m_clipperOutputPoints);
        mergeCounter(m_clipperOutputRings, other.m_clipperOutputRings);
        mergeCounter(
            m_compositorBoundsCandidates, other.m_compositorBoundsCandidates);
        mergeCounter(
            m_strokeSimplificationComparisons,
            other.m_strokeSimplificationComparisons);
    }

private:
    static void ensure(size_t current, size_t count)
    {
        if(count > std::numeric_limits<size_t>::max() - current)
            throw ComplexityLimitError("counter_overflow");
    }

    static void consume(size_t& current, size_t count, const char* reason)
    {
        ensure(current, count);
        current += count;
        (void)reason;
    }

    static void mergeCounter(size_t& current, size_t additional)
    {
        ensure(current, additional);
        current += additional;
    }

    size_t m_generatedPoints{0};
    size_t m_generatedRings{0};
    size_t m_booleanInputPoints{0};
    size_t m_resultPoints{0};
    size_t m_clipperOutputPoints{0};
    size_t m_clipperOutputRings{0};
    size_t m_compositorBoundsCandidates{0};
    size_t m_strokeSimplificationComparisons{0};
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

#endif // LUMINA_SVG_CORE_COMPLEXITY_BUDGET_H
