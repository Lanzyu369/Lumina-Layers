import { describe, expect, it } from "vitest";
import firmwareWire from "./fixtures/lumina-box-firmware-v1.jsonl?raw";
import firmwareWireV2 from "./fixtures/lumina-box-firmware-v2.jsonl?raw";
import reliableFirmwareWire from "./fixtures/lumina-box-reliable-firmware.jsonl?raw";
import {
  LuminaBoxLineDecoder,
  parseLuminaBoxFrame,
  type LuminaBoxMeasurement,
} from "../api/luminaBoxSerial";
import { applyLuminaBoxMeasurement } from "../utils/luminaBoxCapture";

// Captured verbatim from the host C++ executable built from LuminaBox's
// firmware/tests/protocol_fixtures.cpp and firmware/main/measurement.cpp.
// Regenerate using `python <LuminaBox>/firmware/tests/run.py --fixtures <output>`
// and copy its JSONL output here; never regenerate this fixture with JS JSON.stringify.
// The checked-in fixture makes the consumer contract runnable without a sibling checkout.
const thicknesses = [0.08, 0.16, 0.24, 0.32, 0.4, 0.48, 0.56, 0.64, 0.72, 0.8, 1.6, 3];
const modes = ["reflect", "transmit", "auto"] as const;
const channels = ["x", "y", "z"] as const;

function parseFixture(wire = firmwareWire): LuminaBoxMeasurement[] {
  return wire.trimEnd().split(/\r?\n/).map((line) => {
    const frame = parseLuminaBoxFrame(line);
    expect(frame.kind).toBe("measurement");
    if (frame.kind !== "measurement") throw new Error("Firmware wire fixture was rejected");
    return frame.measurement;
  });
}

function emptyRows() {
  return thicknesses.map((thickness, index) => ({
    id: `row-${index}`,
    thickness: thickness.toFixed(2),
    reflectance: { x: "previous-r-x", y: "previous-r-y", z: "previous-r-z" },
    transmittance: { x: "previous-t-x", y: "previous-t-y", z: "previous-t-z" },
  })).reverse();
}

