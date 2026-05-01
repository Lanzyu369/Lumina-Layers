import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ColorMode } from "../../api/types";
import { useConverterStore } from "../../stores/converter";
import { useSettingsStore } from "../../stores/settingsStore";
import { useSingleStageStore } from "../../stores/singleStageStore";
import { useWidgetStore } from "../../stores/widgetStore";
import { collectBugReportContext } from "../bugReportContext";

declare const __LUMINA_VERSION__: string;

describe("collectBugReportContext", () => {
  const originalWindow = globalThis.window;
  const originalNavigator = globalThis.navigator;

  beforeEach(() => {
    useConverterStore.setState({
      sessionId: "converter-session",
      source_version: "legacy",
      selectedNativeBrandKey: "",
      selectedNativeDbNames: [],
      selectedMaterialDirNames: [],
      materialLayerCount: 5,
      materialLayerHeightMm: 0.08,
    });
    useSingleStageStore.setState({ sessionId: "single-session" });
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
        single_stage: "single-session",
      },
      color_mode: "8-Color Max",
      lut_name: "My LUT",
      source_version: null,
      selected_native_brand_key: null,
      selected_native_db_names: [],
      selected_material_dir_names: [],
      material_layer_count: null,
      material_layer_height_mm: null,
      recent_client_logs: [],
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
    useSingleStageStore.setState({ sessionId: null });

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
});
