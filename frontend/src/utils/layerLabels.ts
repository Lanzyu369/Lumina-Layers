import type { translations } from "../i18n/translations";

type TranslationKey = keyof typeof translations;

type Translate = (key: TranslationKey) => string;

const ZH_DIGITS = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"];

function toChineseInteger(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return String(value);
  }

  if (value <= 10) {
    return value === 10 ? "十" : ZH_DIGITS[value];
  }

  if (value < 20) {
    return `十${value % 10 === 0 ? "" : ZH_DIGITS[value % 10]}`;
  }

  if (value < 100) {
    const tens = Math.floor(value / 10);
    const ones = value % 10;
    return `${ZH_DIGITS[tens]}十${ones === 0 ? "" : ZH_DIGITS[ones]}`;
  }

  return String(value);
}

export function formatDisplayLayerLabel(index: number, t: Translate, lang: "zh" | "en"): string {
  const { label, viewerSuffix } = formatDisplayLayerLabelParts(index, t, lang);
  return viewerSuffix ? `${label} ${viewerSuffix}` : label;
}

export function formatDisplayLayerLabelParts(
  index: number,
  t: Translate,
  lang: "zh" | "en",
): { label: string; viewerSuffix: string | null } {
  const layerNumber = index + 1;
  const label =
    lang === "zh"
      ? `第${toChineseInteger(layerNumber)}层`
      : `Layer ${layerNumber}`;

  if (layerNumber !== 1) {
    return { label, viewerSuffix: null };
  }

  return { label, viewerSuffix: t("layer_faces_viewer_suffix") };
}
