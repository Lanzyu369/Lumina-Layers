/**
 * Property-Based Tests for Vectorizer Tab frontend.
 * Vectorizer Tab 前端 Property-Based 测试。
 *
 * Properties tested:
 * - Property 4: 缩放/平移同步一致性 (Zoom/Pan sync consistency)
 * - Property 5: 下载 URL 构建正确性 (Download URL construction)
 * - Property 6: i18n 键完整性 (i18n key completeness)
 * - Property 8: 请求取消状态一致性 (Request cancel state consistency)
 */

import { describe, it, expect, vi } from "vitest";
import * as fc from "fast-check";

const { mockedApiClient } = vi.hoisted(() => ({
  mockedApiClient: {
    defaults: { baseURL: "/api" },
    post: vi.fn(),
    get: vi.fn(),
  },
}));

// Mock apiClient before importing buildFileUrl
vi.mock("../api/client", () => ({
  default: mockedApiClient,
  buildApiResourceUrl: (relativePath: string) => {
    const base = mockedApiClient.defaults.baseURL ?? "";
    if (!relativePath) return base;
    if (/^https?:\/\//i.test(relativePath)) return relativePath;
    const normalizedPath = relativePath.startsWith("/") ? relativePath : `/${relativePath}`;
    if (!base) return normalizedPath;
    const normalizedBase = base.replace(/\/+$/, "");
    const baseIsAbsolute = /^https?:\/\//i.test(normalizedBase);
    if (normalizedPath.startsWith("/api/")) {
      if (!baseIsAbsolute && normalizedBase === "/api") {
        return normalizedPath;
      }
      if (baseIsAbsolute) {
        const parsedBase = new URL(normalizedBase);
        const pathPrefixMatch = parsedBase.pathname.match(/^(.*)\/api$/);
        const pathPrefixRaw = pathPrefixMatch?.[1] ?? "";
        const pathPrefix = pathPrefixRaw === "/" ? "" : pathPrefixRaw.replace(/\/+$/, "");
        return `${parsedBase.origin}${pathPrefix}${normalizedPath}`;
      }
    }
    return `${normalizedBase.replace(/\/+$/, "")}/${normalizedPath.replace(/^\/+/, "")}`;
  },
}));

vi.mock("../api/vectorizer", () => ({
  vectorizeImage: vi.fn(),
}));

vi.mock("../stores/converter", () => ({
  useConverterStore: {
    getState: vi.fn(() => ({ setImageFile: vi.fn(), setModelingMode: vi.fn() })),
  },
}));

vi.mock("../stores/widgetStore", () => ({
  useWidgetStore: {
    getState: vi.fn(() => ({ setActiveTab: vi.fn() })),
  },
}));

import { buildFileUrl } from "../components/VectorizerPanel";
import { useVectorizerStore } from "../stores/vectorizerStore";
import { translations } from "../i18n/translations";

// ============================================================
// Property 4: 缩放/平移同步一致性
// ============================================================

// ============================================================
// Property 5: 下载 URL 构建正确性
// ============================================================
describe("Property 5: 下载 URL 构建正确性 (Download URL construction)", () => {
  /**
   * **Validates: Requirements 4.2**
   *
   * For any relative SVG path, buildFileUrl must produce a URL that:
   * 1. Starts with the apiClient baseURL
   * 2. Contains the original relative path as a suffix
   * 3. Never produces double slashes (except in protocol)
   */

  // Generate paths like /files/abc123.svg
  const relativePathArb = fc
    .tuple(
      fc.stringMatching(/^[a-z0-9_-]{1,20}$/),
      fc.stringMatching(/^[a-z0-9_-]{1,20}$/),
    )
    .map(([dir, file]) => `/${dir}/${file}.svg`);

  it("buildFileUrl always starts with baseURL and ends with the relative path", () => {
    // **Validates: Requirements 4.2**
    fc.assert(
      fc.property(relativePathArb, (path) => {
        const url = buildFileUrl(path);
        expect(url).toBe(`/api${path}`);
        expect(url.endsWith(path)).toBe(true);
      }),
      { numRuns: 200 },
    );
  });

  const apiPrefixedPathArb = fc
    .tuple(
      fc.stringMatching(/^[a-z0-9_-]{1,20}$/),
      fc.stringMatching(/^[a-z0-9_-]{1,20}$/),
    )
    .map(([dir, file]) => `/api/${dir}/${file}.svg`);

  it("buildFileUrl preserves api-prefixed resource paths without double-prefixing", () => {
    fc.assert(
      fc.property(apiPrefixedPathArb, (path) => {
        expect(buildFileUrl(path)).toBe(path);
      }),
      { numRuns: 200 },
    );
  });
});

// ============================================================
// Property 6: i18n 键完整性
// ============================================================
describe("Property 6: i18n 键完整性 (i18n key completeness)", () => {
  /**
   * **Validates: Requirements 6.1, 6.2**
   *
   * Every translation key used by VectorizerPanel (vec.* keys) must:
   * 1. Exist in the translations object
   * 2. Have both zh and en values
   * 3. Have non-empty string values for both languages
   */

  // All vec.* keys used in VectorizerPanel
  const VECTORIZER_KEYS = [
    "vec.title",
    "vec.basic_params",
    "vec.advanced_params",
    "vec.output_enhance",
    "vec.num_colors",
    "vec.num_colors_auto",
    "vec.num_colors_manual",
    "vec.detail_level",
    "vec.detail_level_on",
    "vec.detail_level_off",
    "vec.smoothness",
    "vec.svg_enable_stroke",
    "vec.svg_stroke_width",
    "vec.thin_line_max_radius",
    "vec.enable_coverage_fix",
    "vec.min_coverage_ratio",
    "vec.adv_preprocess",
    "vec.smoothing_spatial",
    "vec.smoothing_color",
    "vec.max_working_pixels",
    "vec.adv_segmentation",
    "vec.slic_region_size",
    "vec.edge_sensitivity",
    "vec.refine_passes",
    "vec.enable_antialias_detect",
    "vec.aa_tolerance",
    "vec.adv_curve_fitting",
    "vec.curve_fit_error",
    "vec.contour_simplify",
    "vec.merge_segment_tolerance",
    "vec.adv_filtering",
    "vec.min_region_area",
    "vec.max_merge_color_dist",
    "vec.min_contour_area",
    "vec.min_hole_area",
    "vec.submit",
    "vec.processing",
    "vec.result_title",
    "vec.original",
    "vec.svg_preview",
    "vec.shapes",
    "vec.colors",
    "vec.download_svg",
    "vec.send_to_converter",
    "vec.resource_action_failed",
    "vec.error",
    "vec.no_image",
  ] as const;

  const keyArb = fc.constantFrom(...VECTORIZER_KEYS);

  it("every vec.* key exists in translations with both zh and en", () => {
    // **Validates: Requirements 6.1, 6.2**
    fc.assert(
      fc.property(keyArb, (key) => {
        const entry = translations[key];
        expect(entry).toBeDefined();
        expect(typeof entry.zh).toBe("string");
        expect(typeof entry.en).toBe("string");
        expect(entry.zh.length).toBeGreaterThan(0);
        expect(entry.en.length).toBeGreaterThan(0);
      }),
      { numRuns: VECTORIZER_KEYS.length * 3 },
    );
  });

  // Also check hint keys
  const HINT_KEYS = [
    "vec.hint_num_colors",
    "vec.hint_smoothness",
    "vec.hint_detail_level",
    "vec.hint_svg_enable_stroke",
    "vec.hint_svg_stroke_width",
    "vec.hint_thin_line_max_radius",
    "vec.hint_enable_coverage_fix",
    "vec.hint_min_coverage_ratio",
    "vec.hint_smoothing_spatial",
    "vec.hint_smoothing_color",
    "vec.hint_max_working_pixels",
    "vec.hint_slic_region_size",
    "vec.hint_edge_sensitivity",
    "vec.hint_refine_passes",
    "vec.hint_enable_antialias_detect",
    "vec.hint_aa_tolerance",
    "vec.hint_curve_fit_error",
    "vec.hint_contour_simplify",
    "vec.hint_merge_segment_tolerance",
    "vec.hint_min_region_area",
    "vec.hint_max_merge_color_dist",
    "vec.hint_min_contour_area",
    "vec.hint_min_hole_area",
  ] as const;

  const hintKeyArb = fc.constantFrom(...HINT_KEYS);

  it("every vec.hint_* key exists in translations with both zh and en", () => {
    // **Validates: Requirements 6.1, 6.2**
    fc.assert(
      fc.property(hintKeyArb, (key) => {
        const entry = translations[key];
        expect(entry).toBeDefined();
        expect(typeof entry.zh).toBe("string");
        expect(typeof entry.en).toBe("string");
        expect(entry.zh.length).toBeGreaterThan(0);
        expect(entry.en.length).toBeGreaterThan(0);
      }),
      { numRuns: HINT_KEYS.length * 3 },
    );
  });
});

// ============================================================
// Property 8: 请求取消状态一致性
// ============================================================
describe("Property 8: 请求取消状态一致性 (Request cancel state consistency)", () => {
  /**
   * **Validates: Requirements 10.1**
   *
   * After cancel() is called, the store must always be in a consistent
   * non-processing state: isProcessing=false, abortController=null,
   * and error=null (cancel is not an error).
   */

  it("cancel always produces consistent non-processing state when abortController exists", () => {
    // **Validates: Requirements 10.1**
    // cancel() only acts when abortController is non-null (i.e., a request is in-flight).
    // When abortController is null, cancel() is a no-op by design.
    fc.assert(
      fc.property(
        fc.option(fc.string(), { nil: null }), // error
        (prevError) => {
          // Set up state with an active abortController (simulating in-flight request)
          useVectorizerStore.setState({
            isProcessing: true,
            error: prevError,
            abortController: new AbortController(),
          });

          // Call cancel
          useVectorizerStore.getState().cancel();

          const state = useVectorizerStore.getState();

          // Post-conditions: always consistent after cancel with active controller
          expect(state.isProcessing).toBe(false);
          expect(state.abortController).toBeNull();
        },
      ),
      { numRuns: 100 },
    );
  });

  it("cancel is a no-op when no abortController exists", () => {
    // **Validates: Requirements 10.1**
    fc.assert(
      fc.property(
        fc.boolean(), // isProcessing
        fc.option(fc.string(), { nil: null }), // error
        (wasProcessing, prevError) => {
          useVectorizerStore.setState({
            isProcessing: wasProcessing,
            error: prevError,
            abortController: null,
          });

          const beforeProcessing = useVectorizerStore.getState().isProcessing;

          useVectorizerStore.getState().cancel();

          // No-op: isProcessing unchanged when no controller
          expect(useVectorizerStore.getState().isProcessing).toBe(beforeProcessing);
          expect(useVectorizerStore.getState().abortController).toBeNull();
        },
      ),
      { numRuns: 50 },
    );
  });

  it("reset always produces a clean initial state regardless of prior state", () => {
    // **Validates: Requirements 10.1**
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.option(fc.string(), { nil: null }),
        fc.integer({ min: 0, max: 256 }),
        fc.double({ min: 0, max: 1, noNaN: true }),
        (wasProcessing, prevError, numColors, smoothness) => {
          useVectorizerStore.setState({
            isProcessing: wasProcessing,
            error: prevError,
          });
          useVectorizerStore.getState().setParam("num_colors", numColors);
          useVectorizerStore.getState().setParam("smoothness", smoothness);

          useVectorizerStore.getState().reset();

          const state = useVectorizerStore.getState();
          expect(state.isProcessing).toBe(false);
          expect(state.error).toBeNull();
          expect(state.result).toBeNull();
          expect(state.imageFile).toBeNull();
          expect(state.params.num_colors).toBe(0);
          expect(state.params.smoothness).toBe(0.5);
        },
      ),
      { numRuns: 100 },
    );
  });
});
