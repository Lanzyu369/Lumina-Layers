/**
 * Slider value-preservation regression tests.
 *
 * Background: native `<input type="range">` anchors its step grid to `min`,
 * so min=0.2/step=0.08 emits values like 0.2, 0.28, 0.36, ..., 3.48. A
 * previous implementation re-aligned these to a 0-anchored grid (multiples
 * of `step`), which systematically bumped every drag emission up by half a
 * step (e.g. 1.16 → 1.20, 1.24 → 1.28). Users perceived that as the slider
 * "auto-adding 0.08" every time they released it. The current Slider only
 * clamps to [min, max] and rounds to the step's display precision, so the
 * native-emitted value is preserved.
 *
 * 背景：原生 `<input type="range">` 的 step 网格以 `min` 为锚点，
 * min=0.2/step=0.08 会发出 0.2、0.28、0.36…3.48 等值。旧实现把这些值重新对齐
 * 到以 0 为锚点的网格（step 的整数倍），结果每次拖动都会被向上平移半格
 * （例如 1.16→1.20、1.24→1.28），用户感觉"一松手就自动加 0.08"。现在的
 * Slider 只做 [min, max] 夹紧与按 step 小数位取整，保留浏览器原生值。
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import Slider from "../Slider";

describe("Slider value preservation", () => {
  it("range onChange preserves the browser-emitted value without shifting up half a step", () => {
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

    // Native range with min=0.2, step=0.08 emits values like 1.16 / 1.24
    // (= 0.2 + n*0.08). These must pass through unchanged — re-aligning
    // them to a 0-anchored grid would bump every emission up by half a
    // step and feel like an "auto +0.08" on release.
    fireEvent.change(range, { target: { value: "1.16" } });
    expect(onChange.mock.calls.at(-1)?.[0]).toBeCloseTo(1.16, 10);

    fireEvent.change(range, { target: { value: "1.24" } });
    expect(onChange.mock.calls.at(-1)?.[0]).toBeCloseTo(1.24, 10);

    fireEvent.change(range, { target: { value: "0.2" } });
    expect(onChange.mock.calls.at(-1)?.[0]).toBeCloseTo(0.2, 10);
  });

  it("text input commit preserves precise values without snapping to the step grid", () => {
    // Regression: previously the text input also force-snapped to the step
    // grid, so typing 1.5 became 1.52. The text input is the precise-entry
    // path; it must only clamp to [min, max] and round to display precision.
    // 回归：此前文本输入也会强制对齐到 step 网格，导致手动输入 1.5 变成
    // 1.52。文本框作为精确输入路径，仅做 [min, max] 夹紧与显示精度圆整。
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
    fireEvent.change(text, { target: { value: "1.5" } });
    fireEvent.blur(text);
    expect(onChange.mock.calls.at(-1)?.[0]).toBeCloseTo(1.5, 10);

    fireEvent.focus(text);
    fireEvent.change(text, { target: { value: "3.5" } });
    fireEvent.blur(text);
    expect(onChange.mock.calls.at(-1)?.[0]).toBeCloseTo(3.5, 10);

    fireEvent.focus(text);
    fireEvent.change(text, { target: { value: "1.17" } });
    fireEvent.blur(text);
    // 1.17 rounded to 2 decimals (step=0.08 has 2 decimals) stays 1.17,
    // not snapped to the nearest 0.08 multiple.
    expect(onChange.mock.calls.at(-1)?.[0]).toBeCloseTo(1.17, 10);
  });

  it("uses an optional text normalizer for both the emitted and displayed value", () => {
    const onChange = vi.fn();
    render(
      <Slider
        label="Thickness"
        value={0.32}
        min={0.24}
        max={3.44}
        step={0.08}
        onChange={onChange}
        normalizeTextValue={() => 0.32}
      />,
    );

    const text = screen.getByLabelText("Thickness value") as HTMLInputElement;
    fireEvent.focus(text);
    fireEvent.change(text, { target: { value: "0.36" } });
    fireEvent.blur(text);

    expect(onChange).toHaveBeenLastCalledWith(0.32);
    expect(text).toHaveValue("0.32");
  });

  it("clamps text input into [min, max]", () => {
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
    fireEvent.change(text, { target: { value: "9.9" } });
    fireEvent.blur(text);
    expect(onChange.mock.calls.at(-1)?.[0]).toBeLessThanOrEqual(3.5);

    fireEvent.focus(text);
    fireEvent.change(text, { target: { value: "-5" } });
    fireEvent.blur(text);
    expect(onChange.mock.calls.at(-1)?.[0]).toBeGreaterThanOrEqual(0.2);
  });

  it("passes through already-aligned values unchanged", () => {
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
    expect(onChange.mock.calls.at(-1)?.[0]).toBeCloseTo(0.86, 10);
  });
});
