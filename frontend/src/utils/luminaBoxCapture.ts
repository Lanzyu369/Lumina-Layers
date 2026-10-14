import type { LuminaBoxCaptureResult, LuminaBoxMeasurement } from "../api/luminaBoxSerial";
import type { LuminaBoxXYZ } from "../api/types";

interface MeasurementRow {
  thickness: string;
  reflectance: { x: string; y: string; z: string };
  transmittance: { x: string; y: string; z: string };
}

const toInputs = ([x, y, z]: LuminaBoxXYZ) => ({ x: String(x), y: String(y), z: String(z) });

/** Match actual thickness, never row position; preserve the other modality in single mode. */
export function applyLuminaBoxMeasurement<Row extends MeasurementRow>(
  rows: Row[],
  measurement: LuminaBoxMeasurement,
): { result: LuminaBoxCaptureResult; samples: Row[] } {
  const matches = rows.filter((row) => {
    const thickness = Number(row.thickness.trim());
    return Number.isFinite(thickness) && thickness > 0
      && thickness.toFixed(6) === measurement.thickness_mm.toFixed(6);
  });
  if (matches.length !== 1) {
    return { result: matches.length ? "thickness_ambiguous" : "thickness_missing", samples: rows };
  }
  return {
    result: "applied",
    samples: rows.map((row) => row !== matches[0] ? row : {
      ...row,
      ...(measurement.mode !== "transmit" ? { reflectance: toInputs(measurement.reflectance_xyz) } : {}),
      ...(measurement.mode !== "reflect" ? { transmittance: toInputs(measurement.transmittance_xyz) } : {}),
    }),
  };
}
