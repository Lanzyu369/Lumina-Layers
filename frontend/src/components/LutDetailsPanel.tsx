import "./LutDetailsPanel.css";
import HelpDot from "./ui/HelpDot";
import CloseButton from "./ui/CloseButton";
import DisclosureSummary from "./ui/DisclosureSummary";
import { memo, startTransition, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useI18n } from "../i18n/context";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import Dropdown from "./ui/Dropdown";
import { StatusBanner, cardPadClass, resolvePanelSurfaceClass, wellClass, wellPadClass } from "./ui/panelPrimitives";
import { useLutDetailsStore, filterLutDetailsCatalog } from "../stores/lutDetailsStore";
import {
  LutScatterChart,
  formatNumberRange,
} from "./lutDetails/LutScatterChart";
import LabPointCloud3D from "./lutDetails/LabPointCloud3D";
import type { LutDetailsCatalogItem, LutDetailsResponse } from "../api/types";
import type { LutScatterPoint } from "./lutDetails/LutScatterChart";
import { buildReferenceGridImageHref, buildReferenceImageHref } from "./lutDetails/referenceImage";
import type { ReferencePoint } from "./lutDetails/referenceImage";
import { maxOklchChromaForHueLightness, oklchToHexClamped, rgbToOklch } from "./lutDetails/oklch";

function replaceTokens(template: string, values: Record<string, string | number>): string {
  let result = template;
  for (const [key, value] of Object.entries(values)) {
    result = result.replace(`{${key}}`, String(value));
  }
  return result;
}

function appendSummaryPart(summary: string, nextPart: string | null): string {
  if (!nextPart) {
    return summary;
  }
  return `${summary} | ${nextPart}`;
}

function localizeCapability(capability: string, t: (key: string) => string): string {
  switch (capability) {
    case "legacy_lookup":
      return t("lut_info_capability_legacy_lookup");
    case "predictive_match":
      return t("lut_info_capability_predictive_match");
    case "predictive_model":
      return t("lut_info_capability_predictive_model");
    case "dynamic_layer_height":
      return t("lut_info_capability_dynamic_layer_height");
    case "dynamic_layer_count":
      return t("lut_info_capability_dynamic_layer_count");
    case "custom_recipe":
      return t("lut_info_capability_custom_recipe");
    case "native_reference":
      return t("lut_info_capability_native_reference");
    default:
      return capability;
  }
}

function formatMm(value: number, t: (key: string) => string): string {
  return `${value.toFixed(2)} ${t("common_unit_mm")}`;
}

function formatModeItem(mode: { color_layers: number; layer_height_mm: number }, t: (key: string) => string): string {
  return replaceTokens(t("lut_details_supported_mode_item"), {
    layers: mode.color_layers,
    height: mode.layer_height_mm.toFixed(2),
  });
}

function valueOrDash(value: string | number | null | undefined, t: (key: string) => string): string {
  if (value === null || value === undefined || value === "") {
    return t("common_not_available");
  }
  return String(value);
}

function renderErrorMessage(error: string, t: (key: string) => string): string {
  if (error.startsWith("lut_details_") || error.startsWith("common_")) {
    return t(error);
  }
  return error;
}

function InfoField({
  label,
  value,
  fullWidth = false,
}: {
  label: string;
  value: string;
  fullWidth?: boolean;
}) {
  return (
    <div className={`lut-details-field min-w-0 ${fullWidth ? "col-span-full" : ""}`}>
      <dt className="text-xs text-slate-500 dark:text-slate-400">
        {label}
      </dt>
      <dd className="mt-1 break-words [overflow-wrap:anywhere] text-sm leading-5 text-slate-800 dark:text-slate-100">
        {value}
      </dd>
    </div>
  );
}

