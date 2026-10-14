/**
 * Ghost-button / flattened-shell regression coverage.
 * 幽灵按钮与扁平外壳的回归测试。
 *
 * These tests pin the two contracts that make the "少框" layout hold:
 *  1. Interactive controls must not carry a `shadow-*` utility, because the
 *     global rule in index.css strips box-shadow from any matching class
 *     string and Tailwind draws `ring-*` with box-shadow — a stray `shadow-`
 *     utility silently kills the keyboard focus ring.
 *  2. Ghost controls stay visible (never `opacity-0`) and expose their toggled
 *     state through `aria-pressed` so the "boundary appears on hover" style
 *     still has an accessible on/off state.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Button from "../components/ui/Button";
import Checkbox from "../components/ui/Checkbox";
import RadioGroup from "../components/ui/RadioGroup";
import Slider from "../components/ui/Slider";
import { WidgetPanel } from "../components/widget/WidgetPanel";

const readSource = (relativePath: string) =>
  readFileSync(resolve(process.cwd(), "src", relativePath), "utf-8");

describe("Button ghost variant", () => {
  it("renders the ghost control class without a shadow utility", () => {
    render(<Button label="查看分层" variant="ghost" onClick={vi.fn()} />);

    const button = screen.getByRole("button", { name: "查看分层" });
    expect(button).toHaveClass("ghost-control");
    expect(button.className).not.toMatch(/shadow-/);
  });

  it("exposes the toggled state through aria-pressed and data-active", () => {
    render(<Button label="画笔" variant="ghost" active onClick={vi.fn()} />);

    const button = screen.getByRole("button", { name: "画笔" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button).toHaveAttribute("data-active", "true");

    render(<Button label="同色" variant="ghost" onClick={vi.fn()} />);
    expect(screen.getByRole("button", { name: "同色" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("carries the destructive tone only on ghost buttons", () => {
    render(<Button label="删除" variant="ghost" tone="danger" onClick={vi.fn()} />);
    expect(screen.getByRole("button", { name: "删除" })).toHaveAttribute(
      "data-tone",
      "danger",
    );

    render(
      <Button label="生成" variant="primary" tone="danger" onClick={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "生成" })).not.toHaveAttribute(
      "data-tone",
    );
  });

  it("renders a leading icon next to the label", () => {
    render(
      <Button
        label="导出分享卡"
        variant="ghost"
        leadingIcon={<svg data-testid="leading-icon" />}
        onClick={vi.fn()}
      />,
    );

    const button = screen.getByRole("button", { name: "导出分享卡" });
    expect(button.querySelector('[data-testid="leading-icon"]')).not.toBeNull();
    expect(screen.getByText("导出分享卡")).toHaveClass("whitespace-nowrap");
  });

  it("never emits a shadow utility in any variant or size", () => {
    const variants = ["primary", "secondary", "ghost"] as const;
    const sizes = ["sm", "md", "icon"] as const;

    for (const variant of variants) {
      for (const size of sizes) {
        const { unmount } = render(
          <Button
            label={`probe-${variant}-${size}`}
            variant={variant}
            size={size}
            onClick={vi.fn()}
          />,
        );
        const button = screen.getByRole("button", {
          name: `probe-${variant}-${size}`,
        });
        expect(
          button.className,
          `Button variant=${variant} size=${size} must not carry shadow-*`,
        ).not.toMatch(/shadow-/);
        unmount();
      }
    }
  });

  it("uses focus-visible (not focus) for the keyboard focus ring", () => {
    render(<Button label="预览" variant="secondary" onClick={vi.fn()} />);
    const button = screen.getByRole("button", { name: "预览" });
    expect(button.className).toContain("focus-visible:ring-2");
    expect(button.className).not.toContain("focus:ring-4");
  });
});

describe("Ghost control CSS contract", () => {
  const css = readSource("index.css");

  it("hides the boundary at rest but never hides the control", () => {
    const block = css.slice(css.indexOf(".ghost-control {"));
    expect(block).toContain("border: 1px solid transparent");
    expect(css).not.toMatch(/\.ghost-control\s*\{[^}]*opacity:\s*0/);
  });

  it("shows the boundary on hover and on keyboard focus", () => {
    expect(css).toContain(".ghost-control:hover:not(:disabled)");
    expect(css).toContain(".ghost-control:focus-visible");
    expect(css).toContain(".ghost-control[aria-pressed=\"true\"]");
  });

  it("keeps a resting boundary for touch devices, which have no hover", () => {
    expect(css).toMatch(/@media \(hover: none\)/);
  });
});

describe("Selectable rows drop their border", () => {
  it("leaves the checkbox row transparent at rest", () => {
    render(<Checkbox label="模型覆面" checked={false} onChange={vi.fn()} />);
    const row = screen.getByText("模型覆面").closest("label");
    expect(row).not.toBeNull();
    // Tests elsewhere locate this row by the radius token, so it must survive.
    expect(row!).toHaveClass("rounded-[10px]");
    expect(row!.className).toContain("border-transparent");
    expect(row!.className).not.toMatch(/border-slate-200/);
  });

  it("leaves the radio row transparent at rest", () => {
    render(
      <RadioGroup
        label="结构模式"
        value="double"
        options={[
          { label: "双面", value: "double" },
          { label: "单面", value: "single" },
        ]}
        onChange={vi.fn()}
      />,
    );
    const row = screen.getByText("双面").closest("label");
    expect(row).not.toBeNull();
    expect(row!).toHaveClass("rounded-[10px]");
    expect(row!.className).toContain("border-transparent");
  });
});

describe("Slider drops its bordered shell", () => {
  it("renders the value box without an outer bordered frame", () => {
    const { container } = render(
      <Slider label="宽度" value={60} min={10} max={300} step={1} onChange={vi.fn()} unit="mm" />,
    );

    const valueBox = screen.getByRole("textbox", { name: /宽度 value/i });
    expect(valueBox).toBeInTheDocument();
    expect(valueBox.className).toContain("border-transparent");
    expect(valueBox.className).not.toMatch(/shadow-/);

    // The old shell was the only `rounded-2xl border` wrapper in this control.
    expect(container.querySelector(".rounded-2xl")).toBeNull();
    expect(screen.getByRole("slider", { name: "宽度" })).toBeInTheDocument();
  });
});

describe("Widget shell is the single card level", () => {
  it("uses panel-card and the 16px radius", () => {
    render(
      <WidgetPanel widgetId="basic-settings" titleKey="widget_basic_settings">
        <div>content</div>
      </WidgetPanel>,
    );

    const panel = document.querySelector('[data-widget-id="basic-settings"]');
    expect(panel).not.toBeNull();
    expect(panel!).toHaveClass("panel-card");
    expect(panel!.className).not.toMatch(/shadow-/);
    expect(panel!.getAttribute("style")).toContain("border-radius: 16px");
  });
});
