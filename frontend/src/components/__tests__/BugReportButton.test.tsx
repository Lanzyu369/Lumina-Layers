import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { BugReportButton } from "../BugReportButton";

describe("BugReportButton", () => {
  it("renders with translated aria label and a styled tooltip instead of a native title", () => {
    render(<BugReportButton onClick={() => {}} />);

    const button = screen.getByRole("button", { name: "反馈问题" });
    expect(button).toBeInTheDocument();
    // DESIGN.md forbids native ``title`` tooltips; the hint must come from
    // the styled HeaderTooltip wrapper instead.
    // DESIGN.md 禁止原生 ``title`` 提示；提示必须来自样式化的
    // HeaderTooltip 包装组件。
    expect(button).not.toHaveAttribute("title");
    const tooltip = screen.getByText("向开发者发送 bug 反馈");
    expect(tooltip).toHaveAttribute("aria-hidden", "true");
    expect(tooltip.className).toContain("opacity-0");
  });

  it("invokes onClick when pressed", () => {
    const onClick = vi.fn();
    render(<BugReportButton onClick={onClick} />);

    fireEvent.click(screen.getByTestId("bug-report-button"));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
