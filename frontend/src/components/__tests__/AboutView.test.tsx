import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AboutView from "../AboutView";
import { clearCache } from "../../api/system";
import { I18nProvider } from "../../i18n/context";
import { useAboutStore } from "../../stores/aboutStore";
import { useSettingsStore } from "../../stores/settingsStore";

vi.mock("../../api/system", () => ({
  clearCache: vi.fn(),
}));

describe("AboutView cache clear visible errors", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({ language: "en" });
    useAboutStore.setState({ loading: false, notification: null });
  });

  it("shows a readable notification when cache clearing fails with a raw HTTP status error", async () => {
    vi.mocked(clearCache).mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    render(
      <I18nProvider>
        <AboutView />
      </I18nProvider>,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /Clear System Cache|清除系统缓存/ }),
    );

    const notification = await screen.findByTestId("cache-notification");
    expect(notification).toHaveTextContent(
      /The server hit an internal error|服务器发生内部错误/,
    );
    expect(notification).not.toHaveTextContent(/Request failed with status code 500/i);
    expect(clearCache).toHaveBeenCalledOnce();
  });
});
