import { afterEach, describe, expect, it, vi } from "vitest";

import { devLog } from "../devLog";

describe("devLog", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("forwards debug messages in development", () => {
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    devLog.log("[DEBUG] test message", { id: "preview" });

    expect(logSpy).toHaveBeenCalledWith("[DEBUG] test message", {
      id: "preview",
    });
  });

  it("forwards timing calls in development", () => {
    const timeSpy = vi.spyOn(console, "time").mockImplementation(() => {});
    const timeLogSpy = vi.spyOn(console, "timeLog").mockImplementation(() => {});
    const timeEndSpy = vi.spyOn(console, "timeEnd").mockImplementation(() => {});

    devLog.timing.start("[LUMINA] preview");
    devLog.timing.mark("[LUMINA] preview", "request sent");
    devLog.timing.end("[LUMINA] preview");

    expect(timeSpy).toHaveBeenCalledWith("[LUMINA] preview");
    expect(timeLogSpy).toHaveBeenCalledWith("[LUMINA] preview", "request sent");
    expect(timeEndSpy).toHaveBeenCalledWith("[LUMINA] preview");
  });
});