describe("Real Lumina Box firmware wire contract", () => {
  it("accepts the independent C++ reliable envelope and maps all 36 measurements without altering raw values", () => {
    const frames = reliableFirmwareWire.trimEnd().split(/\r?\n/).map(parseLuminaBoxFrame);
    expect(frames[0]).toMatchObject({ kind: "pong", captureId: "fixture-capture", pendingCount: 0 });
    const deliveries = frames.slice(1);
    expect(deliveries).toHaveLength(36);
    const ids = new Set<string>();
    for (const mode of modes) {
      let rows = emptyRows();
      for (const frame of deliveries) {
        expect(frame.kind).toBe("delivery");
        if (frame.kind !== "delivery") throw new Error("Reliable C++ wire fixture was rejected");
        expect(frame.captureId).toBe("fixture-capture");
        if (frame.measurement.mode !== mode) continue;
        ids.add(frame.measurement.measurement_id);
        const applied = applyLuminaBoxMeasurement(rows, frame.measurement);
        expect(applied.result).toBe("applied");
        rows = applied.samples;
      }
      for (const row of rows) {
        if (mode !== "transmit") expect(row.reflectance.x).toBe("103.25");
        else expect(row.reflectance.x).toBe("previous-r-x");
        if (mode !== "reflect") expect(row.transmittance.x).toBe("0");
        else expect(row.transmittance.x).toBe("previous-t-x");
      }
    }
    expect(ids.size).toBe(36);
    const decoder = new LuminaBoxLineDecoder();
    const bytes = new TextEncoder().encode(reliableFirmwareWire);
    const splitFrames = [];
    for (let offset = 0; offset < bytes.length; offset += 7) splitFrames.push(...decoder.push(bytes.slice(offset, offset + 7)));
    expect(splitFrames).toEqual(frames);
  });
  it("accepts the actual C++ serializer output for all three modes and twelve thicknesses", () => {
    expect(firmwareWire.endsWith("\n")).toBe(true);
    const measurements = parseFixture();
    expect(measurements).toHaveLength(36);
    expect(measurements.every((measurement) => measurement.version === 1)).toBe(true);
    expect(new Set(measurements.map((measurement) => measurement.measurement_id)).size).toBe(36);
    for (const mode of modes) {
      expect(measurements.filter((measurement) => measurement.mode === mode).map((measurement) => measurement.thickness_mm))
        .toEqual(thicknesses);
    }
  });

  it.each(modes)("fills the correct reversed table rows from actual %s frames with percentage precision", (mode) => {
    let rows = emptyRows();
    const measurements = parseFixture().filter((measurement) => measurement.mode === mode);
    for (const measurement of measurements) {
      const previous = rows;
      const applied = applyLuminaBoxMeasurement(rows, measurement);
      expect(applied.result).toBe("applied");
      rows = applied.samples;
      // Thickness matching must not depend on the firmware's increasing row order.
      expect(rows.map((row) => row.id)).toEqual(previous.map((row) => row.id));
      const changedRows = rows.filter((row, index) => row !== previous[index]);
      expect(changedRows).toHaveLength(1);
      expect(changedRows[0].thickness).toBe(measurement.thickness_mm.toFixed(2));
    }
    for (const row of rows) {
      const firstThickness = Number(row.thickness) === 0.08;
      const expectedReflection = firstThickness ? [0, 100, 31.234567] : [49, 48.25, 51.125];
      const expectedTransmission = firstThickness ? [0, 100, 42.234567] : [12.5, 10, 8.125];
      channels.forEach((channel, index) => {
        if (mode !== "transmit") {
          // A float32 input and six-place printf can differ by a few millionths
          // of a percentage point. There must be no factor-of-100 conversion.
          expect(Math.abs(Number(row.reflectance[channel]) - expectedReflection[index])).toBeLessThanOrEqual(0.000005);
        } else expect(row.reflectance[channel]).toBe(`previous-r-${channel}`);
        if (mode !== "reflect") {
          expect(Math.abs(Number(row.transmittance[channel]) - expectedTransmission[index])).toBeLessThanOrEqual(0.000005);
        } else expect(row.transmittance[channel]).toBe(`previous-t-${channel}`);
      });
    }
  });

  it("accepts the independent v2 C++ fixture without changing the archived v1 fixture", () => {
    const measurements = parseFixture(firmwareWireV2);
    expect(measurements).toHaveLength(36);
    expect(measurements.every((measurement) => measurement.version === 2)).toBe(true);
    expect(new Set(measurements.map((measurement) => measurement.measurement_id)).size).toBe(36);
    for (const mode of modes) {
      expect(measurements.filter((measurement) => measurement.mode === mode).map((measurement) => measurement.thickness_mm))
        .toEqual(thicknesses);
    }
  });

  it.each(modes)("retains real v2 %s raw reflection above 100 in the correct table rows", (mode) => {
    let rows = emptyRows();
    for (const measurement of parseFixture(firmwareWireV2).filter((frame) => frame.mode === mode)) {
      const previous = rows;
      const applied = applyLuminaBoxMeasurement(rows, measurement);
      expect(applied.result).toBe("applied");
      rows = applied.samples;
      const changedRows = rows.filter((row, index) => row !== previous[index]);
      expect(changedRows).toHaveLength(1);
      expect(changedRows[0].thickness).toBe(measurement.thickness_mm.toFixed(2));
    }
    for (const row of rows) {
      const thickness = Number(row.thickness);
      const expectedReflection = thickness === 0.08 ? [0, 100, 31.234567]
        : thickness === 0.16 ? [100.000008, 48.25, 51.125]
        : thickness === 3 ? [103.25, 120.5, 99.125] : [49, 48.25, 51.125];
      const expectedTransmission = thickness === 0.08 ? [0, 100, 42.234567] : [12.5, 10, 8.125];
      channels.forEach((channel, index) => {
        if (mode !== "transmit") {
          expect(Math.abs(Number(row.reflectance[channel]) - expectedReflection[index])).toBeLessThanOrEqual(0.000005);
        } else expect(row.reflectance[channel]).toBe(`previous-r-${channel}`);
        if (mode !== "reflect") {
          expect(Math.abs(Number(row.transmittance[channel]) - expectedTransmission[index])).toBeLessThanOrEqual(0.000005);
        } else expect(row.transmittance[channel]).toBe(`previous-t-${channel}`);
      });
      if (mode !== "transmit" && thickness === 0.16) expect(row.reflectance.x).toBe("100.000008");
    }
  });

  it.each([["v1", firmwareWire], ["v2", firmwareWireV2]])("decodes captured C++ %s JSONL across arbitrary USB read boundaries and ordinary log lines", (_version, wire) => {
    const decoder = new LuminaBoxLineDecoder();
    const bytes = new TextEncoder().encode(`boot ready\n${wire}sensor idle\n`);
    const fragments = [1, 7, 23, 2, 53];
    const received: LuminaBoxMeasurement[] = [];
    for (let offset = 0, fragment = 0; offset < bytes.length; fragment++) {
      const end = Math.min(bytes.length, offset + fragments[fragment % fragments.length]);
      for (const frame of decoder.push(bytes.slice(offset, end))) {
        expect(frame.kind).not.toBe("invalid");
        if (frame.kind === "measurement") received.push(frame.measurement);
      }
      offset = end;
    }
    expect(received).toEqual(parseFixture(wire));
  });
});
