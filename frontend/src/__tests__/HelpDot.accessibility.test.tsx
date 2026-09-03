import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Checkbox from "../components/ui/Checkbox";
import { I18nProvider } from "../i18n/context";
import { useSettingsStore } from "../stores/settingsStore";

describe("HelpDot accessibility names", () => {
  it("does not reuse the associated form control label and opens on tap", async () => {
    useSettingsStore.setState({ language: "zh" });

    render(
      <I18nProvider>
        <Checkbox
          label="启用外轮廓"
          tooltip="沿作品外缘生成一圈可以调整宽度的边框。"
          wikiPath="/docs/reference/model-features/outline/"
          checked={false}
          onChange={() => undefined}
        />
      </I18nProvider>,
    );

    expect(screen.getByLabelText("启用外轮廓")).toHaveAttribute(
      "type",
      "checkbox",
    );
    const helpButton = screen.getByRole("button", {
      name: "沿作品外缘生成一圈可以调整宽度的边框。",
    });
    expect(helpButton).toBeInTheDocument();

    fireEvent.click(helpButton);

    expect(await screen.findByRole("link", { name: /查看 Wiki 详情/ })).toHaveAttribute(
      "href",
      "https://wiki.luminastudio.com.cn/zh/docs/reference/model-features/outline/",
    );
    expect(screen.getByLabelText("启用外轮廓")).not.toBeChecked();
  });
});
