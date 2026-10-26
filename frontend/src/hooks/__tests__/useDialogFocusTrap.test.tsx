import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { useDialogFocusTrap } from "../useDialogFocusTrap";

function Harness({ active, focusSecond = false }: { active: boolean; focusSecond?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useDialogFocusTrap(ref, active, {
    initialFocus: focusSecond
      ? (container) => container.querySelector<HTMLElement>("[data-second]")
      : undefined,
  });
  return (
    <>
      <button type="button">outside</button>
      <div ref={ref} tabIndex={-1} data-testid="dialog">
        <button type="button">first</button>
        <button type="button" data-second>
          second
        </button>
        <button type="button">last</button>
      </div>
    </>
  );
}

describe("useDialogFocusTrap", () => {
  afterEach(() => cleanup());

  it("focuses the container, or the requested element, on activation", () => {
    const { unmount } = render(<Harness active />);
    expect(screen.getByTestId("dialog")).toHaveFocus();
    unmount();

    render(<Harness active focusSecond />);
    expect(screen.getByText("second")).toHaveFocus();
  });

  it("wraps Tab and Shift+Tab inside the dialog", () => {
    render(<Harness active />);
    screen.getByText("last").focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByText("first")).toHaveFocus();

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(screen.getByText("last")).toHaveFocus();
  });

  it("pulls escaped focus back into the dialog", () => {
    render(<Harness active />);
    screen.getByText("outside").focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByText("first")).toHaveFocus();
  });

  it("restores the previous focus when deactivated", () => {
    const { rerender } = render(<Harness active={false} />);
    screen.getByText("outside").focus();
    rerender(<Harness active />);
    expect(screen.getByTestId("dialog")).toHaveFocus();
    rerender(<Harness active={false} />);
    expect(screen.getByText("outside")).toHaveFocus();
  });

  it("does nothing while inactive", () => {
    render(<Harness active={false} />);
    screen.getByText("outside").focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByText("outside")).toHaveFocus();
  });
});
