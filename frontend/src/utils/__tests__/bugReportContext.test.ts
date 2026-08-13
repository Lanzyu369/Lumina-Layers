import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ColorMode } from "../../api/types";
import { useConverterStore } from "../../stores/converter";
import { useSettingsStore } from "../../stores/settingsStore";
import { useSingleStageStore } from "../../stores/singleStageStore";
import { useWidgetStore } from "../../stores/widgetStore";
import type { AdvancedParamsFull } from "../../types/actionHistory";
import { useWorkshopStore } from "../../workshop/store";
import { _clearClientLogBufferForTests, postClientLog } from "../clientLog";
import { collectBugReportContext } from "../bugReportContext";

declare const __LUMINA_VERSION__: string;

describe("collectBugReportContext", () => {
  const originalWindow = globalThis.window;
  const originalNavigator = globalThis.navigator;

  beforeEach(() => {
    _clearClientLogBufferForTests();
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
    useConverterStore.setState({
      sessionId: "converter-session",
      source_version: "legacy",
      selectedNativeBrandKey: "",
      selectedNativeDbNames: [],
      selectedMaterialDirNames: [],
      materialLayerCount: 5,
      materialLayerHeightMm: 0.08,
      downloadUrl: null,
      threemfDiskPath: null,
      largeFormatEnabled: false,
      replacement_regions: [],
      colorRemapMap: {},
      palette: [],
      regionReplacementCount: 0,
      free_color_set: new Set(),
      recipe_overrides: [],
    });
    useSettingsStore.setState({
      language: "en",
      theme: "dark",
      lastColorMode: "8-Color Max",
      lastLutName: "My LUT",
      preserveUploadFilenameFor3mf: false,
    });
    useSingleStageStore.setState({
      sessionId: null,
      stageAParamsUrl: null,
      materialFileUrl: null,
      savedStageAParamsUrl: null,
    });
    useWorkshopStore.setState({
      activeModule: null,
      activeRuntimeContext: null,
      pendingRecipeSource: null,
      diagnostics: null,
    });
    useWidgetStore.setState({ activeTab: "settings" });
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 900,
    });
    Object.defineProperty(window, "devicePixelRatio", {
      configurable: true,
      value: 2,
    });
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "http://localhost:5174/settings" },
    });
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: { userAgent: "vitest-agent" },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    _clearClientLogBufferForTests();
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow,
    });
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: originalNavigator,
    });
  });

  it("falls back to settings preference for color_mode/lut_name when activeTab is not converter", () => {
    const context = collectBugReportContext();

    expect(context).toEqual({
      url: "http://localhost:5174/settings",
      user_agent: "vitest-agent",
      screen_width: 1440,
      screen_height: 900,
      device_pixel_ratio: 2,
      app_version: __LUMINA_VERSION__,
      language: "en",
      theme: "dark",
      active_tab: "settings",
      active_session_ids: {
        converter: "converter-session",
        single_stage: null,
      },
      color_mode: "8-Color Max",
      lut_name: "My LUT",
      source_version: null,
      selected_native_brand_key: null,
      selected_native_db_names: [],
      selected_material_dir_names: [],
      material_layer_count: null,
      material_dynamic_layer_count_enabled: null,
      material_min_layer_count: null,
      material_max_layer_count: null,
      material_delta_e00_tolerance: null,
      material_layer_height_mm: null,
      material_backing_material_dir_name: null,
      preserve_upload_filename_for_3mf: false,
      recent_client_logs: [],
      action_history: [],
      session_history: [],
      active_original_image_ref: null,
      active_final_artifact_ref: null,
      advanced_params: null,
      workshop: null,
    });
  });

  it("captures the uploaded filename export preference for reproduction", () => {
    useSettingsStore.setState({ preserveUploadFilenameFor3mf: true });

    const context = collectBugReportContext();

    expect(context.preserve_upload_filename_for_3mf).toBe(true);
  });

  it("collects only bounded workshop diagnostics while the workshop tab is active", () => {
    useWidgetStore.setState({ activeTab: "workshop" });
    useWorkshopStore.setState({
      activeModule: {
        moduleId: "lumina.bead-pattern",
        version: "1.0.0",
      },
      activeRuntimeContext: {
        installSource: "seed",
        auditStatus: "official",
      },
      runtimeMode: "desktop-secure",
      pendingRecipeSource: {
        manifestSchemaVersion: 1,
        moduleId: "lumina.bead-pattern",
        moduleVersion: "1.0.0",
        projectSchemaVersion: "bead-project/v1",
        renderSchemaVersion: "bead-render/v1",
        payload: {
          matrix: [1, 2, 3],
          imageBytes: "private-image-bytes",
          packagePath: "/Users/min/private-module.lumina-workshop",
          githubToken: "ghp_private-token",
          registrySignature: "private-registry-signature",
          desktopToken: "private-desktop-token",
        },
      },
      diagnostics: {
        projectSchemaVersion: "bead-project/v1",
        inputMode: "numbered-grid",
        rows: 52,
        columns: 52,
        compression: 50,
        errorCode: null,
      },
    });
    useConverterStore.setState({
      workshopSource: {
        manifestSchemaVersion: 1,
        moduleId: "lumina.bead-pattern",
        moduleVersion: "1.0.0",
        projectSchemaVersion: "bead-project/v1",
        renderSchemaVersion: "bead-render/v1",
        payload: {
          inputMode: "numbered-grid",
          rows: 52,
          columns: 52,
          beadPitchMm: 2.6,
          compression: 50,
          palette: [
            {
              index: 1,
              name: "private-red",
              hex: "#ff0000",
            },
          ],
          cellsRle: [[2704, 1]],
          sourceFilename: "private-pattern.png",
          sourceUrl: "blob:http://localhost/private-source",
          sourcePath: "/Users/min/private-pattern.png",
        },
      },
    });

    const context = collectBugReportContext();
    const serialized = JSON.stringify(context);

    expect(context.workshop).toEqual({
      module_id: "lumina.bead-pattern",
      module_version: "1.0.0",
      install_source: "seed",
      audit_status: "official",
      runtime_mode: "desktop-secure",
      error_code: null,
    });
    expect(Object.keys(context.workshop ?? {}).sort()).toEqual(
      [
        "audit_status",
        "error_code",
        "install_source",
        "module_id",
        "module_version",
        "runtime_mode",
      ].sort(),
    );
    expect(serialized).not.toContain("cellsRle");
    expect(serialized).not.toContain("private-red");
    expect(serialized).not.toContain("#ff0000");
    expect(serialized).not.toContain("private-pattern.png");
    expect(serialized).not.toContain("blob:http");
    expect(serialized).not.toContain("/Users/min");
    expect(serialized).not.toContain("private-image-bytes");
    expect(serialized).not.toContain("ghp_private-token");
    expect(serialized).not.toContain("private-registry-signature");
    expect(serialized).not.toContain("private-desktop-token");
  });

  it("does not attach stale workshop diagnostics from another active tab", () => {
    useWidgetStore.setState({ activeTab: "settings" });
    useWorkshopStore.setState({
      activeModule: {
        moduleId: "lumina.bead-pattern",
        version: "1.0.0",
      },
      diagnostics: {
        projectSchemaVersion: "bead-project/v1",
        inputMode: "hard-pixel",
        rows: 24,
        columns: 24,
        compression: 85,
        errorCode: "recognition-uncertain",
      },
    });

    expect(collectBugReportContext().workshop).toBeNull();
  });

  it("prefers converter store color_mode and lut_name when activeTab is converter", () => {
    // Active workstream wins over the persisted settings preference: in
    // production the user was reporting an 8-Color Max issue while
    // settings.lastColorMode still held the default 4-Color (RYBW), making
    // the bug report misleading. The collector must reflect what the user
    // is actually working on, not the last persisted preference.
    useConverterStore.setState({
      sessionId: "converter-session",
      color_mode: ColorMode.EIGHT_COLOR,
      lut_name: "active-converter-lut",
    });
    useSettingsStore.setState({
      language: "en",
      theme: "dark",
      lastColorMode: ColorMode.FOUR_COLOR_RYBW,
      lastLutName: "stale-settings-lut",
    });
    useWidgetStore.setState({ activeTab: "converter" });

    const context = collectBugReportContext();

    expect(context.active_tab).toBe("converter");
    expect(context.color_mode).toBe("8-Color Max");
    expect(context.lut_name).toBe("active-converter-lut");
    expect(context.source_version).toBe("legacy");
  });

  it("collects material archive source details instead of stale LUT details", () => {
    useConverterStore.setState({
      sessionId: "converter-session",
      source_version: "material",
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      lut_name: "stale-lut",
      selectedMaterialDirNames: ["Aliz/red", "Wujing/white"],
      materialLayerCount: 10,
      materialLayerHeightMm: 0.06,
    });
    useSettingsStore.setState({
      language: "en",
      theme: "dark",
      lastColorMode: "8-Color Max",
      lastLutName: "settings-lut",
    });
    useWidgetStore.setState({ activeTab: "converter" });

    const context = collectBugReportContext();

    expect(context.source_version).toBe("material");
    expect(context.color_mode).toBeNull();
    expect(context.lut_name).toBeNull();
    expect(context.selected_material_dir_names).toEqual(["Aliz/red", "Wujing/white"]);
    expect(context.material_layer_count).toBe(10);
    expect(context.material_layer_height_mm).toBe(0.06);
  });

  it("captures dynamic material settings for backend reproduction", () => {
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: ["brand/red", "brand/white"],
      materialBackingMaterialDirName: "brand/white",
      materialDynamicLayerCountEnabled: true,
      materialMinLayerCount: 5,
      materialMaxLayerCount: 9,
    });
    useSettingsStore.setState({ materialDeltaE00Tolerance: 0.4 });
    useWidgetStore.setState({ activeTab: "converter" });

    const context = collectBugReportContext() as unknown as Record<string, unknown>;

    expect(context.material_dynamic_layer_count_enabled).toBe(true);
    expect(context.material_min_layer_count).toBe(5);
    expect(context.material_max_layer_count).toBe(9);
    expect(context.material_delta_e00_tolerance).toBe(0.4);
    expect(context.material_backing_material_dir_name).toBe("brand/white");
  });

  it("collects native LUT source details on converter tab", () => {
    useConverterStore.setState({
      sessionId: "converter-session",
      source_version: "native",
      selectedNativeBrandKey: "bambu",
      selectedNativeDbNames: ["PLA Basic", "PETG Translucent"],
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      lut_name: "native-summary",
    });
    useWidgetStore.setState({ activeTab: "converter" });

    const context = collectBugReportContext();

    expect(context.source_version).toBe("native");
    expect(context.selected_native_brand_key).toBe("bambu");
    expect(context.selected_native_db_names).toEqual(["PLA Basic", "PETG Translucent"]);
    expect(context.selected_material_dir_names).toEqual([]);
  });

  it("returns null color_mode and lut_name when converter store has empty values on converter tab", () => {
    // When the user is on the converter tab but has not picked a LUT yet,
    // showing the stale settings.lastLutName preference would mislead the
    // developer into thinking a LUT was loaded. Active state wins, even
    // when empty. color_mode falls through to settings only when the
    // converter store value is empty/falsy (rare; the enum has a default).
    useConverterStore.setState({
      sessionId: "converter-session",
      color_mode: "" as unknown as ColorMode,
      lut_name: "",
    });
    useSettingsStore.setState({
      language: "en",
      theme: "dark",
      lastColorMode: "8-Color Max",
      lastLutName: "stale-settings-lut",
    });
    useWidgetStore.setState({ activeTab: "converter" });

    const context = collectBugReportContext();

    expect(context.active_tab).toBe("converter");
    expect(context.color_mode).toBeNull();
    expect(context.lut_name).toBeNull();
  });

  it("falls back to safe defaults when browser globals are unavailable", () => {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: undefined,
    });
    useConverterStore.setState({ sessionId: null });

    const context = collectBugReportContext();

    expect(context.url).toBe("");
    expect(context.user_agent).toBe("");
    expect(context.screen_width).toBe(0);
    expect(context.screen_height).toBe(0);
    expect(context.device_pixel_ratio).toBe(1);
    expect(context.active_session_ids).toEqual({
      converter: null,
      single_stage: null,
    });
    expect(context.recent_client_logs).toEqual([]);
  });

  it("includes bounded recent client logs for diagnostics", () => {
    postClientLog("preview: failed", {
      elapsedMs: 42,
      method: "warn",
      scope: "preview",
      phase: "failed",
      details: { reason: "timeout" },
    });

    const context = collectBugReportContext();

    expect(context.recent_client_logs).toEqual([
      expect.objectContaining({
        method: "warn",
        label: "preview: failed",
        elapsed_ms: 42,
        scope: "preview",
        phase: "failed",
        details: { reason: "timeout" },
      }),
    ]);
  });

  it("redacts local file paths from recent client logs in bug reports", () => {
    postClientLog("generate: response received", {
      scope: "generate",
      phase: "response-received",
      details: {
        threemf_disk_path: "/Users/min/CascadeProjects/Lumina-studio/output/model.3mf",
        file_path: "E:/tmp/upload.png",
        message: "failed while reading /private/tmp/lumina/model.3mf",
        download_url: "/api/files/tmp-model",
      },
    });

    const context = collectBugReportContext();
    const serializedLogs = JSON.stringify(context.recent_client_logs);

    expect(serializedLogs).not.toContain("/Users/min");
    expect(serializedLogs).not.toContain("E:/tmp");
    expect(serializedLogs).not.toContain("/private/tmp");
    expect(serializedLogs).toContain("<redacted:local-path>");
    expect(serializedLogs).toContain("/api/files/tmp-model");
  });

  it("populates advanced_params as an AdvancedParamsFull on the converter tab when advanced fields are non-default", () => {
    // The collector must ship a grouped advanced_params object so the
    // backend ticket can surface which feature toggles were active when
    // the user hit "Report". We flip a couple of toggles and check the
    // corresponding groups carry the live store values instead of the
    // disabled-toggle null placeholders.
    // converter Tab 激活、用户打开了浮雕 / 大幅面等高级开关时，反馈上下文
    // 必须带上 advanced_params 分组对象，让后端工单能看到当时生效的功能
    // 开关；否则后端只能按默认值推测用户场景。
    useWidgetStore.setState({ activeTab: "converter" });
    useConverterStore.setState({
      sessionId: "converter-session",
      target_width_mm: 120,
      target_height_mm: 90,
      enable_relief: true,
      color_height_map: { "#ff0000": 1.5, "#00ff00": 2.0 },
      heightmap_max_height: 4.0,
      enable_outline: true,
      outline_width: 2.5,
      largeFormatEnabled: true,
      tileWidthMm: 200,
      tileHeightMm: 180,
      modelSurfaceEnabled: true,
      modelSurfaceFile: new File(["mesh"], "plate.stl", {
        type: "application/octet-stream",
      }),
      modelSurfaceModelFileId: "surface-model-file",
      modelSurfaceSelectionId: "surface-selection",
      modelSurfaceSelection: { face_count: 6513 },
      modelSurfaceFootprint: {
        bounds_width_mm: 197,
        bounds_height_mm: 197,
        hole_count: 85,
      },
      modelSurfacePlacement: {
        mode: "edge_to_edge",
        offset_x_mm: 2,
        offset_y_mm: -3,
        scale: 1.1,
        rotation_deg: 15,
        inset_mm: 0,
      },
      modelSurfaceModelRotation: {
        x_deg: 180,
        y_deg: 0,
        z_deg: 0,
      },
      colorRemapMap: { aabbcc: "ddeeff" },
      palette: [
        {
          quantized_hex: "112233",
          matched_hex: "aabbcc",
          pixel_count: 42,
          percentage: 1,
        },
      ],
      regionReplacementCount: 3,
      free_color_set: new Set(["ff0000"]),
      recipe_overrides: [
        {
          region_id: "region-a",
          recipe: [0, 1, 2, 4],
          layer_order: "Top2Bottom",
          virtual_materials: [{ name: "Matte Black", hex: "#101010" }],
        },
      ],
    });

    const context = collectBugReportContext();

    expect(context.advanced_params).not.toBeNull();
    const advanced = context.advanced_params as AdvancedParamsFull;

    // Dimensions group reflects the live store values.
    expect(advanced.dimensions.target_width_mm).toBe(120);
    expect(advanced.dimensions.target_height_mm).toBe(90);

    // Enabled-toggle groups carry their detail fields.
    expect(advanced.relief.enable_relief).toBe(true);
    expect(advanced.relief.color_height_map).toEqual({
      "#ff0000": 1.5,
      "#00ff00": 2.0,
    });
    expect(advanced.relief.heightmap_max_height).toBe(4.0);

    expect(advanced.outline.enable_outline).toBe(true);
    expect(advanced.outline.outline_width).toBe(2.5);

    expect(advanced.large_format.largeFormatEnabled).toBe(true);
    expect(advanced.large_format.tileWidthMm).toBe(200);
    expect(advanced.large_format.tileHeightMm).toBe(180);
    expect(advanced.model_surface).toEqual({
      enabled: true,
      model_file: {
        name: "plate.stl",
        size: 4,
        type: "application/octet-stream",
      },
      model_file_id: "surface-model-file",
      selection_id: "surface-selection",
      selected_face_count: 6513,
      footprint: {
        width_mm: 197,
        height_mm: 197,
        hole_count: 85,
      },
      placement: {
        mode: "edge_to_edge",
        offset_x_mm: 2,
        offset_y_mm: -3,
        scale: 1.1,
        rotation_deg: 15,
        inset_mm: 0,
      },
      model_rotation: {
        x_deg: 180,
        y_deg: 0,
        z_deg: 0,
      },
    });

    expect(advanced.color_replacement.free_color_set).toEqual(["#ff0000"]);
    expect(advanced.color_replacement.spatial_edit_count).toBe(3);
    expect(advanced.color_replacement.replacement_regions).toEqual([
      {
        quantized_hex: "#112233",
        matched_hex: "#aabbcc",
        replacement_hex: "#ddeeff",
      },
    ]);
    expect(advanced.color_replacement.recipe_overrides).toEqual([
      {
        region_id: "region-a",
        recipe: [0, 1, 2, 4],
        layer_order: "Top2Bottom",
        virtual_materials: [{ name: "Matte Black", hex: "#101010" }],
      },
    ]);

    // Disabled-toggle groups are still present with their toggles false
    // and detail fields nulled out (builder contract).
    expect(advanced.cloisonne.enable_cloisonne).toBe(false);
    expect(advanced.cloisonne.wire_width_mm).toBeNull();
    expect(advanced.puzzle.puzzleEnabled).toBe(false);
  });

  it("returns advanced_params === null when activeTab is not 'converter'", () => {
    // When the user is reporting from another tab (settings / extractor /
    // single-stage etc.), advanced_params is not applicable — the
    // converter-only feature toggles are not the user's current workflow.
    // 用户在非 converter Tab 提交反馈时，高级参数与当前工作流无关，
    // 统一置 null，避免给后端带入误导性的历史值。
    useWidgetStore.setState({ activeTab: "settings" });
    useConverterStore.setState({
      // Converter store has advanced fields set but the active tab is
      // elsewhere — the builder must still return null.
      enable_relief: true,
      largeFormatEnabled: true,
    });

    const context = collectBugReportContext();

    expect(context.advanced_params).toBeNull();
  });

  it("does not attach stale converter final artifacts when activeTab is not converter", () => {
    useWidgetStore.setState({ activeTab: "settings" });
    useConverterStore.setState({
      sessionId: "old-converter-session",
      downloadUrl: "/api/files/old-3mf",
      threemfDiskPath: "/tmp/old-model.3mf",
      largeFormatEnabled: false,
    });

    const context = collectBugReportContext();

    expect(context.active_original_image_ref).toBeNull();
    expect(context.advanced_params).toBeNull();
    expect(context.active_final_artifact_ref).toBeNull();
  });

  it("captures active gradient-card extract session for bug-report log lookup", () => {
    useWidgetStore.setState({ activeTab: "gradient-card-extract" });
    useConverterStore.setState({
      sessionId: "stale-converter-session",
      downloadUrl: "/api/files/stale-3mf",
      threemfDiskPath: "/tmp/stale-model.3mf",
    });
    useSingleStageStore.setState({
      sessionId: "single-stage-session",
      stageAParamsUrl: "/api/files/stage-a-params",
      materialFileUrl: "/api/files/material-json",
      savedStageAParamsUrl: "/api/files/saved-stage-a-params",
    });

    const context = collectBugReportContext();

    expect(context.active_session_ids).toEqual({
      converter: "stale-converter-session",
      single_stage: "single-stage-session",
    });
    // Gradient-card extraction has two source images and the backend does
    // not register those uploads as a singular original-image attachment
    // today. Keep the session id for log lookup without promising a file
    // attachment the backend cannot currently resolve.
    expect(context.active_original_image_ref).toBeNull();
    expect(context.active_final_artifact_ref).toBeNull();
    expect(context.advanced_params).toBeNull();
  });

  it("keeps inactive single-stage sessions available for log lookup without attaching stale originals", () => {
    useWidgetStore.setState({ activeTab: "settings" });
    useSingleStageStore.setState({
      sessionId: "inactive-single-stage-session",
    });

    const context = collectBugReportContext();

    expect(context.active_session_ids.single_stage).toBe("inactive-single-stage-session");
    expect(context.active_original_image_ref).toBeNull();
    expect(context.active_final_artifact_ref).toBeNull();
  });

  it("preserves every other payload field when advanced_params is added (non-regression)", () => {
    // Adding advanced_params must not drop, rename, or reorder any
    // existing bug-report context field. Guard the representative fields
    // that downstream consumers (frontend uploader, backend index, email
    // relay) already rely on.
    // 新增 advanced_params 不能把现有的反馈字段删掉或改名；这里挑选若干
    // 下游已经在用的字段做兜底断言。
    useWidgetStore.setState({ activeTab: "converter" });
    useConverterStore.setState({
      sessionId: "converter-session",
      color_mode: ColorMode.EIGHT_COLOR,
      lut_name: "non-regression-lut",
    });

    const context = collectBugReportContext();

    // Representative fields must still exist with their expected shapes.
    expect(context.url).toBe("http://localhost:5174/settings");
    expect(context.active_tab).toBe("converter");
    expect(context.color_mode).toBe("8-Color Max");
    expect(context.action_history).toEqual([]);
    expect(context.active_final_artifact_ref).toBeNull();

    // No previously exported key was renamed — each representative key
    // must still appear on the payload object.
    const keys = Object.keys(context);
    for (const key of [
      "url",
      "user_agent",
      "screen_width",
      "screen_height",
      "device_pixel_ratio",
      "app_version",
      "language",
      "theme",
      "active_tab",
      "active_session_ids",
      "color_mode",
      "lut_name",
      "source_version",
      "selected_native_brand_key",
      "selected_native_db_names",
      "selected_material_dir_names",
      "material_layer_count",
      "material_dynamic_layer_count_enabled",
      "material_min_layer_count",
      "material_max_layer_count",
      "material_delta_e00_tolerance",
      "material_layer_height_mm",
      "material_backing_material_dir_name",
      "preserve_upload_filename_for_3mf",
      "recent_client_logs",
      "action_history",
      "session_history",
      "active_original_image_ref",
      "active_final_artifact_ref",
      "advanced_params",
      "workshop",
    ]) {
      expect(keys).toContain(key);
    }
  });

  it("marks large-format file downloads as zip artifacts", () => {
    useWidgetStore.setState({ activeTab: "converter" });
    useConverterStore.setState({
      sessionId: "converter-large-format",
      downloadUrl: "/api/files/large-format-download-id",
      threemfDiskPath: null,
      largeFormatEnabled: true,
    });

    const context = collectBugReportContext();

    expect(context.active_final_artifact_ref).toEqual({
      session_id: "converter-large-format",
      download_url: "/api/files/large-format-download-id",
      artifact_type: "zip",
      source: "converter",
    });
  });

  it("captures converter 3mf final artifacts without disk paths", () => {
    useWidgetStore.setState({ activeTab: "converter" });
    useConverterStore.setState({
      sessionId: "converter-3mf",
      downloadUrl: "/api/files/model-3mf-download-id",
      threemfDiskPath: "/tmp/model.3mf",
      largeFormatEnabled: false,
    });

    const context = collectBugReportContext();

    expect(context.active_final_artifact_ref).toEqual({
      session_id: "converter-3mf",
      download_url: "/api/files/model-3mf-download-id",
      artifact_type: "3mf",
      source: "converter",
    });
    expect(context.active_final_artifact_ref).not.toHaveProperty("disk_path");
  });
});
