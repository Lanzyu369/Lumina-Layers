import { act } from "@testing-library/react";
import * as reactDomClient from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as clientLog from "../utils/clientLog";

vi.mock("../App.tsx", () => ({ default: () => null }));
vi.mock("react-dom/client", async (importOriginal) => {
  const client = await importOriginal<typeof import("react-dom/client")>();
  return { ...client, createRoot: vi.fn(client.createRoot) };
});
vi.mock("../utils/clientLog", async (importOriginal) => {
  const logs = await importOriginal<typeof import("../utils/clientLog")>();
  return {
    ...logs,
    installGlobalClientLogCapture: vi.fn(logs.installGlobalClientLogCapture),
  };
});

type LegacyAnalyticsWindow = Window & {
  __LUMINA_UMAMI_CONFIG__?: {
    enabled: boolean;
    scriptUrl: string;
    websiteId: string;
  };
  umami?: { track: ReturnType<typeof vi.fn> };
};

const legacyWindow = window as LegacyAnalyticsWindow;
let root: Root | undefined;
let stopClientLogCapture: (() => void) | undefined;

afterEach(async () => {
  await act(async () => root?.unmount());
  stopClientLogCapture?.();
  root = undefined;
  stopClientLogCapture = undefined;
  document.getElementById("root")?.remove();
  document.head.querySelectorAll("script[src]").forEach((script) => script.remove());
  delete legacyWindow.__LUMINA_UMAMI_CONFIG__;
  delete legacyWindow.umami;
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("app startup", () => {
  it("ignores legacy analytics settings without loading or reporting to a tracker", async () => {
    const tracker = vi.fn();
    legacyWindow.__LUMINA_UMAMI_CONFIG__ = {
      enabled: true,
      scriptUrl: "https://analytics.example.test/script.js",
      websiteId: "legacy-site",
    };
    legacyWindow.umami = { track: tracker };
    vi.stubEnv("VITE_UMAMI_ENABLED", "true");
    vi.stubEnv("VITE_UMAMI_SCRIPT_URL", "https://analytics.example.test/script.js");
    vi.stubEnv("VITE_UMAMI_WEBSITE_ID", "legacy-site");

    const rootElement = document.createElement("div");
    rootElement.id = "root";
    document.body.appendChild(rootElement);
    await act(async () => {
      await import("../main");
    });
    root = vi.mocked(reactDomClient.createRoot).mock.results[0]?.value;
    stopClientLogCapture = vi.mocked(clientLog.installGlobalClientLogCapture).mock.results[0]?.value;

    expect.soft(document.head.querySelectorAll("script[src]")).toHaveLength(0);
    expect(tracker).not.toHaveBeenCalled();
  });
});
