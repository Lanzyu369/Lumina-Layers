import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { HeaderTooltip } from "../HeaderTooltip";

describe("HeaderTooltip", () => {
  it("renders a CSS-hidden styled tooltip and keeps the trigger free of native titles", () => {
    render(
      <HeaderTooltip label="切换主题">
        <button type="button" aria-label="切换主题">
          A
        </button>
      </HeaderTooltip>,
    );

    const tooltip = screen.getByText("切换主题");
    expect(tooltip).toHaveAttribute("aria-hidden", "true");
    // Hidden by default, revealed on trigger hover / keyboard focus via the
    // named-group Tailwind variants. Keyboard focus means :focus-visible, so
    // focus moved back after a mouse click does not leave the hint showing.
    // 默认隐藏，经命名分组的悬停/键盘聚焦变体在触发时显示；鼠标点击后焦点被移回时不显示。
    expect(tooltip.className).toContain("opacity-0");
    expect(tooltip.className).toContain("group-hover/header-tip:opacity-100");
    expect(tooltip.className).toContain(
      "group-has-[:focus-visible]/header-tip:opacity-100",
    );
    expect(tooltip.className).not.toContain("group-focus-within");
    expect(tooltip.className).toContain("pointer-events-none");

    const button = screen.getByRole("button", { name: "切换主题" });
    expect(button).not.toHaveAttribute("title");
  });

  it("omits the hint while suppressed so it cannot cover an open popover", () => {
    render(
      <HeaderTooltip label="更多选项" suppressed>
        <button type="button" aria-label="更多选项">
          A
        </button>
      </HeaderTooltip>,
    );

    expect(screen.queryByText("更多选项")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更多选项" })).toBeInTheDocument();
  });
});
