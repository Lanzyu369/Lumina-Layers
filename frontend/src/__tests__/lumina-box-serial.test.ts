import { describe, expect, it } from "vitest";
import { LuminaBoxLineDecoder, parseLuminaBoxFrame, type LuminaBoxMeasurement } from "../api/luminaBoxSerial";
import { applyLuminaBoxMeasurement } from "../utils/luminaBoxCapture";

const measurement: LuminaBoxMeasurement = {
  protocol: "lumina-box", version: 1, type: "measurement", measurement_id: "boot-1-1",
  thickness_mm: 0.16, mode: "auto", reflectance_xyz: [0, 21.2, 100], transmittance_xyz: [31.2, 42, 37],
};

describe("Lumina Box wired protocol", () => {
  it("accepts finite percentage values including boundaries without rescaling", () => {
    expect(parseLuminaBoxFrame(JSON.stringify(measurement))).toEqual({ kind: "measurement", measurement });
    expect(parseLuminaBoxFrame(JSON.stringify({ ...measurement, transmittance_xyz: [0, 0, 0] })).kind).toBe("measurement");
  });

  it.each([
    { version: 3 }, { measurement_id: "" }, { measurement_id: " ", }, { thickness_mm: "0.16" },
    { thickness_mm: 0 }, { thickness_mm: -1 }, { thickness_mm: null }, { mode: "reflection" }, { mode: ["auto"] },
    { reflectance_xyz: [1, 2] }, { transmittance_xyz: [1, 2, 3, 4] },
    { reflectance_xyz: [-1, 2, 3] }, { transmittance_xyz: [101, 2, 3] },
    { reflectance_xyz: [null, 2, 3] }, { reflectance_xyz: ["1", 2, 3] },
    { reflectance_xyz: undefined }, { transmittance_xyz: undefined },
  ])("rejects an invalid frame: %j", (patch) => {
    expect(parseLuminaBoxFrame(JSON.stringify({ ...measurement, ...patch })).kind).toBe("invalid");
  });

  it.each(["reflect", "auto"] as const)("accepts wire v2 %s reflection above 100 without clipping or rescaling", (mode) => {
    const extended = { ...measurement, version: 2, mode, reflectance_xyz: [100.000008, 103.25, 120.5] };
    expect(parseLuminaBoxFrame(JSON.stringify(extended))).toEqual({ kind: "measurement", measurement: extended });
    expect(parseLuminaBoxFrame(JSON.stringify({ ...extended, version: 1 })).kind).toBe("invalid");
  });

  it.each([
    { reflectance_xyz: [-0.01, 103, 120] },
    { reflectance_xyz: [Number.NaN, 103, 120] },
    { reflectance_xyz: [Number.POSITIVE_INFINITY, 103, 120] },
    { reflectance_xyz: ["103", 104, 105] },
    { reflectance_xyz: [103, 104] },
    { transmittance_xyz: [100.000008, 10, 20] },
    { transmittance_xyz: [-1, 10, 20] },
    { transmittance_xyz: [Number.NaN, 10, 20] },
  ])("keeps invalid XYZ and transmission limits in wire v2: %j", (patch) => {
    expect(parseLuminaBoxFrame(JSON.stringify({ ...measurement, version: 2, ...patch })).kind).toBe("invalid");
  });

  it("retains measured zero transmission in wire v2", () => {
    const extended = { ...measurement, version: 2, reflectance_xyz: [103.25, 120.5, 99.125], transmittance_xyz: [0, 0, 0] };
    expect(parseLuminaBoxFrame(JSON.stringify(extended))).toEqual({ kind: "measurement", measurement: extended });
  });

  it("retains large finite wire v2 reflection values without an invented upper bound", () => {
    const extended = { ...measurement, version: 2, reflectance_xyz: [Number.MAX_VALUE, 103.25, 120.5] };
    expect(parseLuminaBoxFrame(JSON.stringify(extended))).toEqual({ kind: "measurement", measurement: extended });
  });

  it("accepts each single modality but does not accept an invalid extraneous modality", () => {
    const { transmittance_xyz: _transmission, ...reflection } = measurement;
    expect(parseLuminaBoxFrame(JSON.stringify({ ...reflection, mode: "reflect" })).kind).toBe("measurement");
    expect(parseLuminaBoxFrame(JSON.stringify({ ...reflection, mode: "reflect", transmittance_xyz: [null, 0, 0] })).kind).toBe("invalid");
    const { reflectance_xyz: _reflection, ...transmission } = measurement;
    expect(parseLuminaBoxFrame(JSON.stringify({ ...transmission, mode: "transmit" })).kind).toBe("measurement");
  });

  it("decodes byte-split frames, CRLF, multiple packets and mixed UTF-8 logs", () => {
    const decoder = new LuminaBoxLineDecoder();
    const source = new TextEncoder().encode(`启动完成\n${JSON.stringify(measurement)}\r\nconsole log\n${JSON.stringify({ ...measurement, measurement_id: "boot-1-2" })}\n`);
    const frames = Array.from(source).flatMap((byte) => decoder.push(Uint8Array.of(byte)));
    expect(frames.filter((frame) => frame.kind === "measurement")).toHaveLength(2);
    expect(frames.filter((frame) => frame.kind === "invalid")).toHaveLength(0);
  });

  it("drops an oversized line and resumes with the following complete frame", () => {
    const decoder = new LuminaBoxLineDecoder();
    expect(decoder.push(new TextEncoder().encode("x".repeat(9000)))).toEqual([{ kind: "invalid" }]);
    const frames = decoder.push(new TextEncoder().encode(`discarded\n${JSON.stringify(measurement)}\n`));
    expect(frames).toEqual([{ kind: "measurement", measurement }]);
  });

  it("ignores unrelated logs and refuses malformed or truncated frames", () => {
    expect(parseLuminaBoxFrame('{"event":"sensor_ready"}')).toEqual({ kind: "ignored" });
    expect(parseLuminaBoxFrame('{"protocol":"lumina-box",bad}')).toEqual({ kind: "invalid" });
    const decoder = new LuminaBoxLineDecoder();
    expect(decoder.push(new TextEncoder().encode(JSON.stringify(measurement)))).toEqual([]);
  });
});

