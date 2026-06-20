import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearCache } from "../../api/system";
import { useAboutStore } from "../aboutStore";
import { useSettingsStore } from "../settingsStore";

vi.mock("../../api/system", () => ({
  clearCache: vi.fn(),
}));

const RAW_HTTP_STATUS_PATTERN =
  /Request failed with status code|status code\s+\d{3}/i;

describe("aboutStore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useSettingsStore.setState({ language: "en" });
    useAboutStore.setState({ loading: false, notification: null });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("normalizes raw HTTP status text when cache clearing fails", async () => {
    vi.mocked(clearCache).mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    await useAboutStore.getState().clearCache();

    const notification = useAboutStore.getState().notification;
    expect(notification?.type).toBe("error");
    expect(notification?.message).toBe(
      "The server hit an internal error. Check the log for the request ID.",
    );
    expect(notification?.message).not.toMatch(RAW_HTTP_STATUS_PATTERN);
  });

  it("preserves readable cache clear errors", async () => {
    vi.mocked(clearCache).mockRejectedValueOnce(new Error("Cache directory is busy."));

    await useAboutStore.getState().clearCache();

    expect(useAboutStore.getState().notification?.message).toBe(
      "Cache directory is busy.",
    );
  });
});
