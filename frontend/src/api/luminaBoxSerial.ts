import type { LuminaBoxPercentXYZ, LuminaBoxXYZ } from "./types";
import { getLuminaBoxDesktopSerialApi } from "./luminaBoxDesktopSerial";

/** Captured reflection percentages; wire v2 permits values above the current fit range.
 * 采集的反射百分数；v2 可保留超过当前拟合范围的原始读数。 */
export type LuminaBoxRawReflectanceXYZ = LuminaBoxXYZ;

export type LuminaBoxMeasurement = {
  protocol: "lumina-box";
  version: 1 | 2;
  type: "measurement";
  measurement_id: string;
  thickness_mm: number;
  thickness_schedule_id?: string;
} & (
  | { mode: "reflect"; reflectance_xyz: LuminaBoxRawReflectanceXYZ }
  | { mode: "transmit"; transmittance_xyz: LuminaBoxPercentXYZ }
  | { mode: "auto"; reflectance_xyz: LuminaBoxRawReflectanceXYZ; transmittance_xyz: LuminaBoxPercentXYZ }
);

export type LuminaBoxFrame =
  | { kind: "measurement"; measurement: LuminaBoxMeasurement }
  | { kind: "delivery"; captureId: string; measurement: LuminaBoxMeasurement }
  | { kind: "pong"; captureId: string; bootId: string; pendingCount: number; droppedCount: number;
      lastMeasurementId?: string; lastAckId?: string; txFailures?: number; rxStats?: Record<string, number> }
  | { kind: "invalid" }
  | { kind: "ignored" };

export type LuminaBoxCaptureResult = "applied" | "thickness_missing" | "thickness_ambiguous"
  | "storage_unavailable" | "invalid_recipe" | "unsupported_mode";

const isNonnegativeXYZ = (value: unknown): value is LuminaBoxXYZ =>
  Array.isArray(value) && value.length === 3 && value.every(
    (channel) => typeof channel === "number" && Number.isFinite(channel) && channel >= 0,
  );

const isPercentXYZ = (value: unknown): value is LuminaBoxPercentXYZ =>
  isNonnegativeXYZ(value) && value.every((channel) => channel <= 100);
const RECEIVER_COUNTER_FIELDS = ["rx_bytes", "rx_dropped_lines", "rx_overlong_lines", "rx_invalid_lines", "rx_expired_lines"] as const;

