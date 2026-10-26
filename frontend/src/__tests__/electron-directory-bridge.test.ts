import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const nativePicker = vi.fn();

beforeEach(() => {
  vi.resetModules();
  nativePicker.mockReset();
  vi.stubGlobal("electronAPI", { pickGeneratedFileDirectory: nativePicker });
});

afterEach(() => vi.unstubAllGlobals());

describe("native directory picker bridge", () => {
  it("surfaces native errors to the settings alert", async () => {
    nativePicker.mockResolvedValue({ status: "error", code: "dialog-failed" });
    const { pickGeneratedFileDirectory } = await import("../integrations/electron");
    await expect(pickGeneratedFileDirectory()).rejects.toThrow();
  });

  it("keeps user cancellation silent", async () => {
    nativePicker.mockResolvedValue({ status: "canceled" });
    const { pickGeneratedFileDirectory } = await import("../integrations/electron");
    await expect(pickGeneratedFileDirectory()).resolves.toBeNull();
  });

  it("returns the selected directory", async () => {
    nativePicker.mockResolvedValue({ status: "selected", directory: "/tmp/prints" });
    const { pickGeneratedFileDirectory } = await import("../integrations/electron");
    await expect(pickGeneratedFileDirectory()).resolves.toBe("/tmp/prints");
  });
});
