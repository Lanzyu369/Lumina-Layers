#ifndef LUMINA_SVG_CORE_COMPLEXITY_BUDGET_H
#define LUMINA_SVG_CORE_COMPLEXITY_BUDGET_H

#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <limits>
#include <stdexcept>
#include <string>

namespace Clipper2Lib {
class ClipperExecutionGate;
}

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

enum class ComplexityCounter : size_t {
    GeneratedPoints,
    GeneratedRings,
    BooleanInputPoints,
    ResultPoints,
    ClipperIntersectionCandidates,
    ClipperIntersectionComparisons,
    ClipperEnginePointAllocations,
    ClipperEngineRecordAllocations,
    ClipperEngineIntersectionNodeAllocations,
    ClipperEngineProcessedIntersectionEvents,
    ClipperOutputPoints,
    ClipperOutputRings,
    CompositorBoundsCandidates,
    StrokeSimplificationComparisons,
    BooleanInputPointsInFlight,
    TransientPointsInFlight,
    ClipperIndexSegmentsInFlight,
    Count,
};

class ParallelComplexityGate {
public:
    void seed(ComplexityCounter counter, size_t value)
    {
        m_counters[index(counter)].store(value, std::memory_order_relaxed);
    }

    size_t reserve(ComplexityCounter counter, size_t minimum,
                   size_t preferred, size_t limit, const char* budget)
    {
        if(m_exceeded.load(std::memory_order_acquire))
            throw ComplexityLimitError(budget);
        auto& value = m_counters[index(counter)];
        size_t current = value.load(std::memory_order_relaxed);
        while(true) {
            if(minimum > limit || current > limit - minimum) {
                m_exceeded.store(true, std::memory_order_release);
                throw ComplexityLimitError(budget);
            }
            const size_t reserved = std::min(preferred, limit - current);
            if(value.compare_exchange_weak(
                    current, current + reserved,
                    std::memory_order_relaxed,
                    std::memory_order_relaxed))
                return reserved;
        }
    }

    void release(ComplexityCounter counter, size_t count)
    {
        if(count == 0)
            return;
        m_counters[index(counter)].fetch_sub(
            count, std::memory_order_relaxed);
    }

    bool exceeded() const
    {
        return m_exceeded.load(std::memory_order_acquire);
    }

private:
    static constexpr size_t index(ComplexityCounter counter)
    {
        return static_cast<size_t>(counter);
    }

    std::array<std::atomic<size_t>,
               static_cast<size_t>(ComplexityCounter::Count)> m_counters{};
    std::atomic<bool> m_exceeded{false};
};

class ParallelComplexityReservation {
public:
    ParallelComplexityReservation() = default;

    ParallelComplexityReservation(ParallelComplexityGate* gate,
                                  ComplexityCounter counter,
                                  size_t count)
        : m_gate(gate), m_counter(counter), m_count(count)
    {}

    ParallelComplexityReservation(
        const ParallelComplexityReservation&) = delete;
    ParallelComplexityReservation& operator=(
        const ParallelComplexityReservation&) = delete;

    ParallelComplexityReservation(
        ParallelComplexityReservation&& other) noexcept
        : m_gate(other.m_gate),
          m_counter(other.m_counter),
          m_count(other.m_count)
    {
        other.m_gate = nullptr;
        other.m_count = 0;
    }

    ParallelComplexityReservation& operator=(
        ParallelComplexityReservation&& other) noexcept
    {
        if(this == &other)
            return *this;
        release();
        m_gate = other.m_gate;
        m_counter = other.m_counter;
        m_count = other.m_count;
        other.m_gate = nullptr;
        other.m_count = 0;
        return *this;
    }

    ~ParallelComplexityReservation()
    {
        release();
    }

private:
    void release()
    {
        if(m_gate != nullptr && m_count > 0)
            m_gate->release(m_counter, m_count);
        m_gate = nullptr;
        m_count = 0;
    }

    ParallelComplexityGate* m_gate{nullptr};
    ComplexityCounter m_counter{ComplexityCounter::GeneratedPoints};
    size_t m_count{0};
};