/** Validate complete JSONL frames without interpreting console output as measurements. */
export function parseLuminaBoxFrame(line: string): LuminaBoxFrame {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    return { kind: line.includes('"lumina-box"') ? "invalid" : "ignored" };
  }
  if (!value || typeof value !== "object") return { kind: "ignored" };
  const frame = value as Record<string, unknown>;
  if (frame.protocol !== "lumina-box") return { kind: "ignored" };
  if (frame.version === 3) {
    const token = (item: unknown, max = 64): item is string =>
      typeof item === "string" && item.length > 0 && item.length <= max && /^[A-Za-z0-9_-]+$/.test(item);
    if (!token(frame.capture_id)) return { kind: "invalid" };
    if (frame.type === "pong" && token(frame.boot_id, 80)
      && Number.isSafeInteger(frame.pending_count) && Number(frame.pending_count) >= 0 && Number(frame.pending_count) <= 32
      && Number.isSafeInteger(frame.dropped_count) && Number(frame.dropped_count) >= 0) {
      const receiverStats: Record<string, number> = {};
      for (const field of RECEIVER_COUNTER_FIELDS) {
        if (frame[field] === undefined) continue;
        if (!Number.isSafeInteger(frame[field]) || Number(frame[field]) < 0) return { kind: "invalid" };
        receiverStats[field] = Number(frame[field]);
      }
      return { kind: "pong", captureId: frame.capture_id, bootId: frame.boot_id,
        pendingCount: Number(frame.pending_count), droppedCount: Number(frame.dropped_count),
        ...(typeof frame.last_measurement_id === "string" && frame.last_measurement_id.length <= 128
          ? { lastMeasurementId: frame.last_measurement_id } : {}),
        ...(typeof frame.last_ack_id === "string" && frame.last_ack_id.length <= 128 ? { lastAckId: frame.last_ack_id } : {}),
        ...(Number.isSafeInteger(frame.tx_failures) && Number(frame.tx_failures) >= 0 ? { txFailures: Number(frame.tx_failures) } : {}),
        ...(Object.keys(receiverStats).length ? { rxStats: receiverStats } : {}),
      };
    }
    if (frame.type === "delivery" && frame.measurement && typeof frame.measurement === "object"
      && (frame.measurement as Record<string, unknown>).type === "measurement") {
      const nested = parseLuminaBoxFrame(JSON.stringify(frame.measurement));
      if (nested.kind === "measurement") return { kind: "delivery", captureId: frame.capture_id, measurement: nested.measurement };
    }
    return { kind: "invalid" };
  }
  if ((frame.version !== 1 && frame.version !== 2) || frame.type !== "measurement"
    || typeof frame.measurement_id !== "string" || !frame.measurement_id.trim()
    || frame.measurement_id.length > 128
    || typeof frame.thickness_mm !== "number" || !Number.isFinite(frame.thickness_mm)
    || frame.thickness_mm <= 0
    || typeof frame.mode !== "string" || !["reflect", "transmit", "auto"].includes(frame.mode)) {
    return { kind: "invalid" };
  }
  const needsReflection = frame.mode === "reflect" || frame.mode === "auto";
  const needsTransmission = frame.mode === "transmit" || frame.mode === "auto";
  const validReflection = frame.version === 2 ? isNonnegativeXYZ : isPercentXYZ;
  if ((needsReflection || frame.reflectance_xyz !== undefined) && !validReflection(frame.reflectance_xyz)) {
    return { kind: "invalid" };
  }
  if ((needsTransmission || frame.transmittance_xyz !== undefined) && !isPercentXYZ(frame.transmittance_xyz)) {
    return { kind: "invalid" };
  }
  return { kind: "measurement", measurement: frame as LuminaBoxMeasurement };
}

const MAX_LINE_LENGTH = 4096;

/** Decode arbitrarily split UTF-8 chunks and bound memory even for unterminated logs. */
export class LuminaBoxLineDecoder {
  private readonly decoder = new TextDecoder();
  private pending = "";
  private droppingLine = false;

  push(chunk: Uint8Array): LuminaBoxFrame[] {
    const text = this.decoder.decode(chunk, { stream: true });
    const frames: LuminaBoxFrame[] = [];
    let start = 0;
    while (start < text.length) {
      const newline = text.indexOf("\n", start);
      const end = newline < 0 ? text.length : newline;
      if (!this.droppingLine) {
        if (this.pending.length + end - start > MAX_LINE_LENGTH) {
          this.pending = "";
          this.droppingLine = true;
          frames.push({ kind: "invalid" });
        } else {
          this.pending += text.slice(start, end);
        }
      }
      if (newline < 0) break;
      if (!this.droppingLine && this.pending.trim()) {
        frames.push(parseLuminaBoxFrame(this.pending.trim()));
      }
      this.pending = "";
      this.droppingLine = false;
      start = newline + 1;
    }
    return frames;
  }
}

// Keep the supported Web Serial surface explicit without a global DOM augmentation.
export interface LuminaBoxSerialPort {
  readonly readable: ReadableStream<Uint8Array> | null;
  readonly writable?: WritableStream<Uint8Array> | null;
  open(options: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
}

export interface LuminaBoxSerialApi {
  requestPort(): Promise<LuminaBoxSerialPort>;
}

export function getLuminaBoxSerialApi(): LuminaBoxSerialApi | null {
  const desktop = getLuminaBoxDesktopSerialApi();
  if (desktop) return desktop;
  if (typeof navigator === "undefined" || globalThis.isSecureContext === false) return null;
  return (navigator as Navigator & { serial?: LuminaBoxSerialApi }).serial ?? null;
}
