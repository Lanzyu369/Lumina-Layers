import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import ConversionPresets from "../components/sections/ConversionPresets";
import { I18nProvider } from "../i18n/context";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";
import { useConverterStore, DEFAULT_STATE } from "../stores/converter";
import { captureConversionParameters } from "../stores/conversionPreferences";
import { bindConversionPreferences } from "../hooks/useConversionPreferences";

describe("conversion preset controls", () => {
  beforeEach(() => {
    localStorage.clear();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "zh" });
    useConverterStore.setState({ ...DEFAULT_STATE, lut_names: [], lut_name: "" });
  });

  const show = () => render(<I18nProvider><ConversionPresets /></I18nProvider>);
  const seed = () => {
    const parameters = captureConversionParameters(useConverterStore.getState());
    useSettingsStore.getState().setConversionPreferences({ last: parameters,
      presets: [{ id: "art", name: "常用板画", parameters }] });
  };
  const select = (name: RegExp) => {
    fireEvent.click(screen.getByRole("combobox", { name: "预设" }));
    fireEvent.click(screen.getByRole("option", { name }));
  };

  it("saves named presets durably and rejects duplicate names", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "保存为预设" }));
    fireEvent.change(screen.getByRole("textbox", { name: "预设名称" }), { target: { value: "常用板画" } });
    fireEvent.click(screen.getByRole("button", { name: "保存预设" }));
    expect(useSettingsStore.getState().conversionPreferences.presets[0].name).toBe("常用板画");
    expect(localStorage.getItem("lumina-settings")).toContain("常用板画");
    fireEvent.click(screen.getByRole("button", { name: "保存为预设" }));
    fireEvent.change(screen.getByRole("textbox", { name: "预设名称" }), { target: { value: " 常用板画 " } });
    fireEvent.click(screen.getByRole("button", { name: "保存预设" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(useSettingsStore.getState().conversionPreferences.presets).toHaveLength(1);
  });

  it("updates a selected preset only when the user explicitly requests it", () => {
    seed(); show(); select(/^常用板画/);
    act(() => useConverterStore.getState().setTargetWidthMm(180));
    expect(screen.getByText("已修改")).toBeInTheDocument();
    expect(useSettingsStore.getState().conversionPreferences.presets[0].parameters.size_mm).toBe(60);
    fireEvent.click(screen.getByRole("button", { name: "更新预设" }));
    expect(useSettingsStore.getState().conversionPreferences.presets[0].parameters.size_mm).toBe(180);
    expect(screen.queryByText("已修改")).not.toBeInTheDocument();
  });

  it("renames and deletes a selected preset while keeping current parameters", () => {
    seed(); show(); select(/^常用板画/); select(/^重命名当前预设$/);
    fireEvent.change(screen.getByRole("textbox", { name: "预设名称" }), { target: { value: "新的板画" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "重命名当前预设" }));
    expect(useSettingsStore.getState().conversionPreferences.presets[0].name).toBe("新的板画");
    select(/^删除当前预设$/);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "删除当前预设" }));
    expect(useSettingsStore.getState().conversionPreferences.presets).toEqual([]);
    expect(useConverterStore.getState().target_width_mm).toBe(60);
  });

  it("restores the selected preset name and unsaved modifications after a full reload", async () => {
    seed();
    let stop = bindConversionPreferences();
    const view = show();
    select(/^常用板画/);
    act(() => useConverterStore.getState().setTargetWidthMm(180));
    const stored = localStorage.getItem("lumina-settings")!;
    view.unmount(); stop();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    useConverterStore.setState({ ...DEFAULT_STATE });
    localStorage.setItem("lumina-settings", stored);
    await useSettingsStore.persist.rehydrate();
    stop = bindConversionPreferences();
    try {
      show();
      expect(screen.getByRole("combobox", { name: "预设" })).toHaveTextContent("常用板画");
      expect(screen.getByText("已修改")).toBeInTheDocument();
      expect(useConverterStore.getState().target_width_mm).toBe(180);
      expect(useSettingsStore.getState().conversionPreferences.presets[0].parameters.size_mm).toBe(60);
    } finally { stop(); }
  });

  it("shows imported project parameters separately from the remembered preset", () => {
    seed(); show(); select(/^常用板画/);
    act(() => useConverterStore.getState().importRecipeState({ target_width_mm: 93 },
      new File(["project"], "project.png", { type: "image/png" })));
    expect(screen.getByRole("combobox", { name: "预设" })).toHaveTextContent("当前项目参数");
    expect(screen.queryByText("已修改")).not.toBeInTheDocument();
  });
});