class ComplexityBudget {
public:
    static constexpr size_t MAX_GENERATED_POINTS = 64'000'000;
    static constexpr size_t MAX_GENERATED_RINGS = 1'000'000;
    static constexpr size_t MAX_BOOLEAN_INPUT_POINTS_PER_OPERATION =
        16'000'000;
    static constexpr size_t MAX_BOOLEAN_INPUT_POINTS_PER_DOCUMENT =
        2'000'000'000;
    static constexpr size_t MAX_TRANSIENT_POINTS_PER_OPERATION = 16'000'000;
    static constexpr size_t MAX_RESULT_POINTS = 16'000'000;
    static constexpr size_t MAX_RETAINED_GEOMETRY_POINTS = 16'000'000;
    static constexpr size_t MAX_RETAINED_GEOMETRY_RINGS = 1'000'000;
    static constexpr size_t MAX_CLIPPER_INDEX_SEGMENTS = 4'000'000;
    static constexpr size_t MAX_CLIPPER_INTERSECTION_CANDIDATES = 100'000'000;
    static constexpr size_t MAX_CLIPPER_INTERSECTION_COMPARISONS =
        256'000'000;
    static constexpr size_t MAX_CLIPPER_INTERSECTION_CANDIDATES_PER_DOCUMENT =
        400'000'000;
    static constexpr size_t MAX_CLIPPER_INTERSECTION_COMPARISONS_PER_DOCUMENT =
        1'000'000'000;
    static constexpr size_t MAX_CLIPPER_ENGINE_POINT_ALLOCATIONS_PER_DOCUMENT =
        1'000'000'000;
    static constexpr size_t MAX_CLIPPER_ENGINE_RECORD_ALLOCATIONS_PER_DOCUMENT =
        64'000'000;
    static constexpr size_t
        MAX_CLIPPER_ENGINE_INTERSECTION_NODE_ALLOCATIONS_PER_DOCUMENT =
            100'000'000;
    static constexpr size_t
        MAX_CLIPPER_ENGINE_PROCESSED_INTERSECTION_EVENTS_PER_DOCUMENT =
            100'000'000;
    static constexpr size_t MAX_CLIPPER_OUTPUT_POINTS = 16'000'000;
    static constexpr size_t MAX_CLIPPER_OUTPUT_RINGS = 1'000'000;
    static constexpr size_t MAX_CLIPPER_OUTPUT_POINTS_PER_DOCUMENT =
        1'000'000'000;
    static constexpr size_t MAX_CLIPPER_OUTPUT_RINGS_PER_DOCUMENT =
        64'000'000;
    static constexpr size_t MAX_COMPOSITOR_BOUNDS_CANDIDATES = 100'000'000;
    static constexpr size_t MAX_STROKE_SIMPLIFICATION_COMPARISONS =
        50'000'000;

    void attachParallelGate(ParallelComplexityGate* gate)
    {
        m_parallelGate = gate;
    }

    void attachClipperExecutionGate(Clipper2Lib::ClipperExecutionGate* gate)
    {
        m_clipperExecutionGate = gate;
    }

    Clipper2Lib::ClipperExecutionGate* clipperExecutionGate() const
    {
        return m_clipperExecutionGate;
    }

    void seedParallelGate(ParallelComplexityGate& gate) const
    {
        gate.seed(ComplexityCounter::GeneratedPoints, m_generatedPoints);
        gate.seed(ComplexityCounter::GeneratedRings, m_generatedRings);
        gate.seed(
            ComplexityCounter::BooleanInputPoints, m_booleanInputPoints);
        gate.seed(ComplexityCounter::ResultPoints, m_resultPoints);
        gate.seed(
            ComplexityCounter::ClipperIntersectionCandidates,
            m_clipperIntersectionCandidates);
        gate.seed(
            ComplexityCounter::ClipperIntersectionComparisons,
            m_clipperIntersectionComparisons);
        gate.seed(
            ComplexityCounter::ClipperEnginePointAllocations,
            m_clipperEnginePointAllocations);
        gate.seed(
            ComplexityCounter::ClipperEngineRecordAllocations,
            m_clipperEngineRecordAllocations);
        gate.seed(
            ComplexityCounter::ClipperEngineIntersectionNodeAllocations,
            m_clipperEngineIntersectionNodeAllocations);
        gate.seed(
            ComplexityCounter::ClipperEngineProcessedIntersectionEvents,
            m_clipperEngineProcessedIntersectionEvents);
        gate.seed(
            ComplexityCounter::ClipperOutputPoints, m_clipperOutputPoints);
        gate.seed(
            ComplexityCounter::ClipperOutputRings, m_clipperOutputRings);
        gate.seed(
            ComplexityCounter::CompositorBoundsCandidates,
            m_compositorBoundsCandidates);
        gate.seed(
            ComplexityCounter::StrokeSimplificationComparisons,
            m_strokeSimplificationComparisons);
    }

