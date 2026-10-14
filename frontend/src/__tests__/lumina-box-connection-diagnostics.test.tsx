import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LuminaBoxConnectionDiagnostics from "../components/LuminaBoxConnectionDiagnostics";
import { translations } from "../i18n/translations";
import type { LuminaBoxSerialDiagnosticSnapshot } from "../stores/luminaBoxSerialStore";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

const snapshot: LuminaBoxSerialDiagnosticSnapshot = {
  status: "disconnected", mode: "unknown", captureId: "capture-1", receivedBytes: 512,
  receivedCount: 1, pendingCount: 0, lastHeartbeatAt: 1000, issue: "operation_timeout",
  lastError: "serial_operation_timeout", trace: [{ at: 1200, event: "command_failed", detail: "ack" }],
};

beforeEach(() => {
  useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "zh" });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("connection diagnostics", () => {
  it("shows a copyable snapshot without requiring a download or exposing measurement values", () => {
    const save = vi.fn();
    vi.stubGlobal("electronAPI", { saveConnectionDiagnostics: save });
    const state = { ...snapshot, lastMeasurement: { reflectance_xyz: [44.9, 50.7, 21.4] } };
    render(<LuminaBoxConnectionDiagnostics snapshot={state} />);
    fireEvent.click(screen.getByTestId("lumina-box-diagnostics-view"));
    const text = (screen.getByTestId("lumina-box-diagnostics-text") as HTMLTextAreaElement).value;
    expect(JSON.parse(text)).toMatchObject({ version: 1, lastError: "serial_operation_timeout", trace: snapshot.trace });
    expect(text).not.toContain("reflectance_xyz");
    expect(save).not.toHaveBeenCalled();
  });

  it("saves the exact snapshot through the desktop bridge and shows a result", async () => {
    const save = vi.fn().mockResolvedValue({ status: "saved" });
    vi.stubGlobal("electronAPI", { saveConnectionDiagnostics: save });
    render(<LuminaBoxConnectionDiagnostics snapshot={snapshot} />);
    fireEvent.click(screen.getByTestId("lumina-box-diagnostics-save"));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(JSON.parse(save.mock.calls[0][0])).toMatchObject({ version: 1, lastError: snapshot.lastError });
    expect(await screen.findByText(translations.lumina_box_serial_diagnostics_saved.zh)).toBeInTheDocument();
  });

  it("keeps diagnostics visible with a restart instruction when the running desktop lacks the bridge", async () => {
    vi.stubGlobal("electronAPI", {});
    render(<LuminaBoxConnectionDiagnostics snapshot={snapshot} />);
    fireEvent.click(screen.getByTestId("lumina-box-diagnostics-save"));
    expect(await screen.findByText(translations.lumina_box_serial_diagnostics_restart.zh)).toBeInTheDocument();
    expect((screen.getByTestId("lumina-box-diagnostics-text") as HTMLTextAreaElement).value).toContain(snapshot.lastError);
  });
});
