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

  it("closing the welcome with Escape counts as skipping", () => {
    render(<TutorialHost canAutoOffer />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(readTutorialProgress()?.outcome).toBe("skipped");
  });
});
