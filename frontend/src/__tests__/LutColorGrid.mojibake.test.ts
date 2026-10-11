import { createElement } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LutColorGrid from "../components/sections/LutColorGrid";
import { translations } from "../i18n/translations";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";

let language: "zh" | "en" = "zh";
vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => translations[key]?.[language] ?? key, lang: language }),
}));

const originalConverter = useConverterStore.getState();
const originalSettings = useSettingsStore.getState();
beforeEach(() => {
  window.localStorage.clear();
  useConverterStore.setState({
    source_version: "legacy", lutColors: [{ hex: "#ff0000", rgb: [255, 0, 0] }],
    lutColorCards: [], lutColorsLoading: false, lutColorsLutName: "fixture",
    palette: [], selectedColor: null, pendingReplacement: null, replacePreviewLoading: false,
  });
  useSettingsStore.setState({ paletteMode: "swatch" });
});
afterEach(() => {
  cleanup();
  useConverterStore.setState(originalConverter);
  useSettingsStore.setState(originalSettings);
});

describe("Color swatch tooltips", () => {
  it.each(["zh", "en"] as const)("renders readable tooltip text and updates favorites in %s", (lang) => {
    language = lang;
    render(createElement(LutColorGrid));
    const swatch = screen.getByTitle(`#ff0000 · ${translations.lut_grid_dblclick_fav[lang]}`);
    fireEvent.doubleClick(swatch);
    expect(screen.getByTitle(`#ff0000 · ${translations.lut_grid_dblclick_unfav[lang]}`)).toBeInTheDocument();
  });
});