function ChipList({
  items,
  emptyLabel,
}: {
  items: string[];
  emptyLabel: string;
}) {
  if (items.length === 0) {
    return <span className="text-sm text-slate-500 dark:text-slate-400">{emptyLabel}</span>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <span
          key={item}
          className="rounded-full border border-blue-200/80 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 dark:border-blue-400/30 dark:bg-blue-500/10 dark:text-blue-200"
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function renderPaletteRow(item: NonNullable<LutDetailsResponse["palette"]>[number], index: number, t: (key: string) => string) {
  return (
    <tr key={`${item.color}-${index}`} className="border-t border-slate-200/70 dark:border-slate-800/70">
      <td className="px-3 py-3">
        <div className="flex items-center gap-3">
          <span
            className="h-6 w-6 shrink-0 rounded-full border border-slate-200/80 dark:border-slate-700/80"
            style={{ backgroundColor: item.hex_color ?? "transparent" }}
          />
          <div>
            <div className="text-sm font-medium text-slate-900 dark:text-slate-50">{item.color}</div>
            <div className="text-xs text-slate-500 dark:text-slate-400">{item.color_name ?? t("lut_details_palette_unknown")}</div>
          </div>
        </div>
      </td>
      <td className="px-3 py-3 text-sm text-slate-700 dark:text-slate-200">{item.material}</td>
      <td className="px-3 py-3 text-sm font-mono text-slate-700 dark:text-slate-200">{item.hex_color ?? t("common_not_available")}</td>
    </tr>
  );
}

function srgbToLinear(channel: number): number {
  const normalized = channel / 255;
  if (normalized <= 0.04045) {
    return normalized / 12.92;
  }
  return ((normalized + 0.055) / 1.055) ** 2.4;
}

function rgbToLab(r: number, g: number, b: number): { l: number; a: number; b2: number } {
  const lr = srgbToLinear(r);
  const lg = srgbToLinear(g);
  const lb = srgbToLinear(b);

  const x = (lr * 0.4124564 + lg * 0.3575761 + lb * 0.1804375) / 0.95047;
  const y = (lr * 0.2126729 + lg * 0.7151522 + lb * 0.072175) / 1.0;
  const z = (lr * 0.0193339 + lg * 0.119192 + lb * 0.9503041) / 1.08883;

  const f = (value: number) =>
    value > 0.008856 ? Math.cbrt(value) : (7.787 * value) + (16 / 116);

  const fx = f(x);
  const fy = f(y);
  const fz = f(z);

  return {
    l: (116 * fy) - 16,
    a: 500 * (fx - fy),
    b2: 200 * (fy - fz),
  };
}

function projectRgb(r: number, g: number, b: number) {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  return {
    x: (rn - bn) * 0.8660254,
    y: gn - ((rn + bn) * 0.5),
  };
}

function findHuePeak(
  hue: number,
  chromaUpperBound: number,
): { lightness: number; maxChroma: number } {
  let left = 0;
  let right = 1;
  for (let iteration = 0; iteration < 11; iteration += 1) {
    const leftThird = left + ((right - left) / 3);
    const rightThird = right - ((right - left) / 3);
    const leftChroma = maxOklchChromaForHueLightness(hue, leftThird, chromaUpperBound);
    const rightChroma = maxOklchChromaForHueLightness(hue, rightThird, chromaUpperBound);
    if (leftChroma < rightChroma) {
      left = leftThird;
    } else {
      right = rightThird;
    }
  }
  const lightness = (left + right) / 2;
  return {
    lightness: lightness * 100,
    maxChroma: maxOklchChromaForHueLightness(hue, lightness, chromaUpperBound),
  };
}

function findHueLightnessBounds(
  hue: number,
  chromaUpperBound: number,
  chromaThreshold: number,
): { minLightness: number; maxLightness: number } {
  const peak = findHuePeak(hue, chromaUpperBound);
  if (peak.maxChroma <= chromaThreshold) {
    return { minLightness: 0, maxLightness: 100 };
  }

  let lowMin = 0;
  let highMin = peak.lightness / 100;
  for (let iteration = 0; iteration < 11; iteration += 1) {
    const mid = (lowMin + highMin) / 2;
    const chroma = maxOklchChromaForHueLightness(hue, mid, chromaUpperBound);
    if (chroma >= chromaThreshold) {
      highMin = mid;
    } else {
      lowMin = mid;
    }
  }

  let lowMax = peak.lightness / 100;
  let highMax = 1;
  for (let iteration = 0; iteration < 11; iteration += 1) {
    const mid = (lowMax + highMax) / 2;
    const chroma = maxOklchChromaForHueLightness(hue, mid, chromaUpperBound);
    if (chroma >= chromaThreshold) {
      lowMax = mid;
    } else {
      highMax = mid;
    }
  }

  return {
    minLightness: highMin * 100,
    maxLightness: lowMax * 100,
  };
}

export function buildHuePeakProfile(
  sampleCount: number,
  chromaUpperBound: number,
): Array<{ hue: number; lightness: number; maxChroma: number }> {
  const rawProfile = Array.from({ length: sampleCount }, (_, index) => {
    const hue = (index / (sampleCount - 1)) * 360;
    const peak = findHuePeak(hue, chromaUpperBound);
    return {
      hue,
      lightness: peak.lightness,
      maxChroma: peak.maxChroma,
    };
  });
  const windowRadius = 8;
  return rawProfile.map((entry, index) => {
    let lightnessSum = 0;
    let chromaSum = 0;
    let count = 0;
    for (let offset = -windowRadius; offset <= windowRadius; offset += 1) {
      const sampleIndex = (index + offset + rawProfile.length) % rawProfile.length;
      const sample = rawProfile[sampleIndex];
      lightnessSum += sample.lightness;
      chromaSum += sample.maxChroma;
      count += 1;
    }
    return {
      hue: entry.hue,
      lightness: lightnessSum / count,
      maxChroma: chromaSum / count,
    };
  });
}

function buildHueLightnessBoundsProfile(
  sampleCount: number,
  chromaUpperBound: number,
  chromaThreshold: number,
): Array<{ hue: number; minLightness: number; maxLightness: number }> {
  const rawProfile = Array.from({ length: sampleCount }, (_, index) => {
    const hue = (index / (sampleCount - 1)) * 360;
    const bounds = findHueLightnessBounds(hue, chromaUpperBound, chromaThreshold);
    return {
      hue,
      minLightness: bounds.minLightness,
      maxLightness: bounds.maxLightness,
    };
  });

  const windowRadius = 8;
  return rawProfile.map((entry, index) => {
    let minSum = 0;
    let maxSum = 0;
    let count = 0;
    for (let offset = -windowRadius; offset <= windowRadius; offset += 1) {
      const sampleIndex = (index + offset + rawProfile.length) % rawProfile.length;
      const sample = rawProfile[sampleIndex];
      minSum += sample.minLightness;
      maxSum += sample.maxLightness;
      count += 1;
    }
    return {
      hue: entry.hue,
      minLightness: minSum / count,
      maxLightness: maxSum / count,
    };
  });
}

function getInterpolatedHueProfile(
  profile: Array<{ hue: number; lightness: number; maxChroma: number }>,
  hue: number,
): { lightness: number; maxChroma: number } {
  const normalizedHue = ((hue % 360) + 360) % 360;
  const profileMaxIndex = profile.length - 1;
  const scaledIndex = (normalizedHue / 360) * profileMaxIndex;
  const leftIndex = Math.floor(scaledIndex);
  const rightIndex = Math.min(profileMaxIndex, leftIndex + 1);
  const mix = scaledIndex - leftIndex;
  const left = profile[leftIndex];
  const right = profile[rightIndex];
  return {
    lightness: left.lightness + ((right.lightness - left.lightness) * mix),
    maxChroma: left.maxChroma + ((right.maxChroma - left.maxChroma) * mix),
  };
}

function getInterpolatedHueLightnessBounds(
  profile: Array<{ hue: number; minLightness: number; maxLightness: number }>,
  hue: number,
): { minLightness: number; maxLightness: number } {
  const normalizedHue = ((hue % 360) + 360) % 360;
  const profileMaxIndex = profile.length - 1;
  const scaledIndex = (normalizedHue / 360) * profileMaxIndex;
  const leftIndex = Math.floor(scaledIndex);
  const rightIndex = Math.min(profileMaxIndex, leftIndex + 1);
  const mix = scaledIndex - leftIndex;
  const left = profile[leftIndex];
  const right = profile[rightIndex];
  return {
    minLightness: left.minLightness + ((right.minLightness - left.minLightness) * mix),
    maxLightness: left.maxLightness + ((right.maxLightness - left.maxLightness) * mix),
  };
}

function getRelativeHueLightness(
  hue: number,
  lightness: number,
  profile: Array<{ hue: number; minLightness: number; maxLightness: number }>,
): number {
  const bounds = getInterpolatedHueLightnessBounds(profile, hue);
  const span = Math.max(bounds.maxLightness - bounds.minLightness, 1);
  return Math.max(0, Math.min(100, ((lightness - bounds.minLightness) / span) * 100));
}

function getRelativeHueChroma(
  hue: number,
  chroma: number,
  profile: Array<{ hue: number; lightness: number; maxChroma: number }>,
): number {
  const hueProfile = getInterpolatedHueProfile(profile, hue);
  return Math.max(0, Math.min(100, (chroma / Math.max(hueProfile.maxChroma, 0.0001)) * 100));
}

function getHueChromaReferenceColor(
  hue: number,
  relativeSaturation: number,
  profile: Array<{ hue: number; lightness: number; maxChroma: number }>,
): string {
  const hueProfile = getInterpolatedHueProfile(profile, hue);
  return oklchToHexClamped({
    l: hueProfile.lightness / 100,
    c: (relativeSaturation / 100) * hueProfile.maxChroma,
    h: hue,
  });
}

function formatRange(values: number[]): string {
  if (values.length === 0) {
    return "0.0 – 0.0";
  }
  return formatNumberRange(Math.min(...values), Math.max(...values));
}

function formatCircularHueRange(values: number[]): string {
  if (values.length === 0) {
    return "0.0 – 0.0";
  }

  const normalized = values
    .map((value) => ((value % 360) + 360) % 360)
    .sort((left, right) => left - right);
  let largestGapIndex = 0;
  let largestGap = -1;

  for (let index = 0; index < normalized.length; index += 1) {
    const current = normalized[index];
    const next = normalized[(index + 1) % normalized.length] ?? normalized[0] ?? current;
    const gap = index === normalized.length - 1 ? (next + 360) - current : next - current;
    if (gap > largestGap) {
      largestGap = gap;
      largestGapIndex = index;
    }
  }

  const start = normalized[(largestGapIndex + 1) % normalized.length] ?? normalized[0] ?? 0;
  const end = normalized[largestGapIndex] ?? start;
  return `${start.toFixed(1)} – ${end.toFixed(1)}`;
}

function buildReferenceSteps(): number[] {
  return Array.from({ length: 17 }, (_, index) => Math.round((index / 16) * 255));
}

function buildLabReferencePoints(): ReferencePoint[] {
  const points: ReferencePoint[] = [];
  for (const r of buildReferenceSteps()) {
    for (const g of buildReferenceSteps()) {
      for (const b of buildReferenceSteps()) {
        const lab = rgbToLab(r, g, b);
        points.push({
          x: lab.a,
          y: lab.b2,
          hex_color: `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`,
          rgb: [r, g, b],
        });
      }
    }
  }
  return points;
}

function buildRgbReferencePoints(): ReferencePoint[] {
  const points: ReferencePoint[] = [];
  for (const r of buildReferenceSteps()) {
    for (const g of buildReferenceSteps()) {
      for (const b of buildReferenceSteps()) {
        const projected = projectRgb(r, g, b);
        points.push({
          x: projected.x,
          y: projected.y,
          hex_color: `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`,
          rgb: [r, g, b],
        });
      }
    }
  }
  return points;
}

export function buildHueLightnessPoints(points: LutDetailsResponse["lab_points"]): LutScatterPoint[] {
  return points.flatMap((point) => {
    const lch = rgbToOklch(point.rgb[0], point.rgb[1], point.rgb[2]);
    if (lch.c < HUE_DEFINED_CHROMA_THRESHOLD) {
      return [];
    }
    const relativeLightness = getRelativeHueLightness(lch.h, lch.l * 100, getHueLightnessBoundsProfile());
    return [{
      x: lch.h,
      y: relativeLightness,
      hex_color: point.hex_color,
      label: point.label,
    }];
  });
}

export function buildHueChromaPoints(points: LutDetailsResponse["lab_points"]): LutScatterPoint[] {
  const profile = getHueChromaProfile();
  return points.flatMap((point) => {
    const lch = rgbToOklch(point.rgb[0], point.rgb[1], point.rgb[2]);
    if (lch.c < HUE_DEFINED_CHROMA_THRESHOLD) {
      return [];
    }
    const relativeSaturation = getRelativeHueChroma(lch.h, lch.c, profile);
    return [{
      x: lch.h,
      y: relativeSaturation,
      hex_color: getHueChromaReferenceColor(lch.h, relativeSaturation, profile),
      label: point.label,
    }];
  });
}

const LAB_REFERENCE_BOUNDS = { minX: -120, maxX: 120, minY: -120, maxY: 120 };
const RGB_REFERENCE_BOUNDS = { minX: -0.9, maxX: 0.9, minY: -1, maxY: 1 };
const HUE_LIGHTNESS_REFERENCE_BOUNDS = { minX: 0, maxX: 360, minY: 0, maxY: 100 };
const HUE_CHROMA_REFERENCE_BOUNDS = {
  minX: 0,
  maxX: 360,
  minY: 0,
  maxY: 100,
};
const HUE_GRID_COLUMNS = 120;
const HUE_GRID_ROWS = 120;
const HUE_GRID_BLEED = 0.35;
const HUE_CHROMA_GRID_COLUMNS = 180;
const HUE_CHROMA_GRID_ROWS = 180;
const HUE_DEFINED_CHROMA_THRESHOLD = 0.02;
const HUE_CHROMA_ABSOLUTE_MAX = 0.35;

interface ReferenceAssets {
  labImage: string;
  rgbImage: string;
  hueLightnessImage: string;
  hueChromaImage: string;
}

const REFERENCE_ASSET_KEYS = [
  "labImage",
  "rgbImage",
  "hueLightnessImage",
  "hueChromaImage",
] as const;

type ReferenceAssetKey = (typeof REFERENCE_ASSET_KEYS)[number];

let cachedReferenceAssets: Partial<ReferenceAssets> = {};
let cachedHueLightnessBoundsProfile: Array<{ hue: number; minLightness: number; maxLightness: number }> | null = null;
let cachedHueChromaProfile: Array<{ hue: number; lightness: number; maxChroma: number }> | null = null;

function getHueLightnessBoundsProfile() {
  if (cachedHueLightnessBoundsProfile === null) {
    cachedHueLightnessBoundsProfile = buildHueLightnessBoundsProfile(721, 0.4, 0.02);
  }
  return cachedHueLightnessBoundsProfile;
}

function getHueChromaProfile() {
  if (cachedHueChromaProfile === null) {
    cachedHueChromaProfile = buildHuePeakProfile(721, HUE_CHROMA_ABSOLUTE_MAX);
  }
  return cachedHueChromaProfile;
}

function buildReferenceAsset(key: ReferenceAssetKey): string {
  switch (key) {
    case "labImage":
      return buildReferenceImageHref(
        buildLabReferencePoints(),
        LAB_REFERENCE_BOUNDS,
        480,
      );
    case "rgbImage":
      return buildReferenceImageHref(
        buildRgbReferencePoints(),
        RGB_REFERENCE_BOUNDS,
        480,
      );
    case "hueLightnessImage":
      return buildReferenceGridImageHref(
        HUE_LIGHTNESS_REFERENCE_BOUNDS,
        {
          viewSize: 480,
          columns: HUE_GRID_COLUMNS,
          rows: HUE_GRID_ROWS,
          cellBleed: HUE_GRID_BLEED,
          colorAt: (hue, lightness) => {
            const bounds = getInterpolatedHueLightnessBounds(getHueLightnessBoundsProfile(), hue);
            const absoluteLightness = bounds.minLightness + ((lightness / 100) * Math.max(bounds.maxLightness - bounds.minLightness, 1));
            const lightnessNormalized = absoluteLightness / 100;
            const chroma = maxOklchChromaForHueLightness(hue, lightnessNormalized, 0.4);
            return {
              fill: oklchToHexClamped({ l: lightnessNormalized, c: chroma, h: hue }),
            };
          },
        },
      );
    case "hueChromaImage":
      return buildReferenceGridImageHref(
        HUE_CHROMA_REFERENCE_BOUNDS,
        {
          viewSize: 480,
          columns: HUE_CHROMA_GRID_COLUMNS,
          rows: HUE_CHROMA_GRID_ROWS,
          cellBleed: HUE_GRID_BLEED,
          backgroundFill: "#0f172a",
          backgroundOpacity: 0.22,
          colorAt: (hue, chroma) => {
            return {
              fill: getHueChromaReferenceColor(hue, chroma, getHueChromaProfile()),
            };
          },
        },
      );
    default:
      return "";
  }
}

function getReferenceAsset(key: ReferenceAssetKey): string {
  const cached = cachedReferenceAssets[key];
  if (cached) {
    return cached;
  }
  const asset = buildReferenceAsset(key);
  cachedReferenceAssets = {
    ...cachedReferenceAssets,
    [key]: asset,
  };
  return asset;
}

function scheduleDeferredWork(callback: () => void): number {
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    return window.requestAnimationFrame(() => callback());
  }
  return window.setTimeout(callback, 0);
}

function cancelDeferredWork(handle: number): void {
  if (typeof window !== "undefined" && typeof window.cancelAnimationFrame === "function") {
    window.cancelAnimationFrame(handle);
    return;
  }
  window.clearTimeout(handle);
}

const LutDetailsLoadedPrimaryColumn = memo(function LutDetailsLoadedPrimaryColumn({
  detail,
  detailLoading,
  t,
}: {
  detail: LutDetailsResponse;
  detailLoading: boolean;
  t: (key: string) => string;
}) {
  const capabilities = detail.capabilities ?? [];
  const supportedModes = detail.supported_modes ?? [];
  const rawMetadataDescription = t("lut_details_raw_metadata_desc");

  return (
    <div data-testid="lut-details-loaded-view" className="flex flex-col gap-5">
      <section className={`${cardPadClass} flex flex-col gap-4`}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("lut_details_summary_title")}</h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("lut_details_summary_desc")}</p>
          </div>
          {detailLoading ? <span className="text-xs text-slate-500 dark:text-slate-400">{t("lut_details_loading")}</span> : null}
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          <InfoField fullWidth label={t("lut_details_summary_name")} value={detail.name} />
          <InfoField label={t("lut_details_summary_manufacturer")} value={detail.manufacturer} />
          <InfoField label={t("lut_details_summary_material")} value={detail.material_type} />
          <InfoField label={t("lut_details_summary_color_mode")} value={detail.color_mode} />
          <InfoField label={t("lut_details_summary_color_count")} value={String(detail.color_count)} />
          <InfoField label={t("lut_details_summary_source_kind")} value={detail.source_kind} />
          <InfoField fullWidth label={t("lut_details_summary_path")} value={detail.path} />
        </dl>
      </section>
      <LutDetailsPalette detail={detail} t={t} />
      <section className={`${cardPadClass} flex flex-col gap-4`}>
        <div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("lut_details_metadata_title")}</h3>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("lut_details_metadata_desc")}</p>
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          <InfoField label={t("lut_details_metadata_schema")} value={valueOrDash(detail.schema_version, t)} />
          <InfoField label={t("lut_details_metadata_manufacturer_source")} value={valueOrDash(detail.manufacturer_source, t)} />
          <InfoField label={t("lut_details_metadata_material_source")} value={valueOrDash(detail.material_source, t)} />
          <InfoField label={t("lut_details_metadata_max_color_layers")} value={String(detail.max_color_layers)} />
          <InfoField label={t("lut_details_metadata_layer_height")} value={formatMm(detail.layer_height_mm, t)} />
          <InfoField label={t("lut_details_metadata_line_width")} value={formatMm(detail.line_width_mm, t)} />
          <InfoField label={t("lut_details_metadata_base_layers")} value={String(detail.base_layers)} />
          <InfoField label={t("lut_details_metadata_base_channel")} value={String(detail.base_channel_idx)} />
          <InfoField label={t("lut_details_metadata_layer_order")} value={detail.layer_order} />
          <InfoField fullWidth label={t("lut_details_metadata_coverage")} value={replaceTokens(t("lut_details_coverage_summary"), { entries: detail.coverage_stats.entry_count, points: detail.coverage_stats.plotted_point_count })} />
        </dl>
        <div className="flex flex-col gap-3">
          <div>
            <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">{t("lut_details_capabilities_title")}</h4>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("lut_details_capabilities_desc")}</p>
          </div>
          <ChipList items={capabilities.map((capability) => localizeCapability(capability, t))} emptyLabel={t("lut_details_capabilities_empty")} />
        </div>
        <div className="flex flex-col gap-3">
          <div>
            <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">{t("lut_details_supported_modes_title")}</h4>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("lut_details_supported_modes_desc")}</p>
          </div>
          <ChipList items={supportedModes.map((mode) => formatModeItem(mode, t))} emptyLabel={t("lut_details_supported_modes_empty")} />
        </div>
      </section>
      <details data-testid="lut-details-raw-metadata" className={`${cardPadClass} group`}>
        <DisclosureSummary className="cursor-pointer list-none text-base font-semibold text-slate-900 outline-none dark:text-slate-50">{t("lut_details_raw_metadata_title")}</DisclosureSummary>
        {rawMetadataDescription ? <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{rawMetadataDescription}</p> : null}
        <pre className="dock-scrollbar mt-4 max-h-96 overflow-auto rounded-[10px] bg-slate-950/95 p-4 text-xs leading-6 text-slate-100">{JSON.stringify(detail.raw_metadata, null, 2)}</pre>
      </details>
    </div>
  );
});

