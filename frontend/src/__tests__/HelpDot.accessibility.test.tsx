import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Checkbox from "../components/ui/Checkbox";
import RadioGroup from "../components/ui/RadioGroup";
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

    const checkbox = screen.getByRole("checkbox", {
      name: "启用外轮廓",
    });
    expect(checkbox).toHaveAttribute("type", "checkbox");
    const helpButton = screen.getByRole("button", {
      name: "沿作品外缘生成一圈可以调整宽度的边框。",
    });
    expect(helpButton).toBeInTheDocument();
    expect(helpButton.closest("label")).toBeNull();

    fireEvent.click(helpButton);

    expect(await screen.findByRole("link", { name: /查看 Wiki 详情/ })).toHaveAttribute(
      "href",
      "https://wiki.luminastudio.com.cn/zh/docs/reference/model-features/outline/",
    );
    expect(checkbox).not.toBeChecked();
  });

  it("keeps a radio group name separate from its help trigger", () => {
    useSettingsStore.setState({ language: "zh" });

    render(
      <I18nProvider>
        <RadioGroup
          label="建模模式"
          tooltip="决定模型使用平面、浮雕还是其他几何生成方式。"
          wikiPath="/docs/reference/converter-basic/modeling-mode/"
          value="flat"
          options={[{ label: "平面", value: "flat" }]}
          onChange={() => undefined}
        />
      </I18nProvider>,
    );

    expect(screen.getByRole("group", { name: "建模模式" })).toBeInTheDocument();
    const helpButton = screen.getByRole("button", {
      name: "决定模型使用平面、浮雕还是其他几何生成方式。",
    });
    expect(helpButton).toBeInTheDocument();
    expect(helpButton.closest("legend")).toBeNull();
  });
});
