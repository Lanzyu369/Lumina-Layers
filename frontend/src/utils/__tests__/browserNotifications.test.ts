import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getBrowserNotificationPermission,
  requestBrowserNotificationPermission,
  showBrowserCompletionNotification,
  type CompletionNotificationKind,
} from "../browserNotifications";

interface NotificationCall {
  title: string;
  options?: NotificationOptions;
}

const notificationCalls: NotificationCall[] = [];

class MockNotification {
  static permission: NotificationPermission = "default";
  static requestPermission = vi.fn<() => Promise<NotificationPermission>>();

  constructor(title: string, options?: NotificationOptions) {
    notificationCalls.push({ title, options });
  }
}

function stubNotification(permission: NotificationPermission): void {
  MockNotification.permission = permission;
  vi.stubGlobal("Notification", MockNotification);
}

beforeEach(() => {
  notificationCalls.length = 0;
  MockNotification.permission = "default";
  MockNotification.requestPermission.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("browser notification permission", () => {
  it("reports unsupported without a Notification API", async () => {
    vi.stubGlobal("Notification", undefined);

    expect(getBrowserNotificationPermission()).toBe("unsupported");
    await expect(requestBrowserNotificationPermission()).resolves.toBe(
      "unsupported",
    );
    expect(showBrowserCompletionNotification("preview", "en")).toBe(false);
  });

  it("returns an existing granted permission without requesting it", async () => {
    stubNotification("granted");

    await expect(requestBrowserNotificationPermission()).resolves.toBe(
      "granted",
    );
    expect(MockNotification.requestPermission).not.toHaveBeenCalled();
  });

  it("returns an existing denied permission without requesting it", async () => {
    stubNotification("denied");

    await expect(requestBrowserNotificationPermission()).resolves.toBe(
      "denied",
    );
    expect(MockNotification.requestPermission).not.toHaveBeenCalled();
  });

  it("requests permission when the current state is default", async () => {
    stubNotification("default");
    MockNotification.requestPermission.mockResolvedValue("granted");

    await expect(requestBrowserNotificationPermission()).resolves.toBe(
      "granted",
    );
    expect(MockNotification.requestPermission).toHaveBeenCalledOnce();
  });

  it("returns error when requesting permission throws", async () => {
    stubNotification("default");
    MockNotification.requestPermission.mockRejectedValue(
      new Error("permission request failed"),
    );

    await expect(requestBrowserNotificationPermission()).resolves.toBe("error");
  });

  it("returns error when reading the current permission throws", () => {
    class ThrowingPermissionNotification {
      static get permission(): NotificationPermission {
        throw new Error("permission read failed");
      }
    }

    vi.stubGlobal("Notification", ThrowingPermissionNotification);

    expect(getBrowserNotificationPermission()).toBe("error");
  });
});

describe("browser completion notification delivery", () => {
  it("creates a Chinese notification payload", () => {
    stubNotification("granted");

    expect(showBrowserCompletionNotification("preview", "zh")).toBe(true);
    expect(notificationCalls).toEqual([
      {
        title: "预览已完成",
        options: {
          body: "预览已准备好，可以查看。",
          tag: "lumina-completion-preview",
        },
      },
    ]);
  });

  it("creates an English notification payload", () => {
    stubNotification("granted");

    expect(showBrowserCompletionNotification("generation", "en")).toBe(true);
    expect(notificationCalls).toEqual([
      {
        title: "Model generation complete",
        options: {
          body: "Your model is ready to download or send to a slicer.",
          tag: "lumina-completion-generation",
        },
      },
    ]);
  });

  it("uses stable tags for every completion kind", () => {
    stubNotification("granted");
    const kinds: CompletionNotificationKind[] = [
      "preview",
      "generation",
      "batch",
      "calibration",
    ];

    for (const kind of [...kinds, ...kinds]) {
      expect(showBrowserCompletionNotification(kind, "en")).toBe(true);
    }

    expect(notificationCalls.map((call) => call.options?.tag)).toEqual([
      "lumina-completion-preview",
      "lumina-completion-generation",
      "lumina-completion-batch",
      "lumina-completion-calibration",
      "lumina-completion-preview",
      "lumina-completion-generation",
      "lumina-completion-batch",
      "lumina-completion-calibration",
    ]);
  });

  it("does not create a notification without granted permission", () => {
    stubNotification("denied");

    expect(showBrowserCompletionNotification("batch", "en")).toBe(false);
    expect(notificationCalls).toHaveLength(0);
  });

  it("isolates a throwing Notification constructor", () => {
    class ThrowingNotification {
      static permission: NotificationPermission = "granted";

      constructor() {
        throw new Error("notification construction failed");
      }
    }

    vi.stubGlobal("Notification", ThrowingNotification);

    expect(() =>
      showBrowserCompletionNotification("calibration", "en"),
    ).not.toThrow();
    expect(showBrowserCompletionNotification("calibration", "en")).toBe(false);
  });
});
