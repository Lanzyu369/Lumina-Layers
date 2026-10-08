import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LuminaBoxWorkspace from "../components/LuminaBoxWorkspace";

vi.mock("../components/LuminaBoxMaterialPanel", () => ({ default: () => <div data-testid="material-capture-panel" /> }));
beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe("Lumina Box public workspace", () => {
  it.each(["model", "stack-samples", "backed-gradient"])("opens material capture even when the old %s tab was saved", (savedTab) => {
    localStorage.setItem("lumina-box-workspace-tab-v1", savedTab);
    render(<LuminaBoxWorkspace />);
    expect(screen.getByTestId("material-capture-panel")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByTestId("experimental-model-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("experimental-stack-panel")).not.toBeInTheDocument();
  });
});
