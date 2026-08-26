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
    // named-group Tailwind variants.
    // 默认隐藏，经命名分组的悬停/聚焦变体在触发时显示。
    expect(tooltip.className).toContain("opacity-0");
    expect(tooltip.className).toContain("group-hover/header-tip:opacity-100");
    expect(tooltip.className).toContain(
      "group-focus-within/header-tip:opacity-100",
    );
    expect(tooltip.className).toContain("pointer-events-none");

    const button = screen.getByRole("button", { name: "切换主题" });
    expect(button).not.toHaveAttribute("title");
  });
});
