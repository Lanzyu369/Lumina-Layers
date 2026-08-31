#ifndef LUMINA_SVG_CORE_COMPLEXITY_BUDGET_H
#define LUMINA_SVG_CORE_COMPLEXITY_BUDGET_H

#include <cstddef>
#include <limits>
#include <stdexcept>
#include <string>

namespace lumina_svg_core {

class ComplexityLimitError : public std::runtime_error {
public:
    explicit ComplexityLimitError(
        const char* budget = "unspecified")
        : std::runtime_error(budget)
    {}

    explicit ComplexityLimitError(std::string budget)
        : std::runtime_error(std::move(budget))
    {}
};

class ComplexityBudget {
public:
    static constexpr size_t MAX_GENERATED_POINTS = 4'000'000;
    static constexpr size_t MAX_GENERATED_RINGS = 250'000;
    static constexpr size_t MAX_TOPOLOGY_SEGMENTS = 1'000'000;
    static constexpr size_t MAX_BOOLEAN_INPUT_POINTS = 8'000'000;
    static constexpr size_t MAX_OVERLAP_PAIRS = 50'000;
    static constexpr size_t MAX_RESULT_POINTS = 4'000'000;
    static constexpr size_t MAX_CLIPPER_INDEX_SEGMENTS = 1'000'000;
    static constexpr size_t MAX_CLIPPER_INTERSECTION_CANDIDATES = 20'000'000;
    static constexpr size_t MAX_CLIPPER_OUTPUT_POINTS = 16'000'000;
    static constexpr size_t MAX_CLIPPER_OUTPUT_RINGS = 1'000'000;

    void consumeGeneratedPoints(size_t count = 1)
    {
        consume(
            m_generatedPoints, count, MAX_GENERATED_POINTS,
            "generated_points");
    }

    void ensureGeneratedPointCapacity(size_t count) const
    {
        ensure(
            m_generatedPoints, count, MAX_GENERATED_POINTS,
            "generated_points");
    }

    void consumeGeneratedRings(size_t count = 1)
    {
        consume(
            m_generatedRings, count, MAX_GENERATED_RINGS,
            "generated_rings");
    }

    void consumeTopologySegments(size_t count)
    {
        consume(
            m_topologySegments, count, MAX_TOPOLOGY_SEGMENTS,
            "topology_segments");
    }

    void consumeBooleanInputPoints(size_t count)
    {
        consume(
            m_booleanInputPoints, count, MAX_BOOLEAN_INPUT_POINTS,
            "boolean_input_points");
    }

    void consumeOverlapPairs(size_t count)
    {
        consume(
            m_overlapPairs, count, MAX_OVERLAP_PAIRS,
            "overlap_pairs");
    }

    void consumeResultPoints(size_t count)
    {
        consume(
            m_resultPoints, count, MAX_RESULT_POINTS,
            "result_points");
    }

    void ensureClipperIndexSegmentCapacity(size_t count) const
    {
        if(count > MAX_CLIPPER_INDEX_SEGMENTS)
            throw ComplexityLimitError("clipper_index_segments");
    }

    void consumeClipperIntersectionCandidates(size_t count = 1)
    {
        consume(
            m_clipperIntersectionCandidates, count,
            MAX_CLIPPER_INTERSECTION_CANDIDATES,
            "clipper_intersection_candidates");
    }

    void consumeClipperOutputPoints(size_t count)
    {
        consume(
            m_clipperOutputPoints, count,
            MAX_CLIPPER_OUTPUT_POINTS,
            "clipper_output_points");
    }

    void consumeClipperOutputRings(size_t count)
    {
        consume(
            m_clipperOutputRings, count,
            MAX_CLIPPER_OUTPUT_RINGS,
            "clipper_output_rings");
    }

private:
    static void ensure(size_t current, size_t count, size_t limit,
                       const char* budget)
    {
        if(count > limit || current > limit - count)
            throw ComplexityLimitError(budget);
    }

    static void consume(size_t& current, size_t count, size_t limit,
                        const char* budget)
    {
        ensure(current, count, limit, budget);
        current += count;
    }

    size_t m_generatedPoints{0};
    size_t m_generatedRings{0};
    size_t m_topologySegments{0};
    size_t m_booleanInputPoints{0};
    size_t m_overlapPairs{0};
    size_t m_resultPoints{0};
    size_t m_clipperIntersectionCandidates{0};
    size_t m_clipperOutputPoints{0};
    size_t m_clipperOutputRings{0};
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
