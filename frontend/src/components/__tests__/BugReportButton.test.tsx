import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { BugReportButton } from "../BugReportButton";

describe("BugReportButton", () => {
  it("renders as a labelled menu row without a native title", () => {
    render(<BugReportButton onClick={() => {}} />);

    const item = screen.getByRole("button", { name: "反馈问题" });
    expect(item).toHaveTextContent("反馈问题");
    // DESIGN.md forbids native ``title`` tooltips on header controls.
    // DESIGN.md 禁止顶栏控件使用原生 ``title`` 提示。
    expect(item).not.toHaveAttribute("title");
  });

  it("invokes onClick when pressed", () => {
    const onClick = vi.fn();
    render(<BugReportButton onClick={onClick} />);

    fireEvent.click(screen.getByTestId("bug-report-button"));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
