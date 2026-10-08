import { describe, expect, it } from "vitest";
import firmwareWire from "./fixtures/lumina-box-firmware-v1.jsonl?raw";
import firmwareWireV2 from "./fixtures/lumina-box-firmware-v2.jsonl?raw";
import reliableFirmwareWire from "./fixtures/lumina-box-reliable-firmware.jsonl?raw";
import {
  LuminaBoxLineDecoder,
  parseLuminaBoxFrame,
  type LuminaBoxMeasurement,
} from "../api/luminaBoxSerial";

// Captured verbatim from the host C++ executable built from LuminaBox's
// firmware/tests/protocol_fixtures.cpp and firmware/main/measurement.cpp.
// Regenerate using `python <LuminaBox>/firmware/tests/run.py --fixtures <output>`
// and copy its JSONL output here; never regenerate this fixture with JS JSON.stringify.
// The checked-in fixture makes the consumer contract runnable without a sibling checkout.
const thicknesses = [0.08, 0.16, 0.24, 0.32, 0.4, 0.48, 0.56, 0.64, 0.72, 0.8, 1.6, 3];
const modes = ["reflect", "transmit", "auto"] as const;

function parseFixture(wire = firmwareWire): LuminaBoxMeasurement[] {
  return wire.trimEnd().split(/\r?\n/).map((line) => {
    const frame = parseLuminaBoxFrame(line);
    expect(frame.kind).toBe("measurement");
    if (frame.kind !== "measurement") throw new Error("Firmware wire fixture was rejected");
    return frame.measurement;
  });
}

describe("Real Lumina Box firmware wire contract", () => {
  it("accepts the independent C++ reliable envelope and all 36 measurements without altering raw values", () => {
    const frames = reliableFirmwareWire.trimEnd().split(/\r?\n/).map(parseLuminaBoxFrame);
    expect(frames[0]).toMatchObject({ kind: "pong", captureId: "fixture-capture", pendingCount: 0 });
    const deliveries = frames.slice(1);
    expect(deliveries).toHaveLength(36);
    const ids = new Set<string>();
    for (const frame of deliveries) {
      expect(frame.kind).toBe("delivery");
      if (frame.kind !== "delivery") throw new Error("Reliable C++ wire fixture was rejected");
      expect(frame.captureId).toBe("fixture-capture");
      ids.add(frame.measurement.measurement_id);
      if (frame.measurement.mode !== "transmit") expect(frame.measurement.reflectance_xyz[0]).toBe(103.25);
      if (frame.measurement.mode !== "reflect") expect(frame.measurement.transmittance_xyz[0]).toBe(0);
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
