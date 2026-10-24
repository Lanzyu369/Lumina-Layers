import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../../i18n/context";
import { translations } from "../../../i18n/translations";
import { DEFAULT_SETTINGS, useSettingsStore } from "../../../stores/settingsStore";
import * as systemApi from "../../../api/system";
import Custom3mfTemplateSettings from "../Custom3mfTemplateSettings";

vi.unmock("../../../i18n/context");

vi.mock("../../../api/system", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../../api/system")>(),
  getCustom3mfTemplates: vi.fn(),
  saveSettings: vi.fn(),
}));

const template = {
  id: "template-1",
  name: "Studio template",
  printer_model: "Bambu Lab A1",
  slicer: "BambuStudio",
  nozzle_diameter: ["0.4"],
  filament_count: 4,
};

function renderSettings() {
  return render(<I18nProvider><Custom3mfTemplateSettings /></I18nProvider>);
}

describe("3MF template guidance", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "zh" });
    vi.mocked(systemApi.getCustom3mfTemplates).mockResolvedValue([template]);
    vi.mocked(systemApi.saveSettings).mockResolvedValue({ status: "success", message: "ok" });
  });

  it.each(["zh", "en"] as const)("keeps general guidance in help for built-in settings (%s)", async (language) => {
    useSettingsStore.setState({ language });
    renderSettings();
    await waitFor(() => expect(screen.getByRole("combobox")).toBeEnabled());

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(translations["settings.template_compatibility_note"][language])).not.toBeInTheDocument();
    expect(screen.queryByText(translations["settings.template_excluded"][language])).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /单盘|single-plate/ }));
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent(translations["settings.template_summary"][language]);
    expect(tooltip).toHaveTextContent(translations["settings.template_hint"][language]);
    expect(tooltip).toHaveTextContent(translations["settings.template_excluded"][language]);
    expect(useSettingsStore.getState().custom3mfTemplateId).toBeNull();
    expect(systemApi.saveSettings).not.toHaveBeenCalled();
  });

  it.each(["zh", "en"] as const)("shows export limits only while a custom template is selected (%s)", async (language) => {
    useSettingsStore.setState({ language });
    renderSettings();
    const picker = screen.getByRole("combobox");
    await waitFor(() => expect(picker).toBeEnabled());
    fireEvent.click(picker);
    fireEvent.click(screen.getByRole("option", { name: template.name }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      translations["settings.template_active_scope_hint"][language],
    );
    expect(screen.getByText(/Bambu Lab A1 · BambuStudio · 0.4 mm/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /单盘|single-plate/ }));
    expect(await screen.findByRole("tooltip")).not.toHaveTextContent(
      translations["settings.template_excluded"][language],
    );
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(picker);
    fireEvent.click(screen.getByRole("option", { name: translations["settings.template_builtin"][language] }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/Bambu Lab A1 · BambuStudio · 0.4 mm/)).not.toBeInTheDocument();
  });

  it("keeps missing-template recovery instructions visible", async () => {
    useSettingsStore.setState({ custom3mfTemplateId: "missing-template" });
    renderSettings();
    expect(await screen.findByText(translations["settings.template_missing"].zh)).toBeInTheDocument();
    expect(screen.queryByText(translations["settings.template_active_scope_hint"].zh)).not.toBeInTheDocument();
    const picker = screen.getByRole("combobox");
    fireEvent.click(picker);
    fireEvent.click(screen.getByRole("option", { name: translations["settings.template_builtin"].zh }));
    expect(screen.queryByText(translations["settings.template_missing"].zh)).not.toBeInTheDocument();
  });

  it("keeps template loading errors visible without opening help", async () => {
    vi.mocked(systemApi.getCustom3mfTemplates).mockRejectedValue(new Error("offline"));
    renderSettings();
    expect(await screen.findByText(translations["settings.template_load_error"].zh)).toBeInTheDocument();
  });

  it("opens the file chooser from the dropdown without changing the selected template", async () => {
    useSettingsStore.setState({ custom3mfTemplateId: template.id });
    renderSettings();
    const picker = screen.getByRole("combobox");
    await waitFor(() => expect(picker).toBeEnabled());
    const fileInput = screen.getByLabelText(translations["settings.template_file"].zh);
    const chooseFile = vi.spyOn(fileInput, "click");
    expect(screen.queryByRole("button", { name: translations["settings.template_choose_file"].zh })).not.toBeInTheDocument();
    fireEvent.click(picker);
    fireEvent.click(screen.getByRole("option", { name: translations["settings.template_choose_file"].zh }));
    expect(chooseFile).toHaveBeenCalledTimes(1);
    expect(useSettingsStore.getState().custom3mfTemplateId).toBe(template.id);
    expect(picker).toHaveTextContent(template.name);
    expect(picker).toHaveAttribute("aria-expanded", "false");
    expect(systemApi.saveSettings).not.toHaveBeenCalled();
  });
});
