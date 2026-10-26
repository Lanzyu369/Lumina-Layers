import { afterEach, describe, expect, it, vi } from "vitest";

type TestWindow = Window & {
  __LUMINA_UMAMI_CONFIG__?: {
    enabled: boolean;
    scriptUrl: string;
    websiteId: string;
  };
  umami?: {
    track?: (eventName: string, data?: Record<string, unknown>) => void;
  };
};

const testWindow = window as TestWindow;

function configureEnabledAnalytics(): void {
  testWindow.__LUMINA_UMAMI_CONFIG__ = {
    enabled: true,
    scriptUrl: "https://analytics.example.com/script.js",
    websiteId: "site-123",
  };
}

async function loadAnalyticsModule() {
  vi.resetModules();
  return import("../analytics/umami");
}

afterEach(() => {
  document.getElementById("lumina-umami-script")?.remove();
  delete testWindow.__LUMINA_UMAMI_CONFIG__;
  delete testWindow.umami;
  vi.restoreAllMocks();
  vi.resetModules();
});

describe("Lumina Umami analytics", () => {
  it("keeps direct tracker failures from escaping product workflows", async () => {
    configureEnabledAnalytics();
    const { trackLuminaEvent } = await loadAnalyticsModule();
    testWindow.umami = {
      track: vi.fn(() => {
        throw new Error("tracker unavailable");
      }),
    };

    expect(() => trackLuminaEvent("lumina_converter_preview_done")).not.toThrow();
    expect(testWindow.umami.track).toHaveBeenCalledOnce();
  });

  it("keeps queued event flush failures from escaping script load handlers", async () => {
    configureEnabledAnalytics();
    const { installLuminaUmami, trackLuminaEvent } = await loadAnalyticsModule();

    installLuminaUmami();
    trackLuminaEvent("lumina_app_open");
    testWindow.umami = {
      track: vi.fn(() => {
        throw new Error("tracker unavailable");
      }),
    };

    const script = document.getElementById("lumina-umami-script");
    expect(script).toBeInstanceOf(HTMLScriptElement);
    expect(() => script?.dispatchEvent(new Event("load"))).not.toThrow();
    expect(testWindow.umami.track).toHaveBeenCalledOnce();
  });
});
