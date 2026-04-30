import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { BugReportButton } from "../BugReportButton";

describe("BugReportButton", () => {
  it("renders with translated aria label and tooltip", () => {
    render(<BugReportButton onClick={() => {}} />);

    const button = screen.getByRole("button", { name: "反馈问题" });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("title", "向开发者发送 bug 反馈");
  });

  it("invokes onClick when pressed", () => {
    const onClick = vi.fn();
    render(<BugReportButton onClick={onClick} />);

    fireEvent.click(screen.getByTestId("bug-report-button"));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
