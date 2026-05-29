/**
 * Spec: svg-vector-outline-support / Task 1.1
 * Property 1 (Bug Condition): UI 必须允许 vector 模式下勾选 "启用外轮廓"。
 *
 * Bug condition methodology:
 *   - 当前 main 上 `OutlineSettings.tsx` 写死 `disabled={isVector}`，
 *     vector 模式下 checkbox 永远 disabled，本测试**期望失败** —— 失败即
 *     "bug 已被反例捕获"。
 *   - 工单引用: LUM-20260527-001 ("svg 加不了描边")。
 *
 * Validates: Requirements 1.1, 2.1
 */

import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import * as fc from "fast-check";

import OutlineSettings from "../components/sections/OutlineSettings";
import { useConverterStore } from "../stores/converter";
import { ModelingMode } from "../api/types";

/**
 * Reset only the slice of converter state this test cares about. Avoid
 * touching unrelated fields so other tests in the file (and the rest of the
 * test run) keep their defaults.
 * 仅重置本测试关心的字段，避免污染同进程内其他测试。
 */
function resetOutlineRelatedState(modeling_mode: ModelingMode): void {
  useConverterStore.setState({
    modeling_mode,
    enable_outline: false,
    outline_width: 2.0,
  } as never);
}

/**
 * Resolve the outline checkbox via its visible label. The component renders a
 * sr-only `<input type="checkbox">` wrapped in a label whose visible text is
 * the i18n string `outline_enable` (zh: "启用外轮廓", en: "Enable Outline").
 * `screen.getByLabelText` resolves the actual `<input>` so we can assert
 * `disabled` directly.
 * 通过可见标签拿到 sr-only checkbox 的 input 节点。
 */
function getOutlineCheckbox(): HTMLInputElement {
  return screen.getByLabelText(/启用外轮廓|Enable Outline/i) as HTMLInputElement;
}

/**
 * Click via the wrapping `<label>` instead of the sr-only `<input>` so the
 * test exercises the real user gesture. jsdom's `fireEvent.click` on a
 * disabled `<input>` does NOT honor `disabled` at the DOM-event level —
 * dispatching a synthetic click directly on the input bypasses the browser's
 * disabled-state filter and the React onChange handler still fires. Clicking
 * the label, however, walks through `HTMLLabelElement.click()` which mimics
 * the real browser path: a disabled input never fires onChange.
 * 真实用户点击的是包裹 input 的 <label>，而不是 sr-only 的 input 本身。
 * jsdom 上对 disabled input 直接 fireEvent.click 会绕过 disabled 状态，
 * 改点 label 才能复现"disabled 阻止 onChange"的真实浏览器行为。
 */
function clickOutlineLabel(): void {
  const checkbox = getOutlineCheckbox();
  const label = checkbox.closest("label");
  if (!label) {
    throw new Error("OutlineSettings checkbox <label> wrapper not found");
  }
  fireEvent.click(label);
}

describe("OutlineSettings — vector outline exploration (Task 1.1)", () => {
  beforeEach(() => {
    // Sanity reset so each iteration starts from a known modelling mode.
    // 每次断言前重置，避免迭代之间残留状态。
    resetOutlineRelatedState(ModelingMode.HIGH_FIDELITY);
  });

  // ---------------------------------------------------------------------
  // Reverse-direction sanity (currently PASSes on main) — guards against
  // selector typos that would also make the bug-condition assertion
  // trivially fail.
  // 反向断言，确保选择器没写错：非 vector 模式下 checkbox 必须可点击。
  // ---------------------------------------------------------------------

  it("non-vector modes leave the checkbox enabled (selector sanity)", () => {
    fc.assert(
      fc.property(
        fc.constantFrom<ModelingMode>(
          ModelingMode.HIGH_FIDELITY,
          ModelingMode.PIXEL,
        ),
        fc.boolean(),
        fc.double({ min: 0.5, max: 10.0, noNaN: true, noDefaultInfinity: true }),
        (mode, enable_outline, outline_width) => {
          resetOutlineRelatedState(mode);
          useConverterStore.setState({ enable_outline, outline_width } as never);
          const { unmount } = render(<OutlineSettings />);
          try {
            const checkbox = getOutlineCheckbox();
            expect(checkbox.disabled).toBe(false);
          } finally {
            unmount();
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  // ---------------------------------------------------------------------
  // Bug condition assertion (Property 1): vector 模式下 checkbox 必须可勾选。
  // 当前 main 上必失败 —— 失败即捕获 UI 拦截这一根因。
  // ---------------------------------------------------------------------

  it("vector mode allows the user to toggle enable_outline (currently fails on main)", () => {
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.double({ min: 0.5, max: 10.0, noNaN: true, noDefaultInfinity: true }),
        (enable_outline, outline_width) => {
          resetOutlineRelatedState(ModelingMode.VECTOR);
          useConverterStore.setState({ enable_outline, outline_width } as never);
          const { unmount } = render(<OutlineSettings />);
          try {
            const checkbox = getOutlineCheckbox();
            // Property 1: checkbox 必须不被 disabled 静默拦截。
            expect(checkbox.disabled).toBe(false);
            // 同时验证 onChange 真的能写入 store —— 避免出现"checkbox 没
            // disabled 但 onChange 被另一层吞掉"的隐性回归。
            const before = useConverterStore.getState().enable_outline;
            clickOutlineLabel();
            const after = useConverterStore.getState().enable_outline;
            expect(after).toBe(!before);
          } finally {
            unmount();
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  // ---------------------------------------------------------------------
  // 锚点：工单 LUM-20260527-001 的最小复现（确定性、非 PBT）。
  // ---------------------------------------------------------------------

  it("LUM-20260527-001 anchor: vector + outline_width=2.0 must be toggleable", () => {
    resetOutlineRelatedState(ModelingMode.VECTOR);
    useConverterStore.setState({ outline_width: 2.0 } as never);
    render(<OutlineSettings />);
    const checkbox = getOutlineCheckbox();
    expect(checkbox.disabled).toBe(false);
    clickOutlineLabel();
    expect(useConverterStore.getState().enable_outline).toBe(true);
  });
});
