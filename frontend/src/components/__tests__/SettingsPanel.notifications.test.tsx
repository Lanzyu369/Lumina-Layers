import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

vi.mock("../../api/system", () => ({
  clearCache: vi.fn(),
  getMachineRegistryAssetUrl: (path?: string) =>
    path ? `/api/system/machine-registry/assets/${path}` : null,
  getPrinters: vi.fn(),
  getSlicers: vi.fn(),
  saveSettings: vi.fn(),
}));

vi.mock("../../utils/retryAsync", () => ({
  retryAsync: vi.fn((operation: () => Promise<unknown>) => operation()),
}));

import type { PrinterInfo, SlicerOption } from "../../api/types";
import * as systemApi from "../../api/system";
import { I18nProvider } from "../../i18n/context";
import * as i18nContext from "../../i18n/context";
import { translations } from "../../i18n/translations";
import {
  DEFAULT_SETTINGS,
  useSettingsStore,
} from "../../stores/settingsStore";
import { useSlicerStore } from "../../stores/slicerStore";
import SettingsPanel from "../SettingsPanel";

const SLICERS: SlicerOption[] = [
  { id: "BambuStudio", display_name: "Bambu Studio" },
];

const PRINTERS: PrinterInfo[] = [
  {
    id: "bambu-h2d",
    display_name: "Bambu Lab H2D",
    brand: "Bambu Lab",
    bed_width: 350,
    bed_depth: 320,
    bed_height: 325,
    supported_nozzle_sizes: ["0.4"],
    supported_slicers: ["BambuStudio"],
    device_profiles: [
      {
        device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.4",
        slicer_id: "BambuStudio",
        nozzle_size: "0.4",
        source_profile_name: "Bambu Lab H2D 0.4 nozzle",
        revision: "sha256:test",
        supported: true,
      },
    ],
  },
];

const requestPermissionMock =
  vi.fn<() => Promise<NotificationPermission>>();

class MockNotification {
  static permission: NotificationPermission = "default";

  static requestPermission = requestPermissionMock;

  constructor(_title: string, _options?: NotificationOptions) {}
}

function renderPanel() {
  return render(
    <I18nProvider>
      <SettingsPanel />
    </I18nProvider>,
  );
}

