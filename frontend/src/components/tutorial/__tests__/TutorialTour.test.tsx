import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../analytics/umami", () => ({ trackLuminaEvent: vi.fn() }));

import { trackLuminaEvent } from "../../../analytics/umami";
import { TUTORIAL_STEPS } from "../../../data/tutorialSteps";
import { TUTORIAL_ANCHOR_TIMEOUT_MS } from "../../../hooks/useTutorialAnchor";
import { translations } from "../../../i18n/translations";
import { useTutorialStore } from "../../../stores/tutorialStore";
import { readTutorialProgress } from "../../../utils/tutorialProgress";
import TutorialTour from "../TutorialTour";

// setupTests.ts renders the Chinese copy for every t() call.
const zh = (key: string) => translations[key].zh;

function mountAnchor(anchor: string): HTMLElement {
  const element = document.createElement("div");
  element.setAttribute("data-tutorial", anchor);
  element.getBoundingClientRect = () =>
    ({ top: 20, left: 40, width: 600, height: 48, right: 640, bottom: 68, x: 40, y: 20, toJSON: () => ({}) }) as DOMRect;
  document.body.appendChild(element);
  return element;
}

function startTourAt(stepIndex: number) {
  useTutorialStore.getState().startTour("manual");
  useTutorialStore.setState({ stepIndex });
}

describe("TutorialTour", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(trackLuminaEvent).mockClear();
    useTutorialStore.setState({ phase: "idle", stepIndex: 0, trigger: "auto", startedAtMs: null });
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) =>
      window.setTimeout(() => cb(performance.now()), 16),
    );
    vi.stubGlobal("cancelAnimationFrame", (id: number) => window.clearTimeout(id));
  });

  afterEach(() => {
    cleanup();
    document.querySelectorAll("[data-tutorial]").forEach((node) => node.remove());
    vi.unstubAllGlobals();
  });

  it("spotlights the step anchor and shows the step copy", async () => {
    mountAnchor("primary-tabs");
    startTourAt(0);
    render(<TutorialTour />);

    expect(await screen.findByTestId("tutorial-spotlight")).toBeInTheDocument();
    expect(screen.getByText(zh("tutorial_step_tabs_title"))).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-card")).toHaveAttribute("data-side", "bottom");
    expect(screen.queryByText(zh("tutorial_back"))).not.toBeInTheDocument();
  });

  it("falls back to a centered card when the anchor never appears", async () => {
    startTourAt(0);
    render(<TutorialTour />);

    // While searching the card is hidden; it becomes visible once the anchor
    // is declared missing.
    expect(screen.getByTestId("tutorial-card")).not.toBeVisible();
    await waitFor(() => expect(screen.getByTestId("tutorial-card")).toBeVisible(), {
      timeout: TUTORIAL_ANCHOR_TIMEOUT_MS + 1000,
    });
    expect(screen.getByTestId("tutorial-card")).toHaveAttribute("data-side", "center");
    expect(screen.queryByTestId("tutorial-spotlight")).not.toBeInTheDocument();
  });

  it("renders the principle flow and requirement lines for color sources", async () => {
    const legacyIndex = TUTORIAL_STEPS.findIndex((step) => step.id === "source-legacy-lut");
    mountAnchor("color-source");
    startTourAt(legacyIndex);
    render(<TutorialTour />);

    const flow = await screen.findByTestId("tutorial-flow");
    expect(flow.querySelectorAll("li")).toHaveLength(3);
    expect(screen.getByText(zh("tutorial_step_legacy_need"))).toBeInTheDocument();
    expect(screen.getByText(zh("tutorial_step_legacy_fit"))).toBeInTheDocument();
  });

  it("moves forward and back with the buttons and arrow keys", async () => {
    mountAnchor("primary-tabs");
    startTourAt(0);
    render(<TutorialTour />);

    fireEvent.click(await screen.findByText(zh("tutorial_next")));
    expect(useTutorialStore.getState().stepIndex).toBe(1);

    fireEvent.click(screen.getByText(zh("tutorial_back")));
    expect(useTutorialStore.getState().stepIndex).toBe(0);

    act(() => {
      fireEvent.keyDown(document, { key: "ArrowRight" });
    });
    expect(useTutorialStore.getState().stepIndex).toBe(1);
    act(() => {
      fireEvent.keyDown(document, { key: "ArrowLeft" });
    });
    expect(useTutorialStore.getState().stepIndex).toBe(0);
  });

  it("skips in one click", async () => {
    startTourAt(3);
    render(<TutorialTour />);

    fireEvent.click(screen.getByTestId("tutorial-skip-button"));

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(readTutorialProgress()?.outcome).toBe("skipped");
    expect(trackLuminaEvent).toHaveBeenCalledWith(
      "lumina_tutorial_skipped",
      expect.objectContaining({ via: "skip_button", step_index: 4 }),
    );
  });

  it("skips with the Escape key", () => {
    startTourAt(0);
    render(<TutorialTour />);

    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(trackLuminaEvent).toHaveBeenCalledWith(
      "lumina_tutorial_skipped",
      expect.objectContaining({ via: "escape" }),
    );
  });

  it("finishes from the last step", async () => {
    mountAnchor("tutorial-launcher");
    startTourAt(TUTORIAL_STEPS.length - 1);
    render(<TutorialTour />);

    fireEvent.click(await screen.findByText(zh("tutorial_done")));

    expect(useTutorialStore.getState().phase).toBe("idle");
    expect(readTutorialProgress()?.outcome).toBe("completed");
  });

  it("covers the app with a click shield that does not end the tour", () => {
    startTourAt(0);
    render(<TutorialTour />);

    const shield = screen.getByTestId("tutorial-click-shield");
    expect(shield).toHaveClass("absolute", "inset-0");
    fireEvent.click(shield);

    expect(useTutorialStore.getState().phase).toBe("touring");
  });
});