/**
 * Reusable four-charts block: Lab a-b plane (with 2D/3D toggle), RGB
 * isometric projection, Hue x Lightness, Hue x Saturation. Backed by the
 * same scatter primitives used inside :class:`LutDetailsLoadedSecondaryColumn`
 * so the solver-cache "color distribution" view in
 * :class:`MaterialSolverCacheStatusCard` matches the LUT details page exactly.
 *
 * 复用的四图块：Lab a-b 平面（2D/3D 切换）、RGB 等距投影、色相×亮度、色相×饱和度。
 * 内部使用与 LUT 详情副列同一套散点图原语，使穷举缓存的"色彩分布图"与 LUT 详情
 * 页面视觉完全一致。
 */
export const LutColorDistributionCharts = memo(function LutColorDistributionCharts({
  source,
  className = "flex flex-col gap-5",
  compactHeaders = false,
}: {
  source: {
    lab_points: LutDetailsResponse["lab_points"];
    lab_points_3d: LutDetailsResponse["lab_points_3d"];
    lab_hull: LutDetailsResponse["lab_hull"];
    rgb_points: LutDetailsResponse["rgb_points"];
    coverage_stats: LutDetailsResponse["coverage_stats"];
  };
  workspaceMode?: ReturnType<typeof useWorkspaceMode>["mode"];
  className?: string;
  compactHeaders?: boolean;
}) {
  const { t } = useI18n();
  const [labChartView, setLabChartView] = useState<"2d" | "3d">("2d");
  const [referenceAssets, setReferenceAssets] = useState<Partial<ReferenceAssets>>(() => cachedReferenceAssets);
  const [hueProfilesReady, setHueProfilesReady] = useState(
    () => cachedHueLightnessBoundsProfile !== null && cachedHueChromaProfile !== null,
  );

  useEffect(() => {
    if (hueProfilesReady) return;
    let cancelled = false;
    const handle = scheduleDeferredWork(() => {
      getHueLightnessBoundsProfile();
      getHueChromaProfile();
      if (cancelled) return;
      startTransition(() => setHueProfilesReady(true));
    });
    return () => {
      cancelled = true;
      cancelDeferredWork(handle);
    };
  }, [hueProfilesReady]);

  useEffect(() => {
    const nextAssetKey = REFERENCE_ASSET_KEYS.find((key) => !referenceAssets[key]);
    if (!nextAssetKey) return;
    let cancelled = false;
    const handle = scheduleDeferredWork(() => {
      const asset = getReferenceAsset(nextAssetKey);
      if (cancelled) return;
      startTransition(() => {
        setReferenceAssets((current) => {
          if (current[nextAssetKey]) return current;
          return { ...current, [nextAssetKey]: asset };
        });
      });
    });
    return () => {
      cancelled = true;
      cancelDeferredWork(handle);
    };
  }, [referenceAssets]);

  const labPoints3D = source.lab_points_3d ?? [];
  const hueLightnessPoints = useMemo(
    () => (hueProfilesReady ? buildHueLightnessPoints(source.lab_points ?? []) : []),
    [source.lab_points, hueProfilesReady],
  );
  const hueChromaPoints = useMemo(
    () => (hueProfilesReady ? buildHueChromaPoints(source.lab_points ?? []) : []),
    [source.lab_points, hueProfilesReady],
  );
  const omittedHuePointCount = useMemo(
    () => (source.lab_points ?? []).length - hueLightnessPoints.length,
    [source.lab_points, hueLightnessPoints.length],
  );
  const hueRange = useMemo(
    () => formatCircularHueRange(hueLightnessPoints.map((point) => point.x)),
    [hueLightnessPoints],
  );
  const relativeLightnessRange = useMemo(
    () => formatRange(hueLightnessPoints.map((point) => point.y)),
    [hueLightnessPoints],
  );
  const chromaRange = useMemo(() => formatRange(hueChromaPoints.map((point) => point.y)), [hueChromaPoints]);
  const hueOmittedNote = omittedHuePointCount > 0
    ? replaceTokens(t("lut_details_hue_chart_omitted_neutral"), { count: omittedHuePointCount })
    : null;
  const labChartFooter = replaceTokens(t("lut_details_lab_chart_footer"), {
    lRange: formatNumberRange(source.coverage_stats.l_range.min, source.coverage_stats.l_range.max),
    aRange: formatNumberRange(source.coverage_stats.a_range.min, source.coverage_stats.a_range.max),
    bRange: formatNumberRange(source.coverage_stats.b_range.min, source.coverage_stats.b_range.max),
  });
  const labChartViewToggle = (
    <div className="panel-well inline-flex overflow-hidden rounded-full">
      <button
        type="button"
        className={`min-w-11 px-3 py-1.5 text-sm font-medium transition-colors ${
          labChartView === "2d"
            ? "bg-blue-500 text-white"
            : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
        }`}
        aria-pressed={labChartView === "2d"}
        onClick={() => setLabChartView("2d")}
      >
        {t("lut_details_lab_view_2d")}
      </button>
      <button
        type="button"
        className={`min-w-11 px-3 py-1.5 text-sm font-medium transition-colors ${
          labChartView === "3d"
            ? "bg-blue-500 text-white"
            : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
        }`}
        aria-pressed={labChartView === "3d"}
        onClick={() => setLabChartView("3d")}
      >
        {t("lut_details_lab_view_3d")}
      </button>
    </div>
  );

  return (
    <div className={className}>
      {labChartView === "2d" ? (
        <LutScatterChart
          title={t("lut_details_lab_chart_title")}
          descriptionAsTooltip={compactHeaders}
          description={t("lut_details_lab_chart_desc")}
          dataTestId="lut-details-lab-chart"
          points={source.lab_points ?? []}
          referenceImageHref={referenceAssets?.labImage}
          fixedBounds={LAB_REFERENCE_BOUNDS}
          hull={source.lab_hull ?? []}
          xLabel={t("lut_details_lab_chart_x")}
          yLabel={t("lut_details_lab_chart_y")}
          emptyMessage={t("lut_details_no_chart_points")}
          className={cardPadClass}
          showLabels={false}
          plotShape="square"
          footer={labChartFooter}
          headerAction={labChartViewToggle}
          squareViewportClassName={compactHeaders
            ? "mx-auto block w-full max-w-[560px] aspect-square max-h-[560px]"
            : "mx-auto block w-full max-w-[680px] aspect-square max-h-[680px]"}
        />
      ) : (
        <section className={cardPadClass}>
          <div className="mb-4 flex items-start justify-between gap-3">
            <div className={compactHeaders ? "flex min-h-8 min-w-0 flex-1 items-center gap-2" : "flex-1 min-w-0"}>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("lut_details_lab_chart_title")}</h3>
              {compactHeaders
                ? <HelpDot title={t("lut_details_lab_chart_title")} description={t("lut_details_lab_chart_3d_desc")} />
                : <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">{t("lut_details_lab_chart_3d_desc")}</p>}
            </div>
            {labChartViewToggle}
          </div>
          <LabPointCloud3D
            dataTestId="lut-details-lab-chart-3d"
            points={labPoints3D}
            emptyMessage={t("lut_details_no_chart_points")}
            loadingHullMessage={t("lut_details_lab_3d_loading_hull")}
            hullErrorMessage={t("lut_details_lab_3d_error_hull")}
            axisXLabel={t("lut_details_lab_3d_axis_x")}
            axisYLabel={t("lut_details_lab_3d_axis_y")}
            axisZLabel={t("lut_details_lab_3d_axis_z")}
            referenceSliceToggleLabel={t("lut_details_lab_3d_reference_toggle")}
            referenceSliceStatusTemplate={t("lut_details_lab_3d_reference_status")}
            referenceSliceSliderLabel={t("lut_details_lab_3d_reference_slider")}
          />
          <div className="mt-3 text-sm text-slate-500 dark:text-slate-400">{labChartFooter}</div>
        </section>
      )}
      <LutScatterChart
        title={t("lut_details_rgb_chart_title")}
        descriptionAsTooltip={compactHeaders}
        description={t("lut_details_rgb_chart_desc")}
        dataTestId="lut-details-rgb-chart"
        points={source.rgb_points ?? []}
        referenceImageHref={referenceAssets?.rgbImage}
        fixedBounds={RGB_REFERENCE_BOUNDS}
        xLabel={t("lut_details_rgb_chart_x")}
        yLabel={t("lut_details_rgb_chart_y")}
        emptyMessage={t("lut_details_no_chart_points")}
        className={cardPadClass}
        showLabels={false}
        plotShape="square"
        footer={replaceTokens(t("lut_details_rgb_chart_footer"), {
          rRange: formatNumberRange(source.coverage_stats.r_range.min, source.coverage_stats.r_range.max),
          gRange: formatNumberRange(source.coverage_stats.g_range.min, source.coverage_stats.g_range.max),
          bRange: formatNumberRange(source.coverage_stats.b_rgb_range.min, source.coverage_stats.b_rgb_range.max),
        })}
      />
      <LutScatterChart
        title={t("lut_details_hue_lightness_chart_title")}
        descriptionAsTooltip={compactHeaders}
        description={t("lut_details_hue_lightness_chart_desc")}
        dataTestId="lut-details-hue-lightness-chart"
        points={hueLightnessPoints}
        referenceImageHref={referenceAssets?.hueLightnessImage}
        fixedBounds={HUE_LIGHTNESS_REFERENCE_BOUNDS}
        xLabel={t("lut_details_hue_lightness_chart_x")}
        yLabel={t("lut_details_hue_lightness_chart_y")}
        emptyMessage={t("lut_details_no_chart_points")}
        className={cardPadClass}
        showLabels={false}
        plotShape="wide"
        footer={appendSummaryPart(
          replaceTokens(t("lut_details_hue_lightness_chart_footer"), {
            lRange: relativeLightnessRange,
            hRange: hueRange,
          }),
          hueOmittedNote,
        )}
      />
      <LutScatterChart
        title={t("lut_details_hue_chroma_chart_title")}
        descriptionAsTooltip={compactHeaders}
        description={t("lut_details_hue_chroma_chart_desc")}
        dataTestId="lut-details-hue-chroma-chart"
        points={hueChromaPoints}
        referenceImageHref={referenceAssets?.hueChromaImage}
        fixedBounds={HUE_CHROMA_REFERENCE_BOUNDS}
        xLabel={t("lut_details_hue_chroma_chart_x")}
        yLabel={t("lut_details_hue_chroma_chart_y")}
        emptyMessage={t("lut_details_no_chart_points")}
        className={cardPadClass}
        showLabels={false}
        plotShape="wide"
        footer={appendSummaryPart(
          replaceTokens(t("lut_details_hue_chroma_chart_footer"), {
            cRange: chromaRange,
            hRange: hueRange,
          }),
          hueOmittedNote,
        )}
      />
    </div>
  );
});

