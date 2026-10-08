import { beforeEach, describe, expect, it } from "vitest";
import { BACKED_GRADIENT_THICKNESSES } from "../api/luminaBoxBackedGradient";
import { LuminaBoxLineDecoder, parseLuminaBoxFrame } from "../api/luminaBoxSerial";
import { BACKED_GRADIENT_DRAFT_KEY, BACKED_GRADIENT_JOURNAL_KEY, backedGradientManualXYZ,
  restoreBackedGradientDraft, restoreBackedGradientJournal, routeBackedGradientMeasurement } from "../utils/luminaBoxBackedGradientCapture";
import wireV2 from "./fixtures/lumina-box-seven-thickness-v2.jsonl?raw";
import wireV3 from "./fixtures/lumina-box-seven-thickness-v3.jsonl?raw";

// Verbatim output from the firmware C++ protocol producer; retained independently of JS serialization.
const target = { material_symbol: "R", backing: "W", sample_role: "coated" } as const;
const metadata = { sampleName: "sample", notes: "raw fixture" };
beforeEach(() => localStorage.clear());

describe("seven-thickness firmware capture contract", () => {
  it.each([wireV2, wireV3])("routes every real reflection/auto frame while preserving raw device metadata", (wire) => {
    const frames = wire.trim().split(/\r?\n/).map(parseLuminaBoxFrame);
    const routedThicknesses: number[] = [];
    let rejected = 0;
    for (const frame of frames) {
      if (frame.kind !== "delivery" && frame.kind !== "measurement") continue;
      const raw = structuredClone(frame.measurement);
      const routed = routeBackedGradientMeasurement(target, "capture", frame.measurement, "2026-10-07T00:00:00Z", metadata);
      if (frame.measurement.mode === "transmit") { expect(routed.result).toBe("unsupported_mode"); rejected++; continue; }
      if (routed.result !== "ready") throw new Error("Producer reflection frame rejected");
      expect(routed.request.measurement).toEqual(raw);
      expect(routed.request.measurement?.thickness_schedule_id).toBe("backed_gradient_7/v1");
      expect(routed.request.measurement).not.toBe(frame.measurement);
      routedThicknesses.push(routed.request.overlay_mm);
    }
    expect(rejected).toBe(7);
    expect(routedThicknesses).toEqual([...BACKED_GRADIENT_THICKNESSES, ...BACKED_GRADIENT_THICKNESSES]);
  });

  it("accepts fragmented reliable frames and records bare zero without changing the positive device thickness", () => {
    const decoder = new LuminaBoxLineDecoder();
    const bytes = new TextEncoder().encode(wireV3);
    const frames = [];
    for (let index = 0; index < bytes.length; index += 7) frames.push(...decoder.push(bytes.slice(index, index + 7)));
    expect(frames).toEqual(wireV3.trim().split(/\r?\n/).map(parseLuminaBoxFrame));
    const frame = frames.find((item) => item.kind === "delivery" && item.measurement.thickness_mm === 1.28);
    if (frame?.kind !== "delivery") throw new Error("Missing 1.28 fixture");
    const routed = routeBackedGradientMeasurement({ material_symbol: "K", backing: "K", sample_role: "bare_backing" }, "bare", frame.measurement, "time", metadata);
    expect(routed).toMatchObject({ result: "ready", request: { overlay_mm: 0, measurement: { thickness_mm: 1.28, reflectance_xyz: [103.25, 48.25, 51.125] } } });
  });

  it("rejects mismatched schedules without clipping legitimate percentages", () => {
    const frame = parseLuminaBoxFrame(wireV2.split(/\r?\n/)[1]);
    if (frame.kind !== "measurement") throw new Error("Missing fixture");
    expect(routeBackedGradientMeasurement(target, "capture", { ...frame.measurement, thickness_mm: .8 }, "time", metadata)).toEqual({ result: "thickness_missing" });
    expect(backedGradientManualXYZ(["103.25", "0", "100.000008"])).toEqual([103.25, 0, 100.000008]);
    expect(backedGradientManualXYZ(["", "0", "1"])).toBeNull();
    expect(backedGradientManualXYZ(["-1", "0", "1"])).toBeNull();
  });

  it("restores only valid targets and pending frame ownership", () => {
    localStorage.setItem(BACKED_GRADIENT_DRAFT_KEY, JSON.stringify({ datasetId: "saved", target: { ...target, sample_role: "bare_backing" }, manualXYZ: ["1", "2", "3"] }));
    expect(restoreBackedGradientDraft()).toMatchObject({ datasetId: "saved", target, manualXYZ: ["1", "2", "3"] });
    const measurement = parseLuminaBoxFrame(wireV2.split(/\r?\n/)[0]);
    if (measurement.kind !== "measurement") throw new Error("Missing fixture");
    const routed = routeBackedGradientMeasurement(target, "scope", measurement.measurement, "time", metadata);
    if (routed.result !== "ready") throw new Error("Bad target");
    const entry = { key: "k", datasetId: "saved", measurementId: measurement.measurement.measurement_id, receivedAt: "time", outcome: "pending", request: routed.request };
    localStorage.setItem(BACKED_GRADIENT_JOURNAL_KEY, JSON.stringify({ scope: { captureId: "scope", datasetId: "saved", target }, entries: [entry, { ...entry, measurementId: "other" }] }));
    expect(restoreBackedGradientJournal()).toEqual({ scope: { captureId: "scope", datasetId: "saved", target }, entries: [entry] });
  });
});