describe("SettingsPanel completion notifications", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    MockNotification.permission = "default";
    requestPermissionMock.mockResolvedValue("granted");
    vi.stubGlobal("Notification", MockNotification);

    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      language: "zh",
      enableCompletionNotifications: false,
    });
    useSlicerStore.setState({
      slicers: [],
      selectedSlicerId: null,
      isDetecting: false,
      isLaunching: false,
      isValidatingCustomPath: false,
      launchMessage: null,
      customPathMessage: null,
      customPathError: null,
      error: null,
    });
    vi.mocked(systemApi.getPrinters).mockResolvedValue(PRINTERS);
    vi.mocked(systemApi.getSlicers).mockResolvedValue(SLICERS);
    vi.mocked(systemApi.clearCache).mockResolvedValue({
      status: "success",
      message: "ok",
      deleted_files: 0,
      freed_bytes: 0,
      details: {
        registry_cleaned: 0,
        sessions_cleaned: 0,
        output_files_cleaned: 0,
      },
    });
    vi.mocked(systemApi.saveSettings).mockResolvedValue({
      status: "success",
      message: "Settings saved",
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows an accessible inline help trigger for the notification label", () => {
    renderPanel();

    const notificationSection = screen.getByTestId(
      "settings-completion-notifications-section",
    );
    expect(
      within(notificationSection).getByRole("button", {
        name: translations["settings.completion_notifications_enable_label"].zh,
      }),
    ).toHaveTextContent("?");
  });

  it("enables the persisted setting after permission is granted", async () => {
    renderPanel();

    fireEvent.click(
      screen.getByRole("switch", {
        name: translations["settings.completion_notifications_enable_label"].zh,
      }),
    );

    await waitFor(() => {
      expect(
        useSettingsStore.getState().enableCompletionNotifications,
      ).toBe(true);
    });
    expect(requestPermissionMock).toHaveBeenCalledTimes(1);
  });

  it("keeps the setting off and explains when permission is denied", async () => {
    requestPermissionMock.mockResolvedValue("denied");
    renderPanel();

    fireEvent.click(
      screen.getByRole("switch", {
        name: translations["settings.completion_notifications_enable_label"].zh,
      }),
    );

    expect(
      await screen.findByText(
        translations["settings.completion_notifications_denied"].zh,
      ),
    ).toBeInTheDocument();
    expect(
      useSettingsStore.getState().enableCompletionNotifications,
    ).toBe(false);
  });

  it("keeps the setting off when the permission prompt is dismissed", async () => {
    requestPermissionMock.mockResolvedValue("default");
    renderPanel();

    fireEvent.click(
      screen.getByRole("switch", {
        name: translations["settings.completion_notifications_enable_label"].zh,
      }),
    );

    await waitFor(() => {
      expect(requestPermissionMock).toHaveBeenCalledTimes(1);
      expect(
        screen.getByRole("switch", {
          name: translations[
            "settings.completion_notifications_enable_label"
          ].zh,
        }),
      ).toBeEnabled();
    });
    expect(
      screen.getByText(
        translations["settings.completion_notifications_default"].zh,
      ),
    ).toBeInTheDocument();
    expect(
      useSettingsStore.getState().enableCompletionNotifications,
    ).toBe(false);
  });

  it("keeps the setting off and explains permission request failures", async () => {
    requestPermissionMock.mockRejectedValue(
      new Error("notification permission failed"),
    );
    renderPanel();

    fireEvent.click(
      screen.getByRole("switch", {
        name: translations["settings.completion_notifications_enable_label"].zh,
      }),
    );

    expect(
      await screen.findByText(
        translations["settings.completion_notifications_request_failed"].zh,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("switch", {
        name: translations["settings.completion_notifications_enable_label"].zh,
      }),
    ).toBeEnabled();
    expect(
      useSettingsStore.getState().enableCompletionNotifications,
    ).toBe(false);
  });

  it("disables the switch and explains when notifications are unsupported", () => {
    vi.stubGlobal("Notification", undefined);
    renderPanel();

    expect(
      screen.getByRole("switch", {
        name: translations["settings.completion_notifications_enable_label"].zh,
      }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        translations["settings.completion_notifications_unsupported"].zh,
      ),
    ).toBeInTheDocument();
  });

  it("disables an enabled setting without requesting permission again", async () => {
    MockNotification.permission = "granted";
    useSettingsStore.setState({ enableCompletionNotifications: true });
    renderPanel();

    fireEvent.click(
      screen.getByRole("switch", {
        name: translations["settings.completion_notifications_enable_label"].zh,
      }),
    );

    await waitFor(() => {
      expect(
        useSettingsStore.getState().enableCompletionNotifications,
      ).toBe(false);
    });
    expect(requestPermissionMock).not.toHaveBeenCalled();
  });

  it("renders the English notification label in the English locale", async () => {
    const useI18nSpy = vi.spyOn(i18nContext, "useI18n").mockReturnValue({
      lang: "en",
      t: (key: string) => translations[key]?.en ?? key,
    });
    renderPanel();

    expect(
      await screen.findByText(
        translations["settings.completion_notifications_enable_label"].en,
      ),
    ).toBeInTheDocument();

    useI18nSpy.mockRestore();
  });

  it("turns off a stale persisted value when permission is not granted", async () => {
    useSettingsStore.setState({ enableCompletionNotifications: true });
    renderPanel();

    await waitFor(() => {
      expect(
        useSettingsStore.getState().enableCompletionNotifications,
      ).toBe(false);
    });
    expect(requestPermissionMock).not.toHaveBeenCalled();
  });
});
