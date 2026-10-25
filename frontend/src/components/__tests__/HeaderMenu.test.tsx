import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { HeaderMenu } from "../HeaderMenu";
import { DEFAULT_SETTINGS, useSettingsStore } from "../../stores/settingsStore";
import { useTutorialStore } from "../../stores/tutorialStore";

const INITIAL_TUTORIAL_STATE = useTutorialStore.getState();

function renderMenu(props: Partial<Parameters<typeof HeaderMenu>[0]> = {}) {
  const onReportBug = vi.fn();
  const view = render(
    <HeaderMenu
      backendStatus="ok"
      reproTicketId={null}
      onReportBug={onReportBug}
      {...props}
    />,
  );
  return { ...view, onReportBug };
}

function trigger() {
  return screen.getByTestId("header-menu-button");
}

async function expectClosed() {
  await waitFor(() => {
    expect(screen.queryByRole("button", { name: "反馈问题" })).not.toBeInTheDocument();
  });
  expect(trigger()).toHaveAttribute("aria-expanded", "false");
}

describe("HeaderMenu", () => {
  beforeEach(() => {
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  });

  afterEach(() => {
    useTutorialStore.setState(INITIAL_TUTORIAL_STATE, true);
  });

  it("keeps infrequent controls hidden until the menu opens", () => {
    renderMenu();

    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("header-menu-language")).not.toBeInTheDocument();
    expect(screen.getByText("更多选项")).toHaveAttribute("aria-hidden", "true");

    fireEvent.click(trigger());

    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByRole("button", { name: /切换语言/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "深色模式" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新手引导" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "反馈问题" })).toBeInTheDocument();
    expect(screen.getByTestId("health-badge-ok")).toHaveTextContent("后端已连接");
    // The hover hint would overlap the open panel, so it is not rendered.
    expect(screen.queryByText("更多选项")).not.toBeInTheDocument();
  });

  it("keeps language selection out of the header menu", () => {
    renderMenu();
    fireEvent.click(trigger());

    expect(screen.queryByTestId("header-menu-language")).not.toBeInTheDocument();
    expect(screen.queryByText("English")).not.toBeInTheDocument();
  });

  it("turns dark mode on from the menu", async () => {
    renderMenu();
    fireEvent.click(trigger());

    fireEvent.click(screen.getByRole("button", { name: "深色模式" }));

    expect(useSettingsStore.getState().theme).toBe("dark");
    await expectClosed();
    expect(trigger()).toHaveFocus();
  });

  it("replays the beginner tour from the menu", async () => {
    const startTour = vi.fn();
    useTutorialStore.setState({ startTour });
    renderMenu();
    fireEvent.click(trigger());

    fireEvent.click(screen.getByRole("button", { name: "新手引导" }));

    expect(startTour).toHaveBeenCalledWith("manual");
    await expectClosed();
  });

  it("opens the bug report from the menu", async () => {
    const { onReportBug } = renderMenu();
    fireEvent.click(trigger());

    fireEvent.click(screen.getByRole("button", { name: "反馈问题" }));

    expect(onReportBug).toHaveBeenCalledTimes(1);
    await expectClosed();
  });

  it("opens credits from a labelled row and closes the menu", async () => {
    const onOpenCredits = vi.fn();
    renderMenu({ onOpenCredits });
    fireEvent.click(trigger());
    fireEvent.click(screen.getByRole("button", { name: "致谢" }));
    expect(onOpenCredits).toHaveBeenCalledTimes(1);
    await expectClosed();
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    renderMenu();
    fireEvent.click(trigger());
    screen.getByRole("button", { name: "深色模式" }).focus();

    fireEvent.keyDown(document, { key: "Escape" });

    await expectClosed();
    expect(trigger()).toHaveFocus();
  });

  it("leaves Escape alone when another control already handled it", () => {
    renderMenu();
    fireEvent.click(trigger());

    const handled = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    handled.preventDefault();
    document.dispatchEvent(handled);

    expect(trigger()).toHaveAttribute("aria-expanded", "true");
  });

  it("closes when the user presses outside the menu", async () => {
    renderMenu();
    fireEvent.click(trigger());

    fireEvent.mouseDown(document.body);

    await expectClosed();
  });

  it("closes without taking focus back when keyboard focus leaves the menu", async () => {
    render(
      <>
        <HeaderMenu backendStatus="ok" reproTicketId={null} onReportBug={vi.fn()} />
        <button type="button">Next control</button>
      </>,
    );
    fireEvent.click(trigger());

    const outside = screen.getByRole("button", { name: "Next control" });
    outside.focus();

    await expectClosed();
    expect(outside).toHaveFocus();
  });

  it("stays open when the status area is clicked", () => {
    renderMenu();
    fireEvent.click(trigger());

    fireEvent.click(screen.getByTestId("health-badge-ok"));

    expect(trigger()).toHaveAttribute("aria-expanded", "true");
  });

  it("marks the trigger only when the backend is unreachable or a bug is being reproduced", () => {
    const { rerender } = renderMenu({ backendStatus: "checking" });
    expect(screen.queryByTestId("header-menu-alert")).not.toBeInTheDocument();
    expect(trigger()).not.toHaveAttribute("aria-describedby");

    rerender(<HeaderMenu backendStatus="ok" reproTicketId={null} onReportBug={vi.fn()} />);
    expect(screen.queryByTestId("header-menu-alert")).not.toBeInTheDocument();

    rerender(<HeaderMenu backendStatus="fail" reproTicketId={null} onReportBug={vi.fn()} />);
    expect(screen.getByTestId("header-menu-alert")).toHaveClass("bg-red-500");
    // aria-label names the button, so the alert must reach screen readers
    // as the description.
    expect(trigger()).toHaveAccessibleName("更多选项");
    expect(trigger()).toHaveAccessibleDescription("后端不可达");

    rerender(<HeaderMenu backendStatus="ok" reproTicketId="T-123" onReportBug={vi.fn()} />);
    expect(screen.getByTestId("header-menu-alert")).toHaveClass("bg-amber-600");
    expect(trigger()).toHaveAccessibleDescription("复现模式");
    fireEvent.click(trigger());
    expect(screen.getByTestId("repro-mode-badge")).toHaveTextContent("复现模式 · T-123");
  });

  it("anchors the tutorial's help step on the trigger", () => {
    renderMenu();

    expect(trigger()).toHaveAttribute("data-tutorial", "tutorial-launcher");
  });
});
