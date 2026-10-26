import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import NavTabStrip from "../widget/NavTabStrip";

function renderStrip({ scrollWidth, clientWidth }: { scrollWidth: number; clientWidth: number }) {
  render(
    <NavTabStrip role="tablist">
      <button type="button">Tab</button>
    </NavTabStrip>,
  );
  const strip = screen.getByRole("tablist");
  Object.defineProperty(strip, "scrollWidth", { configurable: true, value: scrollWidth });
  Object.defineProperty(strip, "clientWidth", { configurable: true, value: clientWidth });
  return strip;
}

describe("NavTabStrip", () => {
  it("scrolls without a visible scrollbar", () => {
    const strip = renderStrip({ scrollWidth: 800, clientWidth: 400 });

    expect(strip).toHaveClass("scrollbar-hidden", "overflow-x-auto");
    expect(strip).not.toHaveClass("dock-scrollbar");
  });

  it("turns a vertical mouse wheel into horizontal scrolling when the tabs overflow", () => {
    const strip = renderStrip({ scrollWidth: 800, clientWidth: 400 });

    fireEvent.wheel(strip, { deltaY: 120 });
    expect(strip.scrollLeft).toBe(120);

    fireEvent.wheel(strip, { deltaY: 3, deltaMode: 1 });
    expect(strip.scrollLeft).toBe(120 + 3 * 16);

    fireEvent.wheel(strip, { deltaY: 1, deltaMode: 2 });
    expect(strip.scrollLeft).toBe(120 + 3 * 16 + 400);
  });

  it("leaves the wheel alone when the tabs fit or the gesture is already horizontal", () => {
    const fitting = renderStrip({ scrollWidth: 400, clientWidth: 400 });
    fireEvent.wheel(fitting, { deltaY: 120 });
    expect(fitting.scrollLeft).toBe(0);
  });

  it("does not add vertical wheel movement to a horizontal trackpad swipe", () => {
    const strip = renderStrip({ scrollWidth: 800, clientWidth: 400 });

    fireEvent.wheel(strip, { deltaX: 40, deltaY: 10 });
    expect(strip.scrollLeft).toBe(0);
  });
});