describe("Lumina Box measurement placement", () => {
  const rows = ["3.00", "0.160000", "0.08"].map((thickness, index) => ({
    id: `row-${index}`, thickness,
    reflectance: { x: "1", y: "2", z: "3" },
    transmittance: { x: "4", y: "5", z: "6" },
  }));

  it("fills all six fields in the matching thickness after rows are reordered", () => {
    const result = applyLuminaBoxMeasurement(rows, measurement);
    expect(result.result).toBe("applied");
    expect(result.samples[0]).toBe(rows[0]);
    expect(result.samples[2]).toBe(rows[2]);
    expect(result.samples[1]).toEqual({ id: "row-1", thickness: "0.160000", reflectance: { x: "0", y: "21.2", z: "100" }, transmittance: { x: "31.2", y: "42", z: "37" } });
    expect(rows[1].reflectance.x).toBe("1");
  });

  it.each(["reflect", "transmit"] as const)("preserves the other modality in %s mode", (mode) => {
    const result = applyLuminaBoxMeasurement(rows, { ...measurement, mode });
    const unchanged = mode === "reflect" ? "transmittance" : "reflectance";
    expect(result.samples[1][unchanged]).toBe(rows[1][unchanged]);
  });

  it("refuses missing or ambiguous thickness without changing data", () => {
    expect(applyLuminaBoxMeasurement(rows, { ...measurement, thickness_mm: 0.24 })).toEqual({ result: "thickness_missing", samples: rows });
    const duplicateRows = [...rows, { ...rows[1], id: "duplicate", thickness: "0.16" }];
    expect(applyLuminaBoxMeasurement(duplicateRows, measurement)).toEqual({ result: "thickness_ambiguous", samples: duplicateRows });
  });
});
