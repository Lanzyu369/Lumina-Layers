import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../analytics/umami", () => ({ trackLuminaEvent: vi.fn() }));
vi.mock("../TutorialTour", () => ({
  default: () => <div data-testid="tutorial-tour-stub" />,
}));

import { translations } from "../../../i18n/translations";
import { useTutorialStore } from "../../../stores/tutorialStore";
import { readTutorialProgress } from "../../../utils/tutorialProgress";
import { TutorialHost } from "../TutorialHost";

// setupTests.ts renders the Chinese copy for every t() call.
const zh = (key: string) => translations[key].zh;

describe("TutorialHost", () => {
  beforeEach(() => {
    localStorage.clear();
    useTutorialStore.setState({ phase: "idle", stepIndex: 0, trigger: "auto", startedAtMs: null });
  });

  afterEach(() => {
    cleanup();
  });

  it("waits until other dialogs are gone before offering", () => {
    const { rerender } = render(<TutorialHost canAutoOffer={false} />);
    expect(screen.queryByTestId("tutorial-welcome-dialog")).not.toBeInTheDocument();

    rerender(<TutorialHost canAutoOffer />);
    expect(screen.getByTestId("tutorial-welcome-dialog")).toBeInTheDocument();
  });

  it("starts the tour from the welcome dialog", () => {
    render(<TutorialHost canAutoOffer />);

    fireEvent.click(screen.getByText(zh("tutorial_welcome_start")));

    expect(useTutorialStore.getState()).toMatchObject({ phase: "touring", trigger: "auto" });
    expect(screen.getByTestId("tutorial-tour-stub")).toBeInTheDocument();
  });

  it("offers only once, even after a remount", () => {
    const first = render(<TutorialHost canAutoOffer />);
    fireEvent.click(screen.getByText(zh("tutorial_welcome_skip")));
    expect(screen.queryByTestId("tutorial-welcome-dialog")).not.toBeInTheDocument();
    expect(readTutorialProgress()?.outcome).toBe("skipped");
    first.unmount();

    render(<TutorialHost canAutoOffer />);
    expect(screen.queryByTestId("tutorial-welcome-dialog")).not.toBeInTheDocument();
  });

  it("focuses Start and keeps Tab inside the welcome dialog", () => {
    const outside = document.createElement("button");
    outside.textContent = "background";
    document.body.appendChild(outside);
    render(<TutorialHost canAutoOffer />);

    const start = screen.getByText(zh("tutorial_welcome_start")).closest("button");
    expect(start).toHaveFocus();

    outside.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    const dialog = screen.getByTestId("tutorial-welcome-dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);

    start?.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(dialog.contains(document.activeElement)).toBe(true);
    outside.remove();
  });

  it("lets the welcome text scroll so the actions stay reachable", () => {
    render(<TutorialHost canAutoOffer />);
    expect(screen.getByTestId("tutorial-welcome-dialog")).toHaveClass("max-h-[calc(100dvh-32px)]");
    const body = screen.getByTestId("tutorial-welcome-body");
    expect(body).toHaveClass("overflow-y-auto", "min-h-0");
    expect(body.contains(screen.getByText(zh("tutorial_welcome_start")))).toBe(false);
  });

  it("closing the welcome with Escape counts as skipping", () => {
    render(<TutorialHost canAutoOffer />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(readTutorialProgress()?.outcome).toBe("skipped");
  });
});
