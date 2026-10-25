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

  it("explains long-edge sizing without the redundant naming subtitle", () => {
    useConverterStore.setState({ target_width_mm: 150, target_height_mm: 100, preferredSizeAxis: "height" });
    show();
    fireEvent.click(screen.getByRole("button", { name: "保存为预设" }));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.queryByText("给这套设置起个名字，下次一键套用。")).not.toBeInTheDocument();
    expect(dialog.getByText(/长边 150 mm/)).toBeInTheDocument();
    expect(dialog.getByText(/尺寸记录长边/)).toBeInTheDocument();
  });

  it("starts optional groups unchecked on every save and only saves selected groups", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "保存为预设" }));
    for (const name of ["高级设置", "外轮廓设置", "透明镀层设置"]) {
      expect(screen.getByRole("checkbox", { name })).not.toBeChecked();
    }
    expect(within(screen.getByRole("dialog")).queryByText(/涂层关闭/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "透明镀层设置" }));
    fireEvent.change(screen.getByRole("textbox", { name: "预设名称" }), { target: { value: "镀层预设" } });
    fireEvent.click(screen.getByRole("button", { name: "保存预设" }));
    const saved = useSettingsStore.getState().conversionPreferences.presets[0].parameters;
    expect(saved).toHaveProperty("enable_coating", false);
    expect(saved).not.toHaveProperty("enable_outline");
    expect(saved).not.toHaveProperty("enable_cleanup");
    act(() => useConverterStore.getState().setEnableOutline(true));
    expect(screen.queryByText("已修改")).not.toBeInTheDocument();
    act(() => useConverterStore.getState().setEnableCoating(true));
    expect(screen.getByText("已修改")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存为预设" }));
    expect(screen.getByRole("checkbox", { name: "透明镀层设置" })).not.toBeChecked();
  });

  it.each([true, false])("shows material layer height with dynamic mode %s", dynamic => {
    useConverterStore.setState({ source_version: "material", materialLayerHeightMm: 0.08,
      materialDynamicLayerCountEnabled: dynamic, materialMinLayerCount: 4, materialMaxLayerCount: 10,
      materialLayerCount: 8 });
    show();
    fireEvent.click(screen.getByRole("button", { name: "保存为预设" }));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByText(/层高 0.08 mm/)).toBeInTheDocument();
    expect(dialog.getByText(dynamic ? /动态 4–10 层/ : /固定 8 层/)).toBeInTheDocument();
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
