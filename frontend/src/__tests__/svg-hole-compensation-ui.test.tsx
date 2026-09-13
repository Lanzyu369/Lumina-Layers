import { act, fireEvent, render, renderHook, screen, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
vi.unmock("../i18n/context");
import SvgHoleCompensationSettings from "../components/sections/SvgHoleCompensationSettings";
import { I18nProvider } from "../i18n/context";
import { translations } from "../i18n/translations";
import { ModelingMode } from "../api/types";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { ANNOUNCEMENTS } from "../data/announcements";
import { useWidgetStore } from "../stores/widgetStore";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import { useActionHistoryBootstrap } from "../hooks/useActionHistoryBootstrap";
import { collectBugReportContext } from "../utils/bugReportContext";

const svg = () => new File(["<svg/>"], "art.svg", { type: "image/svg+xml" });

beforeEach(() => {
  localStorage.clear();
  useConverterStore.setState({ ...DEFAULT_STATE, imageFile: svg(), modeling_mode: ModelingMode.VECTOR });
  useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "zh" });
  useWidgetStore.setState({ activeTab: "converter" });
  useActionHistoryStore.getState()._resetForTests();
});
afterEach(() => {
  cleanup();
  useActionHistoryStore.getState()._resetForTests();
  useConverterStore.setState({ ...DEFAULT_STATE });
});

describe("SVG source compensation controls", () => {
  it("offers an optional switch and physical thresholds for SVG vector artwork", () => {
    render(<I18nProvider><SvgHoleCompensationSettings /></I18nProvider>);
    const toggle = screen.getByRole("switch", { name: /SVG/ });
    expect(toggle).not.toBeChecked();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toBeChecked();
    const area = screen.getByRole("spinbutton", { name: /mm²/ });
    const width = screen.getByRole("spinbutton", { name: /mm\)/ });
    expect(area).toHaveValue(0.5);
    expect(width).toHaveValue(0.1);
    fireEvent.change(area, { target: { value: "0" } });
    expect(useConverterStore.getState().svg_hole_max_area_mm2).toBe(0);
    fireEvent.click(toggle);
    expect(toggle).not.toBeChecked();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(useConverterStore.getState().svg_hole_compensation_enabled).toBe(false);
  });

  it("clearly disables the feature outside SVG vector mode", () => {
    useConverterStore.setState({ imageFile: null, modeling_mode: ModelingMode.HIGH_FIDELITY });
    render(<I18nProvider><SvgHoleCompensationSettings /></I18nProvider>);
    expect(screen.getByRole("switch", { name: /SVG/ })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/SVG.*矢量/);
  });

  it("clears the enabled UI when switching to a raster source", () => {
    useConverterStore.setState({ svg_hole_compensation_enabled: true });
    render(<I18nProvider><SvgHoleCompensationSettings /></I18nProvider>);
    act(() => useConverterStore.getState().setImageFile(new File(["png"], "art.png", { type: "image/png" })));
    expect(screen.getByRole("switch", { name: /SVG/ })).not.toBeChecked();
    expect(screen.getByRole("switch", { name: /SVG/ })).toBeDisabled();
  });

  it("provides equivalent English controls and explains that intentional details may be filled", () => {
    useSettingsStore.setState({ language: "en" });
    render(<I18nProvider><SvgHoleCompensationSettings /></I18nProvider>);
    expect(screen.getByRole("switch", { name: /SVG hole compensation/ })).toBeEnabled();
    expect(translations.svg_hole_compensation_hint.zh).toContain("有意保留");
    expect(translations.svg_hole_compensation_hint.en).toMatch(/intentional/i);
  });

  it("announces the optional source-level compensation in both languages", () => {
    const items = ANNOUNCEMENTS.find((entry) => entry.version === "2026-09-13")?.sections.flatMap((section) => section.items) ?? [];
    expect(items.some((item) => item.zh.includes("SVG 小洞补偿") && item.zh.includes("默认关闭") && item.en.includes("off by default"))).toBe(true);
  });

  it.each(["toggle", "area", "width"])("captures %s changes in actual action history and feedback", (field) => {
    renderHook(() => useActionHistoryBootstrap());
    act(() => {
      const store = useConverterStore.getState();
      if (field === "toggle") store.setSvgHoleCompensationEnabled(true);
      if (field === "area") store.setSvgHoleMaxAreaMm2(0);
      if (field === "width") store.setSvgHoleMaxWidthMm(0.2);
    });
    const key = field === "toggle" ? "svg_hole_compensation_enabled"
      : field === "area" ? "svg_hole_max_area_mm2" : "svg_hole_max_width_mm";
    const value = useConverterStore.getState()[key];
    const entry = useActionHistoryStore.getState().history.find((event) => event.changed_fields?.[key]);
    expect(entry?.action_type).toBe("advanced_param_change");
    expect(entry?.snapshot.advanced_params).toHaveProperty(`generation.${key}`, value);
    const report = collectBugReportContext();
    expect(report.advanced_params).toHaveProperty(`generation.${key}`, value);
    expect(JSON.stringify(report.advanced_params)).not.toContain("data:image");
  });
});
