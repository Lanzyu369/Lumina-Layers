/**
 * Spec: svg-vector-outline-support / Task 1.5 (revised)
 * Property 1 (Bug Condition): UI 拦截 → buildAdvancedParams 端到端必须忠实写入用户意图。
 *
 * 方案修正背景:
 *   原方案是"喂后端 _sanitize_advanced_params 一个 enable_outline=true"，
 *   sanity check 后改为前端 UI → buildAdvancedParams 端到端测试。
 *   原因: 后端 _sanitize_advanced_params 是 round-trip 透传，给它直接喂
 *   enable_outline=true 不会失败，无法证伪 bug。真正的"用户意图被静默丢弃"
 *   发生在 OutlineSettings 的 disabled={isVector}：Checkbox 拦截 onChange，
 *   store.enable_outline 始终保持 false，buildAdvancedParams 端到端读到的
 *   永远是 false。
 *
 * 当前 main 必失败，失败即"bug 已被反例捕获"。
 *
 * 工单引用: LUM-20260527-001 ("svg 加不了描边")。
 *
 * Validates: Requirements 1.4, 2.4
 */

import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import * as fc from "fast-check";

import OutlineSettings from "../components/sections/OutlineSettings";
import { useConverterStore } from "../stores/converter";
import { ModelingMode } from "../api/types";
import { buildAdvancedParams } from "../utils/advancedParamsBuilder";
import type { AdvancedParamsFull } from "../types/actionHistory";

function getOutlineCheckbox(): HTMLInputElement {
  return screen.getByLabelText(/启用外轮廓|Enable Outline/i) as HTMLInputElement;
}

/**
 * Click via the wrapping `<label>` instead of the sr-only `<input>` so that
 * jsdom honors the input's `disabled` attribute the same way a real browser
 * would (a disabled input never fires `onChange`). Calling `fireEvent.click`
 * directly on the sr-only `<input>` would bypass disabled and let onChange
 * fire, masking the bug.
 * 点击 <label> 而非 sr-only 的 <input>，让 jsdom 真实尊重 disabled。
 */
function clickOutlineLabel(): void {
  const checkbox = getOutlineCheckbox();
  const label = checkbox.closest("label");
  if (!label) {
    throw new Error("OutlineSettings checkbox <label> wrapper not found");
  }
  fireEvent.click(label);
}

/**
 * Seed only the fields needed for this test; do not nuke the rest of the
 * store (other fields keep DEFAULT_STATE values via initial setup).
 * 仅设置本测试相关字段；其余字段保留默认。
 */
function seedVectorOutlineDisabledState(outlineWidth: number): void {
  useConverterStore.setState({
    modeling_mode: ModelingMode.VECTOR,
    enable_outline: false,
    outline_width: outlineWidth,
  } as never);
}

describe("UI -> buildAdvancedParams vector outline (Task 1.5)", () => {
  beforeEach(() => {
    seedVectorOutlineDisabledState(2.0);
  });

  it("vector mode: clicking checkbox flips store.enable_outline to true (currently fails)", () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0.5, max: 10.0, noNaN: true, noDefaultInfinity: true }),
        (outlineWidth) => {
          seedVectorOutlineDisabledState(outlineWidth);
          const { unmount } = render(<OutlineSettings />);
          try {
            const checkbox = getOutlineCheckbox();
            // 用户的真实意图：勾选启用描边（点击 label 触发真实浏览器路径）
            clickOutlineLabel();
            void checkbox;  // eslint guard: keep accessor symmetric
            // Property 1: 用户点击后 store.enable_outline 应该是 true。
            // 当前 main 上 disabled={isVector} 阻止 onChange，永远是 false。
            expect(useConverterStore.getState().enable_outline).toBe(true);
          } finally {
            unmount();
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it("vector mode: buildAdvancedParams.outline.enable_outline ends up true (currently fails)", () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0.5, max: 10.0, noNaN: true, noDefaultInfinity: true }),
        (outlineWidth) => {
          seedVectorOutlineDisabledState(outlineWidth);
          const { unmount } = render(<OutlineSettings />);
          try {
            clickOutlineLabel();
            const advanced = buildAdvancedParams(
              useConverterStore.getState(),
              "converter",
              { maxBytes: 8192 },
            ) as AdvancedParamsFull;
            // Property 1: ticket 里 advanced_params.outline.enable_outline
            // 必须忠实记录用户意图（true）。当前 main 因 UI 拦截恒为 false。
            expect(advanced.outline.enable_outline).toBe(true);
          } finally {
            unmount();
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it("LUM-20260527-001 anchor: vector + outline_width=2.0 ticket 必须写入 enable_outline=true", () => {
    seedVectorOutlineDisabledState(2.0);
    render(<OutlineSettings />);
    clickOutlineLabel();

    expect(useConverterStore.getState().enable_outline).toBe(true);

    const advanced = buildAdvancedParams(
      useConverterStore.getState(),
      "converter",
      { maxBytes: 8192 },
    ) as AdvancedParamsFull;
    expect(advanced.outline.enable_outline).toBe(true);
    expect(advanced.outline.outline_width).toBe(2.0);
  });
});