function LutDetailsPalette({ detail, t }: {
  detail: LutDetailsResponse;
  t: (key: string) => string;
}) {
  const palette = detail.palette ?? [];
  return (
    <section className={`${cardPadClass} flex flex-col gap-4`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("lut_details_palette_title")}</h3>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("lut_details_palette_desc")}</p>
        </div>
        <span className="text-xs text-slate-500 dark:text-slate-400">{replaceTokens(t("lut_details_palette_count"), { count: palette.length })}</span>
      </div>
      {palette.length > 0 ? (
        <div className={`${wellClass} overflow-hidden`}>
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-slate-200/70 text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:border-slate-800/70 dark:text-slate-400">
                <th className="px-3 py-3">{t("lut_details_palette_color")}</th>
                <th className="px-3 py-3">{t("lut_details_palette_material")}</th>
                <th className="px-3 py-3">{t("lut_details_palette_hex")}</th>
              </tr>
            </thead>
            <tbody>{palette.map((item, index) => renderPaletteRow(item, index, t))}</tbody>
          </table>
        </div>
      ) : <div className={`${wellPadClass} px-4 py-5 text-sm leading-6 text-slate-500 dark:text-slate-400`}>{t("lut_details_no_palette")}</div>}
    </section>
  );
}

const LutDetailsLoadedSecondaryColumn = memo(function LutDetailsLoadedSecondaryColumn({
  detail,
  workspaceMode,
}: {
  detail: LutDetailsResponse;
  t: (key: string) => string;
  workspaceMode: ReturnType<typeof useWorkspaceMode>["mode"];
}) {
  return (
    <LutColorDistributionCharts
      compactHeaders
      className="lut-details-charts grid grid-cols-1 gap-4 @[48rem]/lut-charts:grid-cols-2 [&>*]:min-w-0"
      source={{
        lab_points: detail.lab_points,
        lab_points_3d: detail.lab_points_3d,
        lab_hull: detail.lab_hull,
        rgb_points: detail.rgb_points,
        coverage_stats: detail.coverage_stats,
      }}
      workspaceMode={workspaceMode}
    />
  );
});

