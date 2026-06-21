import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { I18nProvider } from "../i18n/context";
import ImportConfirmDialog from "../components/ui/ImportConfirmDialog";
import type { ImportPreview } from "../recipe/importFlow";

function createPreview(): ImportPreview {
  return {
    recipe: {
      format: "lumina-recipe",
      schema_version: 1,
      app_version: "0.0.0",
      created_at: "2026-04-12T00:00:00.000Z",
      source: "converter",
      cover: { width: 1, height: 1, mime_type: "image/png" },
      asset: {
        primary: {
          filename: "photo.png",
          mime_type: "image/png",
          byte_size: 4,
          sha256: "abcd",
          encoding: "base64",
          payload_b64: "dGVzdA==",
        },
      },
      recipe: {
        converter: {
          base: {
            lut: { name: "LUT", color_mode: "4-Color (RYBW)", fingerprint: "fp" },
            color_mode: "4-Color (RYBW)",
            modeling_mode: "high-fidelity",
            target_width_mm: 10,
            target_height_mm: 10,
            quantize_colors: 8,
            enable_cleanup: true,
            hue_enable: false,
            chroma_gate: 0,
          },
          geometry: {
            spacer_thick: 1.2,
            structure_mode: "Single-sided",
            separate_backing: false,
            add_loop: false,
            loop_width: 4,
            loop_length: 8,
            loop_hole: 2.5,
            loop_angle: 0,
            loop_offset_x: 0,
            loop_offset_y: 0,
            loop_position_preset: "top-center",
          },
          relief: {
            enable_relief: false,
            auto_height_mode: "darker-higher",
            color_height_map: {},
            heightmap_max_height: 1,
          },
          outline: { enable_outline: false, outline_width: 1 },
          cloisonne: { enable_cloisonne: false, wire_width_mm: 0.4, wire_height_mm: 0.4 },
          coating: { enable_coating: false, coating_height_mm: 0.08 },
          color_ops: { replacement_regions: [], free_color_set: [] },
          large_format: { large_format_enabled: false, tile_width_mm: 250, tile_height_mm: 250 },
          puzzle: {
            puzzle_enabled: false,
            puzzle_style: "regular",
            puzzle_sizing_mode: "piece_size",
            piece_width_mm: 20,
            piece_height_mm: 20,
            puzzle_rows: 3,
            puzzle_cols: 3,
            target_piece_count: 12,
            puzzle_seed: 0,
            connector_style: "classic",
            labels_enabled: false,
            engrave_back_labels: false,
            irregularity_strength: 0.35,
            min_neck_width_mm: 1.2,
          },
          fridge_magnet: {
            enable_fridge_magnet: true,
            fridge_magnets: [],
          },
          device: { printer_id: "", slicer: "", nozzle_size: "0.4" },
        },
      },
      integrity: {
        recipe_sha256: "0".repeat(64),
        asset_checksums: { primary: "abcd" },
      },
      compat: { min_schema_version: 1 },
      warnings: [],
    },
    restoreResult: {
      state: {},
      assetFile: new File(["test"], "photo.png", { type: "image/png" }),
      heightmapFile: null,
      warnings: [
        "recipe_import_warning_fridge_conflict_puzzle",
        "recipe_import_warning_fridge_conflict_large_format",
        "recipe_import_warning_fridge_conflict_loop",
        "recipe_import_warning_puzzle_conflict_large_format",
        "recipe_import_warning_puzzle_conflict_loop",
        "recipe_import_warning_back_labels_unavailable",
      ],
      recipe: {
        format: "lumina-recipe",
        schema_version: 1,
        app_version: "0.0.0",
        created_at: "2026-04-12T00:00:00.000Z",
        source: "converter",
        cover: { width: 1, height: 1, mime_type: "image/png" },
        asset: {
          primary: {
            filename: "photo.png",
            mime_type: "image/png",
            byte_size: 4,
            sha256: "abcd",
            encoding: "base64",
            payload_b64: "dGVzdA==",
          },
        },
        recipe: {},
        integrity: {
          recipe_sha256: "0".repeat(64),
          asset_checksums: { primary: "abcd" },
        },
        compat: { min_schema_version: 1 },
        warnings: [],
      },
    },
    coverUrl: null,
  };
}

describe("ImportConfirmDialog", () => {
  it("renders translated import conflict warnings instead of raw warning keys", () => {
    render(
      <I18nProvider>
        <ImportConfirmDialog
          open
          preview={createPreview()}
          source="json"
          onConfirm={() => {}}
          onCancel={() => {}}
        />
      </I18nProvider>,
    );

    expect(
      screen.getByText("导入的配方同时启用了冰箱贴模式和拼图模式。为保持状态有效，拼图模式已被禁用。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("导入的配方同时启用了冰箱贴模式和大画幅切片。为保持状态有效，大画幅模式已被禁用。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("导入的配方同时启用了冰箱贴模式和挂件环。为保持状态有效，挂件环已被禁用。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("导入的配方同时启用了拼图模式和大画幅切片。为保持状态有效，大画幅模式已被禁用。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("导入的配方同时启用了拼图模式和挂件环。为保持状态有效，挂件环已被禁用。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("导入的配方启用了拼图背面标签。当前版本暂不支持背面标签，已自动关闭。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("recipe_import_warning_fridge_conflict_puzzle"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("recipe_import_warning_fridge_conflict_loop"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("recipe_import_warning_puzzle_conflict_large_format"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("recipe_import_warning_back_labels_unavailable"),
    ).not.toBeInTheDocument();
  });
});
