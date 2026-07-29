import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/context";
import { translations } from "../i18n/translations";
import { useSettingsStore } from "../stores/settingsStore";
import { WorkshopPanel } from "../workshop/WorkshopPanel";
import { useWorkshopStore } from "../workshop/store";
import type { WorkshopHostServices } from "../workshop/types";
import beadWorkshopModuleSource from "../workshop/modules/bead/BeadWorkshopModule.tsx?raw";

function fakeHost(): WorkshopHostServices {
  return {
    files: {
      pickImage: vi.fn().mockResolvedValue(null),
      decodeImage: vi.fn(),
      encodePng: vi.fn(),
    },
    projects: {
      save: vi.fn(),
      load: vi.fn().mockResolvedValue(null),
      latest: vi.fn().mockResolvedValue(null),
      remove: vi.fn(),
    },
    ui: {
      getLocale: () => "zh",
      getTheme: () => "light",
      translate: (key) => translations[key]?.zh ?? key,
    },
    status: {
      reportProgress: vi.fn(),
      reportError: vi.fn(),
      reportDiagnostics: vi.fn(),
    },
    handoffImage: vi.fn(),
  };
}

function renderPanel(host: WorkshopHostServices = fakeHost()) {
  render(
    <I18nProvider>
      <WorkshopPanel createHost={() => host} />
    </I18nProvider>,
  );
  return host;
}

describe("WorkshopPanel", () => {
  beforeEach(() => {
    localStorage.clear();
    useSettingsStore.setState({ language: "zh", theme: "light" });
    useWorkshopStore.setState({
      activeModuleId: null,
      lastProjectIds: {},
      pendingRecipeSource: null,
      diagnostics: null,
    });
  });

  it("shows the whitelisted official bead module and opens it through the registry", () => {
    renderPanel();

    expect(
      screen.getByRole("heading", { name: "创意工坊" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "拼豆模式" }),
    ).toBeInTheDocument();
    expect(screen.getByText("官方")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "打开" }));

    expect(
      screen.getByRole("heading", { name: "拼豆模式" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "选择拼豆图纸" }),
    ).toBeInTheDocument();
  });

  it("calls only the injected host picker and can return to the gallery", async () => {
    const host = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "打开" }));

    fireEvent.click(
      screen.getByRole("button", { name: "选择拼豆图纸" }),
    );

    await waitFor(() => {
      expect(host.files.pickImage).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(screen.getByRole("button", { name: "返回创意工坊" }));
    expect(
      screen.getByRole("heading", { name: "创意工坊" }),
    ).toBeInTheDocument();
  });

  it("keeps pending recipe payloads and diagnostics out of localStorage", () => {
    const source = {
      manifestSchemaVersion: 1 as const,
      moduleId: "lumina.bead-pattern",
      moduleVersion: "1.0.0",
      projectSchemaVersion: "bead-project/v1",
      renderSchemaVersion: "bead-render/v1",
      payload: { secretMatrix: [1, 2, 3] },
    };
    useWorkshopStore.getState().openRecipe(source);
    useWorkshopStore.getState().setDiagnostics({
      projectSchemaVersion: "bead-project/v1",
      inputMode: "hard-pixel",
      rows: 2,
      columns: 2,
      compression: 50,
      errorCode: null,
    });

    const persisted = localStorage.getItem("lumina-workshop-shell") ?? "";
    expect(persisted).not.toContain("secretMatrix");
    expect(persisted).not.toContain("hard-pixel");
    expect(persisted).toContain("lumina.bead-pattern");
  });

  it("keeps the official module independent from converter and network state", () => {
    expect(beadWorkshopModuleSource).not.toMatch(
      /stores\/converter|stores\/widgetStore/,
    );
    expect(beadWorkshopModuleSource).not.toMatch(
      /\bindexedDB\b|api\/|axios|fetch\(/,
    );
  });
});
