import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { I18nProvider } from "../../i18n/context";
import { translations } from "../../i18n/translations";
import { useConverterStore } from "../../stores/converter";
import {
  DEFAULT_SETTINGS,
  useSettingsStore,
} from "../../stores/settingsStore";
import { useWidgetStore } from "../../stores/widgetStore";
import BedSizeSelector from "../sections/BedSizeSelector";

function renderSelector() {
  return render(
    <I18nProvider>
      <BedSizeSelector />
    </I18nProvider>,
  );
}

describe("BedSizeSelector printer context", () => {
  beforeEach(() => {
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      language: "zh",
      printerModel: "bambu-p1s",
    });
    useConverterStore.setState({
      bed_label: "Bambu Lab P1S",
      bedSizes: [
        {
          label: "Bambu Lab P1S",
          width_mm: 256,
          height_mm: 256,
          is_default: false,
          printer_id: "bambu-p1s",
        },
      ],
      bedSizesLoading: false,
    });
    useWidgetStore.setState({ activeTab: "converter" });
  });

  it("distinguishes the LUT brand from the configured printer bed", () => {
    expect(translations.basic_lut_manufacturer_label).toEqual({
      zh: "选择LUT",
      en: "Select LUT",
    });

    renderSelector();

    expect(screen.getByText("打印机热床")).toBeInTheDocument();
    expect(
      screen.getByText("Bambu Lab P1S · 256×256 毫米"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "在设置中更改打印机" }),
    ).toBeInTheDocument();
  });

  it("does not repeat a custom bed label after localizing the unit", () => {
    useConverterStore.setState({
      bed_label: "256×256 mm",
      bedSizes: [
        {
          label: "256×256 mm",
          width_mm: 256,
          height_mm: 256,
          is_default: true,
          printer_id: null,
        },
      ],
    });

    renderSelector();

    expect(screen.getByText("256×256 mm")).toBeInTheDocument();
    expect(
      screen.queryByText("256×256 mm · 256×256 毫米"),
    ).not.toBeInTheDocument();
  });

  it("opens Settings from the printer-bed summary", () => {
    renderSelector();

    fireEvent.click(
      screen.getByRole("button", { name: "在设置中更改打印机" }),
    );

    expect(useWidgetStore.getState().activeTab).toBe("settings");
  });
});
