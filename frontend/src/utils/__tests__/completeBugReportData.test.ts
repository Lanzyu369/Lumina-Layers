import { afterEach, expect, it, vi } from "vitest";
import apiClient, { apiErrorToVisibleMessage } from "../../api/client";
import { _clearClientLogBufferForTests, getRecentClientLogs, installGlobalClientLogCapture, postClientLog } from "../clientLog";
import { collectBugReportSourceFiles } from "../bugReportContext";
import { useConverterStore } from "../../stores/converter";
import { useWidgetStore } from "../../stores/widgetStore";
import { useExtractorStore } from "../../stores/extractorStore";
import { useSingleStageStore } from "../../stores/singleStageStore";
import * as extractorApi from "../../api/extractor";
import { _clearFeedbackSourcesForTests, installFeedbackSourceCapture } from "../sourceFileOrigins";
import { chooseWorkshopImageFile, createBrowserWorkshopFileServices } from "../../workshop/browserFiles";

afterEach(() => {
  _clearClientLogBufferForTests();
  _clearFeedbackSourcesForTests();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("retains a locally parsed workbook after its file picker is cleared", () => {
  const workbook = new File(["original workbook bytes"], "reference.xlsx");
  const input = document.createElement("input");
  input.type = "file";
  Object.defineProperty(input, "files", { configurable: true, value: [workbook] });
  document.body.appendChild(input);
  input.addEventListener("change", () => {
    Object.defineProperty(input, "files", { configurable: true, value: [] });
  });
  const stop = installFeedbackSourceCapture();
  try {
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.remove();
    expect(collectBugReportSourceFiles().includes(workbook)).toBe(true);
  } finally {
    stop();
    input.remove();
  }
});

it("retains a programmatically uploaded source after the upload is rejected", async () => {
  const source = new File(["invalid source project"], "invalid.3mf");
  const form = new FormData();
  form.append("file", source);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
  vi.spyOn(console, "error").mockImplementation(() => {});
  await expect(apiClient.post("/printer/custom-template", form, {
    adapter: async () => { throw new Error("Invalid project"); },
  })).rejects.toThrow();
  expect(collectBugReportSourceFiles().includes(source)).toBe(true);
});

it("retains native Workshop input even when image decoding fails", async () => {
  let selected: File | null = null;
  const services = createBrowserWorkshopFileServices({
    chooseImageFile: async () => {
      selected = await chooseWorkshopImageFile({
        pickWorkshopImage: async () => ({
          name: "broken-workshop.png", mimeType: "image/png", bytes: new Uint8Array([1, 2, 3, 4]),
        }),
      });
      return selected;
    },
    decodeImage: async () => { throw new Error("Image decoding failed"); },
    encodePng: vi.fn(),
  });
  await expect(services.pickImage()).rejects.toThrow("Image decoding failed");
  expect(selected).not.toBeNull();
  expect(collectBugReportSourceFiles().includes(selected!)).toBe(true);
});

it("keeps object rejection data and the full cause of global errors", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
  const stop = installGlobalClientLogCapture();
  try {
    const reason = { detail: "original rejection detail", payload: [1, 2, 3] };
    const rejection = new Event("unhandledrejection");
    Object.defineProperty(rejection, "reason", { value: reason });
    window.dispatchEvent(rejection);
    const cause = new Error("root cause");
    const failure = Object.assign(new Error("failed", { cause }), { original_path: "/Users/min/original.svg" });
    window.dispatchEvent(new ErrorEvent("error", { error: failure }));
    expect(getRecentClientLogs().find((entry) => entry.phase === "unhandled-rejection")?.details).toMatchObject({ reason });
    expect(getRecentClientLogs().find((entry) => entry.phase === "uncaught-error")?.details).toMatchObject({
      error: { error_message: "failed", original_path: "/Users/min/original.svg",
        cause: { error_message: "root cause", error_stack: expect.stringContaining("root cause") } },
    });
  } finally {
    stop();
  }
});

it("keeps the original API exception before assigning its visible message", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
  const failure = Object.assign(new Error("original transport exception", { cause: new Error("original cause") }), {
    response: { status: 500, data: { detail: "complete server failure" } },
    config: { method: "post", url: "/convert" },
  });
  await expect(apiClient.post("/convert", {}, { adapter: async () => { throw failure; } })).rejects.toThrow("complete server failure");
  expect(getRecentClientLogs().find((entry) => entry.phase === "request-failed")?.details).toMatchObject({
    error: { error_message: "original transport exception", cause: { error_message: "original cause" } },
  });
});

