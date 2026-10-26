import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { launchSlicer } from "../api/slicer";
import SlicerSelector from "../components/sections/SlicerSelector";
import { I18nProvider } from "../i18n/context";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { useSlicerStore } from "../stores/slicerStore";

const { assertResourceDownloadAvailableMock } = vi.hoisted(() => ({
  assertResourceDownloadAvailableMock: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    assertResourceDownloadAvailable: assertResourceDownloadAvailableMock,
  };
});

vi.mock("../api/slicer", () => ({
  detectSlicers: vi.fn().mockResolvedValue({
    slicers: [
      {
        id: "bambu_studio",
        display_name: "Bambu Studio",
        exe_path: "/Applications/Bambu Studio.app",
      },
      {
        id: "orca_slicer",
        display_name: "OrcaSlicer",
        exe_path: "/Applications/OrcaSlicer.app",
      },
    ],
  }),
  launchSlicer: vi.fn().mockResolvedValue({
    status: "success",
    message: "opened",
  }),
  validateCustomSlicerPath: vi.fn(),
}));

describe("SlicerSelector settings linkage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      slicerSoftware: "OrcaSlicer",
      lastSlicerId: "bambu_studio",
    });
    useSlicerStore.setState({
      slicers: [
        {
          id: "bambu_studio",
          display_name: "Bambu Studio",
          exe_path: "/Applications/Bambu Studio.app",
        },
        {
          id: "orca_slicer",
          display_name: "OrcaSlicer",
          exe_path: "/Applications/OrcaSlicer.app",
        },
      ],
      selectedSlicerId: "bambu_studio",
      isDetecting: false,
      isLaunching: false,
      isValidatingCustomPath: false,
      launchMessage: null,
      customPathMessage: null,
      customPathError: null,
      error: null,
      detectSlicers: vi.fn().mockResolvedValue(undefined),
    });
    assertResourceDownloadAvailableMock.mockReset();
  });

  it.each([
    { state: "source not ready", canSubmit: false, isDetecting: false, isLaunching: false, disabled: true },
    { state: "detecting slicers", canSubmit: true, isDetecting: true, isLaunching: false, disabled: true },
    { state: "launching slicer", canSubmit: true, isDetecting: false, isLaunching: true, disabled: true },
    { state: "ready", canSubmit: true, isDetecting: false, isLaunching: false, disabled: false },
  ])("keeps the action visible while $state", ({ canSubmit, isDetecting, isLaunching, disabled }) => {
    useSlicerStore.setState({ isDetecting, isLaunching });
    render(
      <I18nProvider>
        <SlicerSelector
          threemfDiskPath="/tmp/calibration.3mf"
          downloadUrl="/api/files/calibration"
          canSubmit={canSubmit}
          onAutoGenerate={async () => "/tmp/calibration.3mf"}
        />
      </I18nProvider>,
    );

    const action = screen.getByRole("button", { name: "在 OrcaSlicer 中打开" });
    const menu = screen.getByRole("button", { name: "切换切片软件列表" });
    expect(action).toBeVisible();
    if (disabled) {
      expect(action).toBeDisabled();
      expect(menu).toBeDisabled();
      fireEvent.click(action);
      expect(vi.mocked(launchSlicer)).not.toHaveBeenCalled();
    } else {
      expect(action).toBeEnabled();
      expect(menu).toBeEnabled();
    }
  });

  it("prevents a second generation while the first is pending", async () => {
    let finishGeneration!: (value: string | null) => void;
    const onAutoGenerate = vi.fn(() => new Promise<string | null>((resolve) => {
      finishGeneration = resolve;
    }));
    render(
      <I18nProvider>
        <SlicerSelector
          threemfDiskPath={null}
          downloadUrl={null}
          canSubmit
          onAutoGenerate={onAutoGenerate}
        />
      </I18nProvider>,
    );

    const action = screen.getByRole("button", { name: "生成并在 OrcaSlicer 中打开" });
    const menu = screen.getByRole("button", { name: "切换切片软件列表" });
    expect(action).toBeEnabled();
    fireEvent.click(action);
    expect(action).toBeDisabled();
    expect(menu).toBeDisabled();
    fireEvent.click(action);
    expect(onAutoGenerate).toHaveBeenCalledOnce();

    await act(async () => finishGeneration(null));

    expect(action).toBeEnabled();
    expect(menu).toBeEnabled();
  });

  it("prefers the slicer selected in settings over stale selectedSlicerId", async () => {
    render(
      <I18nProvider>
        <SlicerSelector
          threemfDiskPath="/tmp/calibration.3mf"
          downloadUrl="/api/files/calibration"
          canSubmit
          onAutoGenerate={async () => "/tmp/calibration.3mf"}
        />
      </I18nProvider>,
    );

    const openButton = screen.getByRole("button", {
      name: "在 OrcaSlicer 中打开",
    });
    expect(openButton).toBeInTheDocument();
  });

  it("shows the active logo on the action and each detected logo in the menu", async () => {
    render(
      <I18nProvider>
        <SlicerSelector
          threemfDiskPath="/tmp/calibration.3mf"
          downloadUrl="/api/files/calibration"
          canSubmit
          onAutoGenerate={async () => "/tmp/calibration.3mf"}
        />
      </I18nProvider>,
    );

    const openButton = screen.getByRole("button", {
      name: "在 OrcaSlicer 中打开",
    });
    expect(
      within(openButton).getByTestId("slicer-logo-OrcaSlicer"),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "切换切片软件列表" }),
    );

    expect(
      within(screen.getByRole("option", { name: "Bambu Studio" })).getByTestId(
        "slicer-logo-BambuStudio",
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("option", { name: /OrcaSlicer/ })).getByTestId(
        "slicer-logo-OrcaSlicer",
      ),
    ).toBeInTheDocument();
  });

    useSlicerStore.setState({ isLaunching: true });

    render(
      <I18nProvider>
        <SlicerSelector
          threemfDiskPath="/tmp/calibration.3mf"
          downloadUrl="/api/files/calibration"
          canSubmit
          onAutoGenerate={async () => "/tmp/calibration.3mf"}
        />
      </I18nProvider>,
    );

    const openButton = screen.getByRole("button", {
      name: "在 OrcaSlicer 中打开",
    });
  });

  it("does not fall back to Bambu Studio when the settings slicer is missing", async () => {
    useSlicerStore.setState({
      slicers: [
        {
          id: "bambu_studio",
          display_name: "Bambu Studio",
          exe_path: "/Applications/Bambu Studio.app",
        },
      ],
      selectedSlicerId: "bambu_studio",
    });

    render(
      <I18nProvider>
        <SlicerSelector
          threemfDiskPath="/tmp/calibration.3mf"
          downloadUrl="/api/files/calibration"
          canSubmit
          onAutoGenerate={async () => "/tmp/calibration.3mf"}
        />
      </I18nProvider>,
    );

    expect(
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "在 Bambu Studio 中打开" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载 3MF" })).toBeInTheDocument();
  });

  it("launches with an explicit settings-linked slicer id", async () => {
    await useSlicerStore
      .getState()
      .launchSlicer("/tmp/calibration.3mf", "orca_slicer");

    expect(vi.mocked(launchSlicer)).toHaveBeenCalledWith({
      slicer_id: "orca_slicer",
      file_path: "/tmp/calibration.3mf",
    });
  });

  it("opens a generated /api/files artifact without requiring a disk path", async () => {
    const onAutoGenerate = vi.fn(async () => null);

    render(
      <I18nProvider>
        <SlicerSelector
          threemfDiskPath={null}
          downloadUrl="/api/files/calibration"
          canSubmit
          onAutoGenerate={onAutoGenerate}
        />
      </I18nProvider>,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "在 OrcaSlicer 中打开" }),
    );

    await waitFor(() => {
      expect(vi.mocked(launchSlicer)).toHaveBeenCalledWith({
        slicer_id: "orca_slicer",
        download_url: "/api/files/calibration",
      });
    });
    expect(onAutoGenerate).not.toHaveBeenCalled();
  });

  it("does not clean up the converter session when a direct 3MF download is expired", async () => {
    assertResourceDownloadAvailableMock.mockRejectedValueOnce(
      new Error("The requested resource was not found or has expired."),
    );
    useSlicerStore.setState({
      slicers: [],
      selectedSlicerId: null,
    });
    const onArtifactAction = vi.fn();
    const anchorClick = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    const createElementSpy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tagName: string, options?: ElementCreationOptions) => {
        if (tagName.toLowerCase() === "a") {
          return {
            href: "",
            download: "",
            click: anchorClick,
          } as unknown as HTMLAnchorElement;
        }
        return originalCreateElement(tagName, options);
      });

    try {
      render(
        <I18nProvider>
          <SlicerSelector
            threemfDiskPath="/tmp/model.3mf"
            downloadUrl="/api/files/expired-model"
            canSubmit
            onAutoGenerate={async () => "/tmp/model.3mf"}
            onArtifactAction={onArtifactAction}
          />
        </I18nProvider>,
      );

      fireEvent.click(screen.getByRole("button", { name: "下载 3MF" }));

      expect(
        await screen.findByText(
          /The requested resource was not found or has expired\./,
        ),
      ).toBeInTheDocument();
      expect(assertResourceDownloadAvailableMock).toHaveBeenCalledWith(
        "/api/files/expired-model",
      );
      expect(anchorClick).not.toHaveBeenCalled();
      expect(onArtifactAction).not.toHaveBeenCalled();
    } finally {
      createElementSpy.mockRestore();
    }
  });

  it("shows a readable message when direct 3MF download validation cannot reach the server", async () => {
    assertResourceDownloadAvailableMock.mockRejectedValueOnce(
      new Error("The request did not receive a server response. Make sure the Lumina backend is running, check the network connection, and try again."),
    );
    useSlicerStore.setState({
      slicers: [],
      selectedSlicerId: null,
    });
    const onArtifactAction = vi.fn();
    const anchorClick = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    const createElementSpy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tagName: string, options?: ElementCreationOptions) => {
        if (tagName.toLowerCase() === "a") {
          return {
            href: "",
            download: "",
            click: anchorClick,
          } as unknown as HTMLAnchorElement;
        }
        return originalCreateElement(tagName, options);
      });

    try {
      render(
        <I18nProvider>
          <SlicerSelector
            threemfDiskPath="/tmp/model.3mf"
            downloadUrl="/api/files/model"
            canSubmit
            onAutoGenerate={async () => "/tmp/model.3mf"}
            onArtifactAction={onArtifactAction}
          />
        </I18nProvider>,
      );

      fireEvent.click(screen.getByRole("button", { name: "下载 3MF" }));

      expect(
        await screen.findByText(
          "The request did not receive a server response. Make sure the Lumina backend is running, check the network connection, and try again.",
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Failed to fetch/)).not.toBeInTheDocument();
      expect(assertResourceDownloadAvailableMock).toHaveBeenCalledWith(
        "/api/files/model",
      );
      expect(anchorClick).not.toHaveBeenCalled();
      expect(onArtifactAction).not.toHaveBeenCalled();
    } finally {
      createElementSpy.mockRestore();
    }
  });

  it("normalizes raw HTTP status text from direct 3MF download validation", async () => {
    assertResourceDownloadAvailableMock.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );
    useSlicerStore.setState({
      slicers: [],
      selectedSlicerId: null,
    });
    const onArtifactAction = vi.fn();
    const anchorClick = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    const createElementSpy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tagName: string, options?: ElementCreationOptions) => {
        if (tagName.toLowerCase() === "a") {
          return {
            href: "",
            download: "",
            click: anchorClick,
          } as unknown as HTMLAnchorElement;
        }
        return originalCreateElement(tagName, options);
      });

    try {
      render(
        <I18nProvider>
          <SlicerSelector
            threemfDiskPath="/tmp/model.3mf"
            downloadUrl="/api/files/model"
            canSubmit
            onAutoGenerate={async () => "/tmp/model.3mf"}
            onArtifactAction={onArtifactAction}
          />
        </I18nProvider>,
      );

      fireEvent.click(screen.getByRole("button", { name: "下载 3MF" }));

      expect(
        await screen.findByText("服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。"),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(/Request failed with status code 500/i),
      ).not.toBeInTheDocument();
      expect(assertResourceDownloadAvailableMock).toHaveBeenCalledWith(
        "/api/files/model",
      );
      expect(anchorClick).not.toHaveBeenCalled();
      expect(onArtifactAction).not.toHaveBeenCalled();
    } finally {
      createElementSpy.mockRestore();
    }
  });

  it("cleans up only after a direct 3MF download URL validates successfully", async () => {
    assertResourceDownloadAvailableMock.mockResolvedValueOnce(undefined);
    useSlicerStore.setState({
      slicers: [],
      selectedSlicerId: null,
    });
    const onArtifactAction = vi.fn();
    const anchorClick = vi.fn();
    const anchor = {
      href: "",
      download: "",
      click: anchorClick,
    } as unknown as HTMLAnchorElement;
    const originalCreateElement = document.createElement.bind(document);
    const createElementSpy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tagName: string, options?: ElementCreationOptions) => {
        if (tagName.toLowerCase() === "a") {
          return anchor;
        }
        return originalCreateElement(tagName, options);
      });

    try {
      render(
        <I18nProvider>
          <SlicerSelector
            threemfDiskPath="/tmp/model.3mf"
            downloadUrl="/api/files/model"
            canSubmit
            onAutoGenerate={async () => "/tmp/model.3mf"}
            onArtifactAction={onArtifactAction}
          />
        </I18nProvider>,
      );

      fireEvent.click(screen.getByRole("button", { name: "下载 3MF" }));

      await waitFor(() => {
        expect(assertResourceDownloadAvailableMock).toHaveBeenCalledWith(
          "/api/files/model",
        );
      });
      expect(anchor.href).toBe("/api/files/model");
      expect(anchor.download).toBe("");
      expect(anchorClick).toHaveBeenCalledOnce();
      expect(onArtifactAction).toHaveBeenCalledOnce();
    } finally {
      createElementSpy.mockRestore();
    }
  });

  describe("dropdown download entry with a detected slicer", () => {
    function stubAnchor() {
      const anchorClick = vi.fn();
      const anchor = { href: "", download: "", click: anchorClick } as unknown as HTMLAnchorElement;
      const originalCreateElement = document.createElement.bind(document);
      const spy = vi
        .spyOn(document, "createElement")
        .mockImplementation((tagName: string, options?: ElementCreationOptions) =>
          tagName.toLowerCase() === "a" ? anchor : originalCreateElement(tagName, options),
        );
      return { anchor, anchorClick, restore: () => spy.mockRestore() };
    }

    it("generates first and then downloads when no 3MF exists yet", async () => {
      assertResourceDownloadAvailableMock.mockResolvedValueOnce(undefined);
      let latestDownloadUrl: string | null = null;
      const onAutoGenerate = vi.fn(async () => {
        latestDownloadUrl = "/api/files/fresh-model";
        return latestDownloadUrl;
      });
      const onArtifactAction = vi.fn();
      const { anchor, anchorClick, restore } = stubAnchor();

      try {
        render(
          <I18nProvider>
            <SlicerSelector
              threemfDiskPath={null}
              downloadUrl={null}
              canSubmit
              onAutoGenerate={onAutoGenerate}
              getLatestDownloadUrl={() => latestDownloadUrl}
              onArtifactAction={onArtifactAction}
            />
          </I18nProvider>,
        );

        fireEvent.click(screen.getByRole("button", { name: "切换切片软件列表" }));
        const entry = screen.getByRole("button", { name: "生成并下载 3MF" });
        expect(entry).toBeEnabled();
        fireEvent.click(entry);

        await waitFor(() => expect(anchorClick).toHaveBeenCalledOnce());
        expect(onAutoGenerate).toHaveBeenCalledOnce();
        expect(anchor.href).toBe("/api/files/fresh-model");
        expect(vi.mocked(launchSlicer)).not.toHaveBeenCalled();
        expect(onArtifactAction).toHaveBeenCalledOnce();
      } finally {
        restore();
      }
    });

    it("downloads the existing 3MF without regenerating", async () => {
      assertResourceDownloadAvailableMock.mockResolvedValueOnce(undefined);
      const onAutoGenerate = vi.fn(async () => null);
      const { anchor, anchorClick, restore } = stubAnchor();

      try {
        render(
          <I18nProvider>
            <SlicerSelector
              threemfDiskPath={null}
              downloadUrl="/api/files/model"
              canSubmit
              onAutoGenerate={onAutoGenerate}
              onArtifactAction={vi.fn()}
            />
          </I18nProvider>,
        );

        fireEvent.click(screen.getByRole("button", { name: "切换切片软件列表" }));
        fireEvent.click(screen.getByRole("button", { name: "下载 3MF" }));

        await waitFor(() => expect(anchorClick).toHaveBeenCalledOnce());
        expect(anchor.href).toBe("/api/files/model");
        expect(onAutoGenerate).not.toHaveBeenCalled();
      } finally {
        restore();
      }
    });

    it("stays disabled while the image or source is not ready", () => {
      render(
        <I18nProvider>
          <SlicerSelector
            threemfDiskPath={null}
            downloadUrl={null}
            canSubmit={false}
            onAutoGenerate={async () => null}
          />
        </I18nProvider>,
      );

      expect(screen.getByRole("button", { name: "切换切片软件列表" })).toBeDisabled();
    });
  });
});
