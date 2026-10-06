/** Published schema V1 fields from da2abfefc, before puzzle/source additions. */
export function createLegacyRecipeV1() {
  const payload = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
  return {
    format: "lumina-recipe" as const,
    schema_version: 1,
    app_version: "2.0.0",
    created_at: "2026-04-08T12:00:00.000Z",
    source: "converter" as const,
    cover: { width: 1, height: 1, mime_type: "image/png" as const },
    asset: {
      primary: {
        filename: "original.png",
        mime_type: "image/png",
        byte_size: atob(payload).length,
        sha256: "retired-asset-digest",
        encoding: "base64" as const,
        payload_b64: payload,
      },
    },
    recipe: {
      converter: {
        base: {
          lut: { name: "TestLUT", color_mode: "4-Color (RYBW)", fingerprint: "retired-lut-digest" },
          color_mode: "4-Color (RYBW)", modeling_mode: "high-fidelity",
          target_width_mm: 80, target_height_mm: 60, auto_bg: false,
          bg_tol: 10, quantize_colors: 48, enable_cleanup: true,
          hue_enable: false, chroma_gate: 15,
        },
        geometry: {
          spacer_thick: 1.2, structure_mode: "Double-sided", separate_backing: false,
          add_loop: false, loop_width: 4, loop_length: 8, loop_hole: 2.5,
          loop_angle: 0, loop_offset_x: 0, loop_offset_y: 0, loop_position_preset: "top-center",
        },
        relief: { enable_relief: false, auto_height_mode: "darker-higher", color_height_map: {}, heightmap_max_height: 3 },
        outline: { enable_outline: false, outline_width: 2 },
        cloisonne: { enable_cloisonne: false, wire_width_mm: 0.4, wire_height_mm: 0.4 },
        coating: { enable_coating: false, coating_height_mm: 0.08 },
        color_ops: { replacement_regions: [], free_color_set: [] },
        large_format: { large_format_enabled: false, tile_width_mm: 180, tile_height_mm: 180 },
        device: { printer_id: "bambu-p1s", slicer: "OrcaSlicer" },
      },
    },
    integrity: { recipe_sha256: "retired-recipe-digest", asset_checksums: { primary: "retired-asset-digest" } },
    compat: { min_schema_version: 1 },
    warnings: [] as string[],
  };
}
