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
    static constexpr size_t MAX_GENERATED_POINTS = 64'000'000;
    static constexpr size_t MAX_GENERATED_RINGS = 1'000'000;
    static constexpr size_t MAX_BOOLEAN_INPUT_POINTS_PER_OPERATION =
        16'000'000;
    static constexpr size_t MAX_BOOLEAN_INPUT_POINTS_PER_DOCUMENT =
        256'000'000;
    static constexpr size_t MAX_TRANSIENT_POINTS_PER_OPERATION = 16'000'000;
    static constexpr size_t MAX_RESULT_POINTS = 16'000'000;
    static constexpr size_t MAX_RETAINED_GEOMETRY_POINTS = 16'000'000;
    static constexpr size_t MAX_RETAINED_GEOMETRY_RINGS = 1'000'000;
    static constexpr size_t MAX_CLIPPER_INDEX_SEGMENTS = 4'000'000;
    static constexpr size_t MAX_CLIPPER_INTERSECTION_CANDIDATES = 100'000'000;
    static constexpr size_t MAX_CLIPPER_INTERSECTION_COMPARISONS =
        256'000'000;
    static constexpr size_t MAX_CLIPPER_INTERSECTION_CANDIDATES_PER_DOCUMENT =
        100'000'000;
    static constexpr size_t MAX_CLIPPER_INTERSECTION_COMPARISONS_PER_DOCUMENT =
        512'000'000;
    static constexpr size_t MAX_CLIPPER_OUTPUT_POINTS = 16'000'000;
    static constexpr size_t MAX_CLIPPER_OUTPUT_RINGS = 1'000'000;
    static constexpr size_t MAX_CLIPPER_OUTPUT_POINTS_PER_DOCUMENT =
        256'000'000;
    static constexpr size_t MAX_CLIPPER_OUTPUT_RINGS_PER_DOCUMENT =
        16'000'000;
    static constexpr size_t MAX_COMPOSITOR_BOUNDS_CANDIDATES = 100'000'000;
    static constexpr size_t MAX_STROKE_SIMPLIFICATION_COMPARISONS =
        50'000'000;

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

    void requireBooleanInputPointCapacity(size_t count) const
    {
        ensure(
            0, count, MAX_BOOLEAN_INPUT_POINTS_PER_OPERATION,
            "boolean_input_points");
    }

    void consumeBooleanInputPoints(size_t count)
    {
        requireBooleanInputPointCapacity(count);
        consume(
            m_booleanInputPoints, count,
            MAX_BOOLEAN_INPUT_POINTS_PER_DOCUMENT,
            "boolean_input_points_document");
    }

    void requireTransientPointCapacity(size_t count) const
    {
        ensure(
            0, count, MAX_TRANSIENT_POINTS_PER_OPERATION,
            "transient_points");
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

    void requireClipperIntersectionCandidateCapacity(size_t count) const
    {
        ensure(
            0, count,
            MAX_CLIPPER_INTERSECTION_CANDIDATES,
            "clipper_intersection_candidates");
    }

    void requireClipperIntersectionWorkCapacity(size_t count) const
    {
        ensure(
            0, count,
            MAX_CLIPPER_INTERSECTION_COMPARISONS,
            "clipper_intersection_comparisons");
    }

    void consumeClipperIntersectionCandidates(size_t count)
    {
        requireClipperIntersectionCandidateCapacity(count);
        consume(
            m_clipperIntersectionCandidates, count,
            MAX_CLIPPER_INTERSECTION_CANDIDATES_PER_DOCUMENT,
            "clipper_intersection_candidates_document");
    }

    void consumeClipperIntersectionWork(size_t count)
    {
        requireClipperIntersectionWorkCapacity(count);
        consume(
            m_clipperIntersectionComparisons, count,
            MAX_CLIPPER_INTERSECTION_COMPARISONS_PER_DOCUMENT,
            "clipper_intersection_comparisons_document");
    }

    void requireClipperOutputPointCapacity(size_t count) const
    {
        ensure(
            0, count,
            MAX_CLIPPER_OUTPUT_POINTS,
            "clipper_output_points");
    }

    void requireClipperOutputRingCapacity(size_t count) const
    {
        ensure(
            0, count, MAX_CLIPPER_OUTPUT_RINGS,
            "clipper_output_rings");
    }

    void requireClipperOutputDocumentCapacity(
        size_t pointCount, size_t ringCount) const
    {
        requireClipperOutputPointCapacity(pointCount);
        requireClipperOutputRingCapacity(ringCount);
        ensure(
            m_clipperOutputPoints, pointCount,
            MAX_CLIPPER_OUTPUT_POINTS_PER_DOCUMENT,
            "clipper_output_points_document");
        ensure(
            m_clipperOutputRings, ringCount,
            MAX_CLIPPER_OUTPUT_RINGS_PER_DOCUMENT,
            "clipper_output_rings_document");
    }

    void consumeClipperOutputPoints(size_t count)
    {
        requireClipperOutputPointCapacity(count);
        consume(
            m_clipperOutputPoints, count,
            MAX_CLIPPER_OUTPUT_POINTS_PER_DOCUMENT,
            "clipper_output_points_document");
    }

    void consumeClipperOutputRings(size_t count)
    {
        requireClipperOutputRingCapacity(count);
        consume(
            m_clipperOutputRings, count,
            MAX_CLIPPER_OUTPUT_RINGS_PER_DOCUMENT,
            "clipper_output_rings_document");
    }

    void consumeCompositorBoundsCandidates(size_t count = 1)
    {
        consume(
            m_compositorBoundsCandidates, count,
            MAX_COMPOSITOR_BOUNDS_CANDIDATES,
            "compositor_bounds_candidates");
    }

    void consumeStrokeSimplificationComparisons(size_t count = 1)
    {
        consume(
            m_strokeSimplificationComparisons, count,
            MAX_STROKE_SIMPLIFICATION_COMPARISONS,
            "stroke_simplification_comparisons");
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
    size_t m_booleanInputPoints{0};
    size_t m_resultPoints{0};
    size_t m_clipperIntersectionCandidates{0};
    size_t m_clipperIntersectionComparisons{0};
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