    void releaseParallelReservations()
    {
        if(m_parallelGate == nullptr)
            return;
        for(size_t index = 0; index < m_parallelReservations.size(); ++index) {
            const size_t reserved = m_parallelReservations[index];
            if(reserved == 0)
                continue;
            m_parallelGate->release(
                static_cast<ComplexityCounter>(index), reserved);
            m_parallelReservations[index] = 0;
        }
    }

    void consumeGeneratedPoints(size_t count = 1)
    {
        consume(
            m_generatedPoints, count, MAX_GENERATED_POINTS,
            "generated_points", ComplexityCounter::GeneratedPoints);
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
            "generated_rings", ComplexityCounter::GeneratedRings);
    }

    void requireBooleanInputPointCapacity(size_t count) const
    {
        ensure(
            0, count, MAX_BOOLEAN_INPUT_POINTS_PER_OPERATION,
            "boolean_input_points");
    }

    ParallelComplexityReservation reserveBooleanInputPoints(size_t count)
    {
        requireBooleanInputPointCapacity(count);
        return reserveParallelInFlight(
            ComplexityCounter::BooleanInputPointsInFlight, count,
            MAX_BOOLEAN_INPUT_POINTS_PER_OPERATION,
            "parallel_boolean_input_points");
    }

    void consumeBooleanInputPoints(size_t count)
    {
        requireBooleanInputPointCapacity(count);
        consume(
            m_booleanInputPoints, count,
            MAX_BOOLEAN_INPUT_POINTS_PER_DOCUMENT,
            "boolean_input_points_document",
            ComplexityCounter::BooleanInputPoints);
    }

    void requireTransientPointCapacity(size_t count) const
    {
        ensure(
            0, count, MAX_TRANSIENT_POINTS_PER_OPERATION,
            "transient_points");
    }

    ParallelComplexityReservation reserveTransientPoints(size_t count)
    {
        requireTransientPointCapacity(count);
        return reserveParallelInFlight(
            ComplexityCounter::TransientPointsInFlight, count,
            MAX_TRANSIENT_POINTS_PER_OPERATION,
            "parallel_transient_points");
    }

    void consumeResultPoints(size_t count)
    {
        consume(
            m_resultPoints, count, MAX_RESULT_POINTS,
            "result_points", ComplexityCounter::ResultPoints);
    }

    void ensureClipperIndexSegmentCapacity(size_t count) const
    {
        if(count > MAX_CLIPPER_INDEX_SEGMENTS)
            throw ComplexityLimitError("clipper_index_segments");
    }

    ParallelComplexityReservation reserveClipperIndexSegments(size_t count)
    {
        ensureClipperIndexSegmentCapacity(count);
        return reserveParallelInFlight(
            ComplexityCounter::ClipperIndexSegmentsInFlight, count,
            MAX_CLIPPER_INDEX_SEGMENTS,
            "parallel_clipper_index_segments");
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
            "clipper_intersection_candidates_document",
            ComplexityCounter::ClipperIntersectionCandidates);
    }

    void consumeClipperIntersectionWork(size_t count)
    {
        requireClipperIntersectionWorkCapacity(count);
        consume(
            m_clipperIntersectionComparisons, count,
            MAX_CLIPPER_INTERSECTION_COMPARISONS_PER_DOCUMENT,
            "clipper_intersection_comparisons_document",
            ComplexityCounter::ClipperIntersectionComparisons);
    }

    void consumeClipperEngineWork(size_t pointAllocations,
                                  size_t recordAllocations,
                                  size_t intersectionNodeAllocations,
                                  size_t processedIntersectionEvents)
    {
        consume(
            m_clipperEnginePointAllocations, pointAllocations,
            MAX_CLIPPER_ENGINE_POINT_ALLOCATIONS_PER_DOCUMENT,
            "clipper_engine_point_allocations_document",
            ComplexityCounter::ClipperEnginePointAllocations);
        consume(
            m_clipperEngineRecordAllocations, recordAllocations,
            MAX_CLIPPER_ENGINE_RECORD_ALLOCATIONS_PER_DOCUMENT,
            "clipper_engine_record_allocations_document",
            ComplexityCounter::ClipperEngineRecordAllocations);
        consume(
            m_clipperEngineIntersectionNodeAllocations,
            intersectionNodeAllocations,
            MAX_CLIPPER_ENGINE_INTERSECTION_NODE_ALLOCATIONS_PER_DOCUMENT,
            "clipper_engine_intersection_nodes_document",
            ComplexityCounter::ClipperEngineIntersectionNodeAllocations);
        consume(
            m_clipperEngineProcessedIntersectionEvents,
            processedIntersectionEvents,
            MAX_CLIPPER_ENGINE_PROCESSED_INTERSECTION_EVENTS_PER_DOCUMENT,
            "clipper_engine_processed_intersections_document",
            ComplexityCounter::ClipperEngineProcessedIntersectionEvents);
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

    void requireClipperOutputCapacity(
        size_t pointCount, size_t ringCount) const
    {
        requireClipperOutputPointCapacity(pointCount);
        requireClipperOutputRingCapacity(ringCount);
    }

    void consumeClipperOutputPoints(size_t count)
    {
        requireClipperOutputPointCapacity(count);
        consume(
            m_clipperOutputPoints, count,
            MAX_CLIPPER_OUTPUT_POINTS_PER_DOCUMENT,
            "clipper_output_points_document",
            ComplexityCounter::ClipperOutputPoints);
    }

    void consumeClipperOutputRings(size_t count)
    {
        requireClipperOutputRingCapacity(count);
        consume(
            m_clipperOutputRings, count,
            MAX_CLIPPER_OUTPUT_RINGS_PER_DOCUMENT,
            "clipper_output_rings_document",
            ComplexityCounter::ClipperOutputRings);
    }

    void consumeCompositorBoundsCandidates(size_t count = 1)
    {
        consume(
            m_compositorBoundsCandidates, count,
            MAX_COMPOSITOR_BOUNDS_CANDIDATES,
            "compositor_bounds_candidates",
            ComplexityCounter::CompositorBoundsCandidates);
    }

    void consumeStrokeSimplificationComparisons(size_t count = 1)
    {
        consume(
            m_strokeSimplificationComparisons, count,
            MAX_STROKE_SIMPLIFICATION_COMPARISONS,
            "stroke_simplification_comparisons",
            ComplexityCounter::StrokeSimplificationComparisons);
    }

    void mergeFrom(const ComplexityBudget& other)
    {
        mergeCounter(
            m_generatedPoints, other.m_generatedPoints,
            MAX_GENERATED_POINTS, "generated_points");
        mergeCounter(
            m_generatedRings, other.m_generatedRings,
            MAX_GENERATED_RINGS, "generated_rings");
        mergeCounter(
            m_booleanInputPoints, other.m_booleanInputPoints,
            MAX_BOOLEAN_INPUT_POINTS_PER_DOCUMENT,
            "boolean_input_points_document");
        mergeCounter(
            m_resultPoints, other.m_resultPoints,
            MAX_RESULT_POINTS, "result_points");
        mergeCounter(
            m_clipperIntersectionCandidates,
            other.m_clipperIntersectionCandidates,
            MAX_CLIPPER_INTERSECTION_CANDIDATES_PER_DOCUMENT,
            "clipper_intersection_candidates_document");
        mergeCounter(
            m_clipperIntersectionComparisons,
            other.m_clipperIntersectionComparisons,
            MAX_CLIPPER_INTERSECTION_COMPARISONS_PER_DOCUMENT,
            "clipper_intersection_comparisons_document");
        mergeCounter(
            m_clipperEnginePointAllocations,
            other.m_clipperEnginePointAllocations,
            MAX_CLIPPER_ENGINE_POINT_ALLOCATIONS_PER_DOCUMENT,
            "clipper_engine_point_allocations_document");
        mergeCounter(
            m_clipperEngineRecordAllocations,
            other.m_clipperEngineRecordAllocations,
            MAX_CLIPPER_ENGINE_RECORD_ALLOCATIONS_PER_DOCUMENT,
            "clipper_engine_record_allocations_document");
        mergeCounter(
            m_clipperEngineIntersectionNodeAllocations,
            other.m_clipperEngineIntersectionNodeAllocations,
            MAX_CLIPPER_ENGINE_INTERSECTION_NODE_ALLOCATIONS_PER_DOCUMENT,
            "clipper_engine_intersection_nodes_document");
        mergeCounter(
            m_clipperEngineProcessedIntersectionEvents,
            other.m_clipperEngineProcessedIntersectionEvents,
            MAX_CLIPPER_ENGINE_PROCESSED_INTERSECTION_EVENTS_PER_DOCUMENT,
            "clipper_engine_processed_intersections_document");
        mergeCounter(
            m_clipperOutputPoints, other.m_clipperOutputPoints,
            MAX_CLIPPER_OUTPUT_POINTS_PER_DOCUMENT,
            "clipper_output_points_document");
        mergeCounter(
            m_clipperOutputRings, other.m_clipperOutputRings,
            MAX_CLIPPER_OUTPUT_RINGS_PER_DOCUMENT,
            "clipper_output_rings_document");
        mergeCounter(
            m_compositorBoundsCandidates,
            other.m_compositorBoundsCandidates,
            MAX_COMPOSITOR_BOUNDS_CANDIDATES,
            "compositor_bounds_candidates");
        mergeCounter(
            m_strokeSimplificationComparisons,
            other.m_strokeSimplificationComparisons,
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

    void consume(size_t& current, size_t count, size_t limit,
                 const char* budget, ComplexityCounter counter)
    {
        ensure(current, count, limit, budget);
        if(m_parallelGate != nullptr && count > 0) {
            constexpr size_t RESERVATION_CHUNK = 4'096;
            const size_t index = static_cast<size_t>(counter);
            if(m_parallelReservations[index] < count) {
                const size_t minimum = count - m_parallelReservations[index];
                const size_t preferred = std::max(
                    minimum, RESERVATION_CHUNK);
                m_parallelReservations[index] += m_parallelGate->reserve(
                    counter, minimum, preferred, limit, budget);
            }
            m_parallelReservations[index] -= count;
        }
        current += count;
    }

    ParallelComplexityReservation reserveParallelInFlight(
        ComplexityCounter counter, size_t count, size_t limit,
        const char* budget)
    {
        if(m_parallelGate == nullptr || count == 0)
            return {};
        const size_t reserved = m_parallelGate->reserve(
            counter, count, count, limit, budget);
        return {m_parallelGate, counter, reserved};
    }

    static void mergeCounter(size_t& current, size_t additional,
                             size_t limit, const char* budget)
    {
        ensure(current, additional, limit, budget);
        current += additional;
    }

    size_t m_generatedPoints{0};
    size_t m_generatedRings{0};
    size_t m_booleanInputPoints{0};
    size_t m_resultPoints{0};
    size_t m_clipperIntersectionCandidates{0};
    size_t m_clipperIntersectionComparisons{0};
    size_t m_clipperEnginePointAllocations{0};
    size_t m_clipperEngineRecordAllocations{0};
    size_t m_clipperEngineIntersectionNodeAllocations{0};
    size_t m_clipperEngineProcessedIntersectionEvents{0};
    size_t m_clipperOutputPoints{0};
    size_t m_clipperOutputRings{0};
    size_t m_compositorBoundsCandidates{0};
    size_t m_strokeSimplificationComparisons{0};
    ParallelComplexityGate* m_parallelGate{nullptr};
    Clipper2Lib::ClipperExecutionGate* m_clipperExecutionGate{nullptr};
    std::array<size_t,
               static_cast<size_t>(ComplexityCounter::Count)>
        m_parallelReservations{};
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
