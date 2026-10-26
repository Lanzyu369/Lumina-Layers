import type { ConverterState } from "./types";

type DimensionState = Pick<
  ConverterState,
  "bedSizes" | "bed_label" | "aspectRatio" | "largeFormatEnabled"
>;

export function getPrinterBedDimensions(
  state: Pick<DimensionState, "bedSizes" | "bed_label">,
  printerId: string,
) {
  const bed = state.bedSizes.find((item) => item.printer_id === printerId)
    ?? state.bedSizes.find((item) => item.label === state.bed_label);
  // Use the existing default bed until the printer catalog has loaded.
  return { width: bed?.width_mm ?? 256, height: bed?.height_mm ?? 256 };
}

export function getTargetDimensionLimits(state: DimensionState, printerId: string) {
  const { width, height } = getPrinterBedDimensions(state, printerId);
  const ratio = state.aspectRatio;
  return {
    width: ratio && ratio > 0 ? Math.max(10, Math.min(width, height * ratio)) : width,
    height: ratio && ratio > 0 ? Math.max(10, Math.min(height, width / ratio)) : height,
  };
}

export function fitTargetDimensions(
  dimensions: Pick<ConverterState, "target_width_mm" | "target_height_mm">,
  state: DimensionState,
  printerId: string,
) {
  const { target_width_mm, target_height_mm } = dimensions;
  const limits = getPrinterBedDimensions(state, printerId);
  const scale = Math.min(
    1,
    limits.width / target_width_mm,
    limits.height / target_height_mm,
  );
  if (scale === 1) return { target_width_mm, target_height_mm };
  return {
    target_width_mm: Math.max(10, target_width_mm * scale),
    target_height_mm: Math.max(10, target_height_mm * scale),
  };
}
