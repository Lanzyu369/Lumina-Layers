/**
 * Slider snap-to-grid regression tests.
 *
 * Background: the native HTML `<input type="range">` anchors its step grid to
 * `min`, so when `min` is not a multiple of `step` (e.g. min=0.2, step=0.08),
 * dragging emits values like 1.16 / 1.24 instead of 1.20 / 1.28. The Slider
 * component normalizes this by rounding to the nearest multiple of `step`
 * anchored at 0 before calling `onChange`.
 *
 * 背景：原生 `<input type="range">` 的 step 网格以 `min` 为锚点，当 `min` 不
 * 是 `step` 的整数倍时（如 min=0.2, step=0.08），拖动会产生 1.16 / 1.24 等不
 * 是 step 整数倍的值。Slider 组件在 onChange 之前统一对齐到以 0 为锚点的
 * step 网格。
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import Slider from "../Slider";

function isMultipleOfStep(value: number, step: number): boolean {
  const ratio = value / step;
  return Math.abs(ratio - Math.round(ratio)) < 1e-9;
}

describe("Slider snap-to-grid", () => {
  it("range onChange snaps to multiples of step even when min is off-grid", () => {
    const onChange = vi.fn();
    render(
      <Slider
        label="Thickness"
        value={1.2}
        min={0.2}
        max={3.5}
        step={0.08}
        onChange={onChange}
      />,
    );

    const range = screen.getByLabelText("Thickness") as HTMLInputElement;

    // Native range with min=0.2, step=0.08 emits 1.16 (= 0.2 + 12*0.08).
    // After our fix, onChange rounds half-up to 1.20 (a true multiple of 0.08).
    fireEvent.change(range, { target: { value: "1.16" } });
    const emitted1 = onChange.mock.calls.at(-1)?.[0] as number;
    expect(isMultipleOfStep(emitted1, 0.08)).toBe(true);
    expect(emitted1).toBeCloseTo(1.2, 10);

    // Native range also emits 1.24 (= 0.2 + 13*0.08); snaps to 1.28.
    fireEvent.change(range, { target: { value: "1.24" } });
    const emitted2 = onChange.mock.calls.at(-1)?.[0] as number;
    expect(isMultipleOfStep(emitted2, 0.08)).toBe(true);
    expect(emitted2).toBeCloseTo(1.28, 10);
  });

  it("text input commit snaps to multiples of step", () => {
    const onChange = vi.fn();
    render(
      <Slider
        label="Thickness"
        value={1.2}
        min={0.2}
        max={3.5}
        step={0.08}
        onChange={onChange}
      />,
    );

    const text = screen.getByLabelText("Thickness value") as HTMLInputElement;
    fireEvent.focus(text);
    fireEvent.change(text, { target: { value: "1.17" } });
    fireEvent.blur(text);

    const emitted = onChange.mock.calls.at(-1)?.[0] as number;
    expect(isMultipleOfStep(emitted, 0.08)).toBe(true);
    expect(emitted).toBeCloseTo(1.2, 10);
  });

  it("clamps to [min, max] after snapping", () => {
    const onChange = vi.fn();
    render(
      <Slider
        label="Thickness"
        value={1.2}
        min={0.2}
        max={3.5}
        step={0.08}
        onChange={onChange}
      />,
    );

    const text = screen.getByLabelText("Thickness value") as HTMLInputElement;

    // Above max.
    fireEvent.focus(text);
    fireEvent.change(text, { target: { value: "9.9" } });
    fireEvent.blur(text);
    const above = onChange.mock.calls.at(-1)?.[0] as number;
    expect(above).toBeLessThanOrEqual(3.5);

    // Below min.
    fireEvent.focus(text);
    fireEvent.change(text, { target: { value: "-5" } });
    fireEvent.blur(text);
    const below = onChange.mock.calls.at(-1)?.[0] as number;
    expect(below).toBeGreaterThanOrEqual(0.2);
  });

  it("works with already-aligned min (no behavior change)", () => {
    const onChange = vi.fn();
    render(
      <Slider
        label="Gap"
        value={0.84}
        min={0.4}
        max={2.0}
        step={0.02}
        onChange={onChange}
      />,
    );

    const range = screen.getByLabelText("Gap") as HTMLInputElement;
    fireEvent.change(range, { target: { value: "0.86" } });
    const emitted = onChange.mock.calls.at(-1)?.[0] as number;
    expect(emitted).toBeCloseTo(0.86, 10);
    expect(isMultipleOfStep(emitted, 0.02)).toBe(true);
  });
});
