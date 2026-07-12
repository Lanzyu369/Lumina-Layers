import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getBrowserNotificationPermission,
  requestBrowserNotificationPermission,
  showBrowserCompletionNotification,
  type CompletionNotificationKind,
} from "../browserNotifications";

type RenotifyNotificationOptions = NotificationOptions & {
  renotify?: boolean;
};

interface NotificationCall {
  title: string;
  options?: RenotifyNotificationOptions;
}

const notificationCalls: NotificationCall[] = [];

class MockNotification {
  static permission: NotificationPermission = "default";
  static requestPermission = vi.fn<() => Promise<NotificationPermission>>();

  constructor(title: string, options?: RenotifyNotificationOptions) {
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

  it("supports callback-only permission requests used by older macOS Safari", async () => {
    class CallbackOnlyNotification {
      static permission: NotificationPermission = "default";

      static requestPermission(
        callback?: NotificationPermissionCallback,
      ): void {
        callback?.("granted");
      }
    }

    vi.stubGlobal("Notification", CallbackOnlyNotification);

    await expect(requestBrowserNotificationPermission()).resolves.toBe(
      "granted",
    );
  });

  it("settles once when a browser supports both callback and Promise results", async () => {
    class HybridNotification {
      static permission: NotificationPermission = "default";

      static requestPermission(
        callback?: NotificationPermissionCallback,
      ): Promise<NotificationPermission> {
        callback?.("granted");
        return Promise.resolve("denied");
      }
    }

    vi.stubGlobal("Notification", HybridNotification);

    await expect(requestBrowserNotificationPermission()).resolves.toBe(
      "granted",
    );
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
  it("creates exact Chinese and English payloads for every completion kind", () => {
    stubNotification("granted");
    const expectedPayloads: Array<{
      kind: CompletionNotificationKind;
      language: "zh" | "en";
      call: NotificationCall;
    }> = [
      {
        kind: "preview",
        language: "zh",
        call: {
          title: "预览已完成",
          options: {
            body: "预览已准备好，可以查看。",
            tag: "lumina-completion-preview",
            renotify: true,
          },
        },
      },
      {
        kind: "preview",
        language: "en",
        call: {
          title: "Preview complete",
          options: {
            body: "Your preview is ready to inspect.",
            tag: "lumina-completion-preview",
            renotify: true,
          },
        },
      },
      {
        kind: "generation",
        language: "zh",
        call: {
          title: "模型生成已完成",
          options: {
            body: "模型已准备好，可以下载或发送到切片软件。",
            tag: "lumina-completion-generation",
            renotify: true,
          },
        },
      },
      {
        kind: "generation",
        language: "en",
        call: {
          title: "Model generation complete",
          options: {
            body: "Your model is ready to download or send to a slicer.",
            tag: "lumina-completion-generation",
            renotify: true,
          },
        },
      },
      {
        kind: "batch",
        language: "zh",
        call: {
          title: "批量生成已完成",
          options: {
            body: "批量生成结果已准备好。",
            tag: "lumina-completion-batch",
            renotify: true,
          },
        },
      },
      {
        kind: "batch",
        language: "en",
        call: {
          title: "Batch generation complete",
          options: {
            body: "Your batch results are ready.",
            tag: "lumina-completion-batch",
            renotify: true,
          },
        },
      },
      {
        kind: "calibration",
        language: "zh",
        call: {
          title: "校准生成已完成",
          options: {
            body: "校准文件已准备好。",
            tag: "lumina-completion-calibration",
            renotify: true,
          },
        },
      },
      {
        kind: "calibration",
        language: "en",
        call: {
          title: "Calibration generation complete",
          options: {
            body: "Your calibration files are ready.",
            tag: "lumina-completion-calibration",
            renotify: true,
          },
        },
      },
    ];

    for (const { kind, language } of expectedPayloads) {
      expect(showBrowserCompletionNotification(kind, language)).toBe(true);
    }

    expect(notificationCalls).toEqual(
      expectedPayloads.map(({ call }) => call),
    );
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
    expect(notificationCalls.every((call) => call.options?.renotify)).toBe(
      true,
    );
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
