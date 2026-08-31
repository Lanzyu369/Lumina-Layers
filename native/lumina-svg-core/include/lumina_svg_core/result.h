#ifndef LUMINA_SVG_CORE_RESULT_H
#define LUMINA_SVG_CORE_RESULT_H

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace lumina_svg_core {

inline constexpr uint32_t RESULT_SCHEMA_VERSION = 1;

enum class SourceKind : int32_t {
    Fill = 0,
    Stroke = 1,
    Silhouette = 2,
};

struct GeometryCollection {
    // Coordinates are stored as interleaved x/y pairs. Offsets count points,
    // rings, and polygons respectively (never scalar coordinate values).
    std::vector<int64_t> coordinates;
    std::vector<uint64_t> ring_offsets{0};
    std::vector<uint64_t> polygon_offsets{0};
    std::vector<uint64_t> geometry_offsets{0};
    std::vector<int64_t> hole_parent;
    std::vector<uint8_t> rgba;
    std::vector<int32_t> draw_indices;
    std::vector<int32_t> source_indices;
    std::vector<int32_t> source_kinds;

    uint64_t geometryCount() const;
    uint64_t componentCount() const;
    uint64_t holeCount() const;
};

struct NativeResult : public std::enable_shared_from_this<NativeResult> {
    std::string status{"invalid"};
    std::string reason_code{"invalid_svg"};
    uint32_t schema_version{RESULT_SCHEMA_VERSION};
    std::array<double, 4> bbox{{0, 0, 0, 0}};
    std::array<double, 4> viewport_bounds{{0, 0, 0, 0}};
    bool image_vectorizer_origin{false};
    double scale_factor{0};
    double grid_to_source_unit{0};
    double max_flattening_error_mm{0};
    double max_quantization_error_mm{0};
    bool legacy_contour_normalization_identity{true};
    bool legacy_contour_normalization_compatible{true};
    bool legacy_area_filter_identity{true};
    bool legacy_curve_tolerance_compatible{true};
    double recorder_seconds{0};
    double kernel_seconds{0};
    double bounds_seconds{0};
    double replay_seconds{0};
    double topology_seconds{0};
    double legacy_raw_seconds{0};
    double composite_seconds{0};
    double legacy_visible_seconds{0};
    double export_seconds{0};
    // Time to wrap this owned C++ result as a Python object. NumPy views and
    // downstream float/Shapely materialization are measured by their callers.
    double result_conversion_seconds{0};
    GeometryCollection raw;
    GeometryCollection visible;
    GeometryCollection silhouette;
};

struct GeometryCollectionView {
    std::shared_ptr<NativeResult> owner;
    const GeometryCollection* collection{nullptr};
};

} // namespace lumina_svg_core

#endif // LUMINA_SVG_CORE_RESULT_H