function EmptyCard({
  title,
  description,
  emptyMessage,
}: {
  title: string;
  description?: string;
  emptyMessage: string;
}) {
  return (
    <section className={`${cardPadClass} flex flex-col gap-4`}>
      <div>
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{title}</h3>
        {description && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      <div className={`${wellPadClass} px-4 py-5 text-sm leading-6 text-slate-500 dark:text-slate-400`}>
        {emptyMessage}
      </div>
    </section>
  );
}

export default function LutDetailsPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const hasRequestedCatalogRef = useRef(false);
  const {
    catalog,
    catalogLoading,
    selectedManufacturer,
    selectedLutName,
    loadedLutName,
    query,
    detail,
    detailLoading,
    error,
    errorKind,
    hasLoadedDetail,
    isSelectionDirty,
    canLoadSelectedLut,
    fetchCatalog,
    loadSelectedLut,
    setQuery,
    selectManufacturer,
    selectLut,
    clearError,
  } = useLutDetailsStore();
  const [hasCompletedInitialCatalogLoad, setHasCompletedInitialCatalogLoad] = useState(
    () => catalog.length > 0,
  );

  useEffect(() => {
    if (!hasRequestedCatalogRef.current && !catalogLoading) {
      hasRequestedCatalogRef.current = true;
      void fetchCatalog().then(() => {
        if (useLutDetailsStore.getState().errorKind !== "catalog") {
          setHasCompletedInitialCatalogLoad(true);
        }
      });
    }
  }, [catalogLoading, fetchCatalog]);

  useEffect(() => {
    if (catalog.length > 0 && !hasCompletedInitialCatalogLoad) {
      setHasCompletedInitialCatalogLoad(true);
    }
  }, [catalog.length, hasCompletedInitialCatalogLoad]);

  const filteredCatalog = useMemo(
    () => filterLutDetailsCatalog(catalog, query, selectedManufacturer),
    [catalog, query, selectedManufacturer],
  );

  const lutOptions = filteredCatalog.items.map((item: LutDetailsCatalogItem) => ({
    label: `${item.name}${item.manufacturer ? ` · ${item.manufacturer}` : ""}`,
    value: item.name,
  }));

  const manufacturerOptions = filteredCatalog.manufacturers.map((manufacturer) => ({
    label: manufacturer,
    value: manufacturer,
  }));
  const visibleLoadedDetail = detail;
  const effectiveLoadedLutName = loadedLutName || detail?.name || "";
  const showLoadedView = Boolean(visibleLoadedDetail && (hasLoadedDetail || effectiveLoadedLutName));
  const showSelectionDirtyNotice = Boolean(
    showLoadedView
    && isSelectionDirty
    && effectiveLoadedLutName
    && selectedLutName
    && selectedLutName !== effectiveLoadedLutName
  );
  const showNoMatches = !catalogLoading
    && !error
    && filteredCatalog.items.length === 0
    && (catalog.length > 0 || hasCompletedInitialCatalogLoad);
  const handleLoadSelected = () => {
    clearError();
    void loadSelectedLut();
  };
  const handleRetry = () => {
    clearError();
    if (errorKind === "catalog") {
      void fetchCatalog().then(() => {
        if (useLutDetailsStore.getState().errorKind !== "catalog") {
          setHasCompletedInitialCatalogLoad(true);
        }
      });
      return;
    }
    if (selectedLutName) {
      void loadSelectedLut();
      return;
    }
    void fetchCatalog();
  };
  const handleDismissError = () => {
    const shouldRecoverCatalog = errorKind === "catalog" && catalog.length === 0;
    clearError();
    if (shouldRecoverCatalog) {
      void fetchCatalog().then(() => {
        if (useLutDetailsStore.getState().errorKind !== "catalog") {
          setHasCompletedInitialCatalogLoad(true);
        }
      });
    }
  };

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="lut-details-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} lut-details-panel @container/lut-details flex flex-col gap-5`}
    >
      <section data-testid="lut-details-selection-card" className="lut-details-toolbar flex flex-col gap-3">
        <div className="lut-details-selectors grid items-end gap-3">
          <div className="flex min-w-0 flex-col gap-1.5">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-200" htmlFor="lut-details-query">
              {t("lut_details_query_label")}
            </label>
            <input
              id="lut-details-query"
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("lut_details_query_placeholder")}
              className="min-h-11 w-full rounded-[10px] border border-slate-200/80 bg-slate-100 px-3.5 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] transition-all duration-200 hover:border-slate-300 hover:bg-slate-200 focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900/72 dark:text-slate-100 dark:hover:border-slate-600"
            />
          </div>

          <div data-testid="lut-details-manufacturer-dropdown" className="min-w-0">
            <Dropdown
              label={t("lut_details_manufacturer_label")}
              value={selectedManufacturer}
              options={manufacturerOptions}
              onChange={(value) => selectManufacturer(value)}
              disabled={catalogLoading}
              placeholder={t("lut_details_manufacturer_placeholder")}
            />
          </div>

          <div data-testid="lut-details-lut-dropdown" className="min-w-0">
            <Dropdown
              label={t("lut_details_lut_label")}
              value={selectedLutName}
              options={lutOptions}
              onChange={(value) => selectLut(value)}
              disabled={catalogLoading || filteredCatalog.items.length === 0}
              placeholder={t("lut_details_lut_placeholder")}
            />
          </div>

          <button
            type="button"
            onClick={handleLoadSelected}
            disabled={catalogLoading || !canLoadSelectedLut}
            className="action-control inline-flex min-h-11 shrink-0 items-center justify-center rounded-[10px] px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed"
          >
            {t("lut_details_load_action")}
          </button>
        </div>

        {catalogLoading ? <StatusBanner tone="info">{t("lut_details_catalog_loading")}</StatusBanner> : null}
        {!showLoadedView && !detailLoading && !error ? <StatusBanner tone="info">{t("lut_details_load_hint")}</StatusBanner> : null}
        {showSelectionDirtyNotice ? <StatusBanner tone="info">{t("lut_details_pending_loaded_notice")}</StatusBanner> : null}
        {!showLoadedView && detailLoading ? <StatusBanner tone="info">{t("lut_details_loading_selected")}</StatusBanner> : null}

        {error ? (
          <StatusBanner
            tone="error"
            action={(
              <div className="flex items-center gap-2">
                <button
                  onClick={handleRetry}
                  className="action-control rounded-full border border-current/20 px-3 py-1 text-xs transition-colors"
                >
                  {t("widget_retry")}
                </button>
                <CloseButton label={t("lut_details_close_error")} onClick={handleDismissError} />
              </div>
            )}
          >
            {renderErrorMessage(error, t)}
          </StatusBanner>
        ) : null}

        {showNoMatches ? <StatusBanner tone="warning">{t("lut_details_no_matches")}</StatusBanner> : null}
      </section>

      <div data-testid="lut-details-layout" className="grid min-h-0 shrink-0 grid-cols-1 items-start gap-4 @[60rem]/lut-details:grid-cols-[22rem_minmax(0,1fr)]">
        <div data-testid="lut-details-primary-column" className="flex min-w-0 flex-col gap-4">
          {showLoadedView && visibleLoadedDetail ? (
            <LutDetailsLoadedPrimaryColumn
              detail={visibleLoadedDetail}
              detailLoading={detailLoading}
              t={t}
            />
          ) : (
            <div className="flex flex-col gap-5">
              <EmptyCard
                title={t("lut_details_summary_title")}
                emptyMessage={t("lut_details_no_detail")}
              />
              <EmptyCard
                title={t("lut_details_metadata_title")}
                description={t("lut_details_metadata_desc")}
                emptyMessage={t("lut_details_no_detail")}
              />
              <EmptyCard
                title={t("lut_details_palette_title")}
                description={t("lut_details_palette_desc")}
                emptyMessage={t("lut_details_no_palette")}
              />
              <details data-testid="lut-details-raw-metadata" className={`${cardPadClass} group`}>
                <DisclosureSummary className="cursor-pointer list-none text-base font-semibold text-slate-900 outline-none dark:text-slate-50">{t("lut_details_raw_metadata_title")}</DisclosureSummary>
                <pre className="dock-scrollbar mt-4 max-h-96 overflow-auto rounded-[10px] bg-slate-950/95 p-4 text-xs leading-6 text-slate-100">
                  {t("lut_details_no_raw_metadata")}
                </pre>
              </details>
            </div>
          )}
        </div>

        <div data-testid="lut-details-secondary-column" className="@container/lut-charts flex min-w-0 flex-col gap-4">
          {showLoadedView && visibleLoadedDetail ? (
            <LutDetailsLoadedSecondaryColumn
              detail={visibleLoadedDetail}
              t={t}
              workspaceMode={workspace.mode}
            />
          ) : (
            <div className="flex flex-col gap-5">
              <EmptyCard
                title={t("lut_details_lab_chart_title")}
                description={t("lut_details_lab_chart_desc")}
                emptyMessage={t("lut_details_no_chart_points")}
              />
              <EmptyCard
                title={t("lut_details_rgb_chart_title")}
                description={t("lut_details_rgb_chart_desc")}
                emptyMessage={t("lut_details_no_chart_points")}
              />
              <EmptyCard
                title={t("lut_details_hue_lightness_chart_title")}
                description={t("lut_details_hue_lightness_chart_desc")}
                emptyMessage={t("lut_details_no_chart_points")}
              />
              <EmptyCard
                title={t("lut_details_hue_chroma_chart_title")}
                description={t("lut_details_hue_chroma_chart_desc")}
                emptyMessage={t("lut_details_no_chart_points")}
              />
            </div>
          )}
        </div>
      </div>
    </motion.aside>
  );
}