it("keeps every local diagnostic when repeated relay posts are deduplicated", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
  postClientLog("failure", { method: "error", dedupeMs: 1000, details: { message: "first" } });
  postClientLog("failure", { method: "error", dedupeMs: 1000, details: { message: "second" } });
  expect(getRecentClientLogs().map((entry) => entry.details)).toEqual([{ message: "first" }, { message: "second" }]);
});

it("keeps original server error details visible", () => {
  const detail = "Traceback: /Users/min/source.svg: WorkerError: bad geometry";
  expect(apiErrorToVisibleMessage({ response: { status: 500, data: { detail } } })).toBe(detail);
});

it("exports complete log content without redaction or nested truncation", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
  const details = {
    disk_path: "/Users/min/source.svg",
    error_stack: "Traceback\n" + "x".repeat(16000),
    items: Array.from({ length: 80 }, (_, i) => i),
    nested: { a: { b: { c: { d: { e: "keep" } } } } },
  };
  postClientLog("failure", { method: "error", details });
  expect(getRecentClientLogs().at(-1)?.details).toEqual(details);
});

it("collects the original, model and batch files even from another active tab", () => {
  const original = new File(["<svg/>"], "original.svg");
  const model = new File(["solid model"], "plate.stl");
  const batch = new File(["image"], "second.png");
  const previous = useConverterStore.getState();
  const tab = useWidgetStore.getState().activeTab;
  useConverterStore.setState({ imageFile: original, modelSurfaceFile: model, batchFiles: [original, batch] });
  useWidgetStore.setState({ activeTab: "settings" });
  expect(collectBugReportSourceFiles()).toEqual(expect.arrayContaining([original, model, batch]));
  expect(collectBugReportSourceFiles().filter((file) => file === original)).toHaveLength(1);
  useConverterStore.setState(previous);
  useWidgetStore.setState({ activeTab: tab });
});

it("keeps original extractor and gradient-card files after repeated rotations", async () => {
  const original = new File(["exact original camera bytes"], "capture.jpg", { type: "image/jpeg" });
  const white = new File(["exact white camera bytes"], "white.jpg", { type: "image/jpeg" });
  const black = new File(["exact black camera bytes"], "black.jpg", { type: "image/jpeg" });
  const extractor = useExtractorStore.getState();
  const singleStage = useSingleStageStore.getState();
  vi.spyOn(extractorApi, "rotateExtractorImage").mockResolvedValue({ preview_url: "/api/files/rotation", width: 20, height: 10 });
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => new Response("rotated bytes", { headers: { "Content-Type": "image/png" } })));
  try {
    useExtractorStore.setState({ imageFile: original, isLoading: false, imagePreviewUrl: null, originalPreviewUrl: null, calibratedFullFileId: null, previousCalibratedFullFileId: null });
    useSingleStageStore.setState({ whiteImageFile: white, blackImageFile: black, whiteImagePreviewUrl: null, blackImagePreviewUrl: null, isExtracting: false, isRotatingWhite: false, isRotatingBlack: false, whiteColorcheckerFileId: null, blackColorcheckerFileId: null });
    for (let count = 0; count < 2; count += 1) {
      await useExtractorStore.getState().rotateImage();
      await useSingleStageStore.getState().rotateWhiteImage("cw");
      await useSingleStageStore.getState().rotateBlackImage("cw");
    }
    const sources = collectBugReportSourceFiles();
    for (const file of [original, white, black,
      useExtractorStore.getState().imageFile,
      useSingleStageStore.getState().whiteImageFile,
      useSingleStageStore.getState().blackImageFile,
    ]) expect(sources.includes(file!)).toBe(true);
    expect(useExtractorStore.getState().imageFile).not.toBe(original);
  } finally {
    useExtractorStore.setState(extractor);
    useSingleStageStore.setState(singleStage);
  }
});
