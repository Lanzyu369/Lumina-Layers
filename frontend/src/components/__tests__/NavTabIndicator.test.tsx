import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import TabNavBar from "../widget/TabNavBar";
import SubTabBar from "../widget/SubTabBar";
const indicatorAnimation = vi.hoisted(() => ({ complete: undefined as (() => void) | undefined }));

// jsdom runs no layout animation, so expose the props that decide when the
// selected chip slides instead of asserting on motion.
vi.mock("framer-motion", () => ({
  motion: {
    div: ({
      layoutId,
      layoutDependency,
      className,
      onLayoutAnimationComplete,
    }: {
      layoutId?: string;
      layoutDependency?: unknown;
      className?: string;
      children?: ReactNode;
      onLayoutAnimationComplete?: () => void;
    }) => {
      if (layoutId === "active-primary-tab-indicator") indicatorAnimation.complete = onLayoutAnimationComplete;
      return (
      <div
        data-testid="selected-chip"
        data-layout-id={layoutId}
        data-layout-dependency={layoutDependency === undefined ? "missing" : String(layoutDependency)}
        className={className}
      />
      );
    },
  },
}));

describe("selected tab chip", () => {
  it("notifies the page only when the primary indicator has finished moving", () => {
    const onComplete = vi.fn();
    const { rerender } = render(<TabNavBar activeTab="vectorizer" onTabChange={vi.fn()} onIndicatorAnimationComplete={onComplete} />);
    rerender(<TabNavBar activeTab="converter" onTabChange={vi.fn()} onIndicatorAnimationComplete={onComplete} />);
    expect(onComplete).not.toHaveBeenCalled();
    indicatorAnimation.complete?.();
    expect(onComplete).toHaveBeenCalledWith("converter");
  });

  it("slides between primary tabs only when the selected tab changes", () => {
    const { rerender } = render(<TabNavBar activeTab="converter" onTabChange={vi.fn()} />);
    const chip = () => screen.getByTestId("selected-chip");

    // A layoutDependency that stays the same across a render tells
    // framer-motion that header layout changes are not tab changes, so it
    // never replays the slide from the old screen position.
    expect(chip()).toHaveAttribute("data-layout-id", "active-primary-tab-indicator");
    expect(chip()).toHaveAttribute("data-layout-dependency", "converter");

    rerender(<TabNavBar activeTab="converter" onTabChange={vi.fn()} compact />);
    expect(chip()).toHaveAttribute("data-layout-dependency", "converter");

    rerender(<TabNavBar activeTab="settings" onTabChange={vi.fn()} />);
    expect(chip()).toHaveAttribute("data-layout-dependency", "settings");
  });

  it("gives every sub tab its own layout dependency", () => {
    const { rerender } = render(<SubTabBar activeTab="lut-library" onTabChange={vi.fn()} />);
    const chip = () => screen.getByTestId("selected-chip");

    expect(chip()).toHaveAttribute("data-layout-id", "active-secondary-tab-indicator");
    expect(chip()).toHaveAttribute("data-layout-dependency", "subtab-lut-library");

    rerender(<SubTabBar activeTab="five-color" onTabChange={vi.fn()} />);
    expect(chip()).toHaveAttribute("data-layout-dependency", "subtab-five-color");
  });
});
