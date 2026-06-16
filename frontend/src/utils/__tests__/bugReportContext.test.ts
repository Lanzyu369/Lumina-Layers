import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ColorMode } from "../../api/types";
import { useConverterStore } from "../../stores/converter";
import { useSettingsStore } from "../../stores/settingsStore";
import { useWidgetStore } from "../../stores/widgetStore";
import type { AdvancedParamsFull } from "../../types/actionHistory";
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
    });
    useSettingsStore.setState({
      language: "en",
      theme: "dark",
      lastColorMode: "8-Color Max",
      lastLutName: "My LUT",
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
      material_layer_height_mm: null,
      material_backing_material_dir_name: null,
      recent_client_logs: [],
      action_history: [],
      session_history: [],
      active_original_image_ref: null,
      active_final_artifact_ref: null,
      advanced_params: null,
    });
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
      "material_layer_height_mm",
      "material_backing_material_dir_name",
      "recent_client_logs",
      "action_history",
      "session_history",
      "active_original_image_ref",
      "active_final_artifact_ref",
      "advanced_params",
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
      disk_path: null,
      source: "converter",
    });
  });

  it("captures converter 3mf final artifacts on the converter tab", () => {
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
      disk_path: "/tmp/model.3mf",
      source: "converter",
    });
  });
});
