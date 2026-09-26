import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const electronMocks = vi.hoisted(() => ({
  canPick: vi.fn(() => true),
  pick: vi.fn<() => Promise<string | null>>(),
}));

vi.mock("../integrations/electron", () => ({
  canPickGeneratedFileDirectory: electronMocks.canPick,
  pickGeneratedFileDirectory: electronMocks.pick,
}));

import GeneratedFileDirectorySetting from "../components/settings/GeneratedFileDirectorySetting";
import { I18nProvider } from "../i18n/context";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

function renderSetting() {
  return render(
    <I18nProvider>
      <GeneratedFileDirectorySetting />
    </I18nProvider>,
  );
}

describe("GeneratedFileDirectorySetting", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    electronMocks.canPick.mockReturnValue(true);
    useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "zh" });
  });

  it("is hidden where the save location cannot be controlled (web)", () => {
    electronMocks.canPick.mockReturnValue(false);
    renderSetting();
    expect(
      screen.queryByTestId("settings-generated-file-directory-section"),
    ).not.toBeInTheDocument();
  });

  it("shows the system default until a folder is chosen", async () => {
    electronMocks.pick.mockResolvedValueOnce("D:\\Prints");
    renderSetting();

    expect(screen.getByTestId("settings-generated-file-directory-value"))
      .toHaveTextContent("系统默认位置");
    expect(screen.getByRole("button", { name: "恢复默认" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "选择文件夹" }));

    await waitFor(() =>
      expect(useSettingsStore.getState().generatedFileDirectory).toBe("D:\\Prints"),
    );
    expect(screen.getByTestId("settings-generated-file-directory-value"))
      .toHaveTextContent("D:\\Prints");
  });

  it("keeps the current folder when the picker is canceled and can reset", async () => {
    useSettingsStore.setState({ generatedFileDirectory: "D:\\Prints" });
    electronMocks.pick.mockResolvedValueOnce(null);
    renderSetting();

    fireEvent.click(screen.getByRole("button", { name: "选择文件夹" }));
    await waitFor(() => expect(electronMocks.pick).toHaveBeenCalledOnce());
    expect(useSettingsStore.getState().generatedFileDirectory).toBe("D:\\Prints");

    fireEvent.click(screen.getByRole("button", { name: "恢复默认" }));
    expect(useSettingsStore.getState().generatedFileDirectory).toBe("");
  });

  it("reports a picker failure", async () => {
    electronMocks.pick.mockRejectedValueOnce(new Error("ipc down"));
    renderSetting();

    fireEvent.click(screen.getByRole("button", { name: "选择文件夹" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("无法打开文件夹选择器");
  });
});
