import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LuminaBoxWorkspace from "../components/LuminaBoxWorkspace";
import { translations } from "../i18n/translations";
import { useLuminaBoxBackedGradientSerialStore } from "../stores/luminaBoxBackedGradientSerialStore";
import { useLuminaBoxStackSerialStore } from "../stores/luminaBoxStackSerialStore";

vi.mock("../components/LuminaBoxMaterialPanel", () => ({ default: () => <div data-testid="material-capture-panel" /> }));
vi.mock("../components/LuminaBoxStackSamplesPanel", () => ({ default: () => <div data-testid="experimental-stack-panel" /> }));
// The model and backed-gradient screens live on the local-only experiment
// branch, so they are neither imported nor mocked here. The queries below
// still pin that no such panel renders for a stale saved tab.

const legacyStorageKey = "lumina-box-workspace-tab-v1";
const materialTab = () => screen.getByTestId("lumina-box-workspace-material");
const stackTab = () => screen.getByTestId("lumina-box-workspace-stack-samples");

function pendingDisconnect() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  localStorage.clear();
  useLuminaBoxBackedGradientSerialStore.setState({
    status: "disconnected", disconnect: vi.fn(async () => undefined),
  });
  useLuminaBoxStackSerialStore.setState({
    status: "disconnected", disconnect: vi.fn(async () => undefined),
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Lumina Box public workspace", () => {
  it.each(["model", "stack-samples", "backed-gradient"])("opens material capture even when the old %s tab was saved", (savedTab) => {
    localStorage.setItem(legacyStorageKey, savedTab);
    render(<LuminaBoxWorkspace />);
    expect(screen.getByTestId("material-capture-panel")).toBeInTheDocument();
    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(materialTab()).toHaveAttribute("aria-selected", "true");
    expect(stackTab()).toHaveAttribute("aria-selected", "false");
    expect(screen.queryByTestId("experimental-model-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("experimental-stack-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("experimental-gradient-panel")).not.toBeInTheDocument();
  });

  it("mounts only the selected capture page and releases the corresponding connection in both directions", async () => {
    render(<LuminaBoxWorkspace />);
    fireEvent.click(stackTab());
    await screen.findByTestId("experimental-stack-panel");
    expect(screen.queryByTestId("material-capture-panel")).not.toBeInTheDocument();
    expect(useLuminaBoxBackedGradientSerialStore.getState().disconnect).toHaveBeenCalledOnce();
    expect(useLuminaBoxStackSerialStore.getState().disconnect).not.toHaveBeenCalled();
    expect(stackTab()).toHaveAttribute("aria-selected", "true");

    fireEvent.click(materialTab());
    await screen.findByTestId("material-capture-panel");
    expect(screen.queryByTestId("experimental-stack-panel")).not.toBeInTheDocument();
    expect(useLuminaBoxStackSerialStore.getState().disconnect).toHaveBeenCalledOnce();
    expect(useLuminaBoxBackedGradientSerialStore.getState().disconnect).toHaveBeenCalledOnce();
    expect(screen.queryByTestId("experimental-model-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("experimental-gradient-panel")).not.toBeInTheDocument();
  });

  it("starts with material capture again after remount without persisting a stack selection", async () => {
    localStorage.setItem(legacyStorageKey, "backed-gradient");
    const view = render(<LuminaBoxWorkspace />);
    fireEvent.click(stackTab());
    await screen.findByTestId("experimental-stack-panel");
    expect(localStorage.getItem(legacyStorageKey)).toBe("backed-gradient");
    view.unmount();

    render(<LuminaBoxWorkspace />);
    expect(screen.getByTestId("material-capture-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("experimental-stack-panel")).not.toBeInTheDocument();
    expect(localStorage.getItem(legacyStorageKey)).toBe("backed-gradient");
  });

  it("keeps the current page mounted and disables both tabs while disconnect is pending", async () => {
    const pending = pendingDisconnect();
    useLuminaBoxBackedGradientSerialStore.setState({
      status: "connected",
      disconnect: vi.fn(() => {
        useLuminaBoxBackedGradientSerialStore.setState({ status: "disconnecting" });
        return pending.promise;
      }),
    });
    render(<LuminaBoxWorkspace />);
    fireEvent.click(stackTab());
    expect(screen.getByTestId("material-capture-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("experimental-stack-panel")).not.toBeInTheDocument();
    expect(materialTab()).toBeDisabled();
    expect(stackTab()).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(translations.lumina_box_workspace_disconnecting.zh);

    await act(async () => {
      useLuminaBoxBackedGradientSerialStore.setState({ status: "disconnected" });
      pending.resolve();
    });
    expect(screen.getByTestId("experimental-stack-panel")).toBeInTheDocument();
    expect(materialTab()).not.toBeDisabled();
    expect(stackTab()).not.toBeDisabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("keeps the old page when disconnect finishes without releasing the port and allows a retry", async () => {
    const disconnect = vi.fn(async () => {
      useLuminaBoxBackedGradientSerialStore.setState({ status: "disconnecting" });
    });
    useLuminaBoxBackedGradientSerialStore.setState({ status: "connected", disconnect });
    render(<LuminaBoxWorkspace />);
    fireEvent.click(stackTab());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(translations.lumina_box_workspace_switch_failed.zh));
    expect(screen.getByTestId("material-capture-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("experimental-stack-panel")).not.toBeInTheDocument();
    expect(materialTab()).not.toBeDisabled();
    expect(stackTab()).not.toBeDisabled();

    disconnect.mockImplementationOnce(async () => {
      useLuminaBoxBackedGradientSerialStore.setState({ status: "disconnected" });
    });
    fireEvent.click(stackTab());
    await screen.findByTestId("experimental-stack-panel");
    expect(disconnect).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("also refuses to leave stack capture while its connection remains open", async () => {
    render(<LuminaBoxWorkspace />);
    fireEvent.click(stackTab());
    await screen.findByTestId("experimental-stack-panel");
    useLuminaBoxStackSerialStore.setState({
      status: "connected",
      disconnect: vi.fn(async () => {
        useLuminaBoxStackSerialStore.setState({ status: "disconnecting" });
      }),
    });

    fireEvent.click(materialTab());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(translations.lumina_box_workspace_switch_failed.zh));
    expect(screen.getByTestId("experimental-stack-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("material-capture-panel")).not.toBeInTheDocument();
    expect(useLuminaBoxStackSerialStore.getState().disconnect).toHaveBeenCalledOnce();
    expect(materialTab()).not.toBeDisabled();
  });

  it("shows a retryable failure when disconnect rejects", async () => {
    useLuminaBoxBackedGradientSerialStore.setState({
      status: "connected",
      disconnect: vi.fn(async () => { throw new Error("port_close_failed"); }),
    });
    render(<LuminaBoxWorkspace />);
    fireEvent.click(stackTab());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(translations.lumina_box_workspace_switch_failed.zh));
    expect(screen.getByTestId("material-capture-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("experimental-stack-panel")).not.toBeInTheDocument();
    expect(materialTab()).not.toBeDisabled();
    expect(stackTab()).not.toBeDisabled();
  });

  it("supports keyboard wraparound and Home/End navigation with focus on the selected tab", async () => {
    render(<LuminaBoxWorkspace />);
    materialTab().focus();
    fireEvent.keyDown(materialTab(), { key: "End" });
    await screen.findByTestId("experimental-stack-panel");
    expect(stackTab()).toHaveFocus();

    fireEvent.keyDown(stackTab(), { key: "ArrowRight" });
    await screen.findByTestId("material-capture-panel");
    expect(materialTab()).toHaveFocus();

    fireEvent.keyDown(materialTab(), { key: "ArrowLeft" });
    await screen.findByTestId("experimental-stack-panel");
    expect(stackTab()).toHaveFocus();

    fireEvent.keyDown(stackTab(), { key: "Home" });
    await screen.findByTestId("material-capture-panel");
    expect(materialTab()).toHaveFocus();
  });

  it("cancels a pending switch on unmount without changing the next workspace or its focus", async () => {
    const pending = pendingDisconnect();
    useLuminaBoxBackedGradientSerialStore.setState({
      status: "connected", disconnect: vi.fn(() => pending.promise),
    });
    const view = render(<LuminaBoxWorkspace />);
    fireEvent.keyDown(materialTab(), { key: "End" });
    expect(stackTab()).toBeDisabled();
    view.unmount();

    render(<LuminaBoxWorkspace />);
    materialTab().focus();
    await act(async () => {
      useLuminaBoxBackedGradientSerialStore.setState({ status: "disconnected" });
      pending.resolve();
    });
    expect(screen.getByTestId("material-capture-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("experimental-stack-panel")).not.toBeInTheDocument();
    expect(materialTab()).toHaveFocus();
    expect(stackTab()).not.toBeDisabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(localStorage.getItem(legacyStorageKey)).toBeNull();
  });
});
