import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../../../i18n/context";
import { useSettingsStore } from "../../../stores/settingsStore";
import BuildPlateSelector from "../BuildPlateSelector";

const plates = [
  {
    id: "textured-pei-plate",
    display_name: "Textured PEI Plate",
    display_name_zh: "纹理PEI打印板",
    image_url: "/bed_pei.png",
  },
  {
    id: "engineering-plate",
    display_name: "Engineering Plate",
    display_name_zh: "工程材料打印板",
    image_url: "/bed_engineering.png",
  },
  {
    id: "supertack-plate",
    display_name: "Bambu Cool Plate SuperTack",
    display_name_zh: "增稳低温打印板",
    image_url: "/bed_cool_supertack.png",
  },
];

function renderSelector(
  onSelect = vi.fn(),
  language: "zh" | "en" = "zh",
  selectedId = "textured-pei-plate",
) {
  return render(
    <I18nProvider>
      <BuildPlateSelector
        label="打印板"
        hint="hint"
        plates={plates}
        selectedId={selectedId}
        onSelect={onSelect}
        language={language}
      />
    </I18nProvider>,
  );
}

describe("BuildPlateSelector", () => {
  beforeEach(() => {
    useSettingsStore.getState().setLanguage("zh");
  });

  it("uses the official Chinese label and preserves artwork aspect ratio", () => {
    const onSelect = vi.fn();
    renderSelector(onSelect);

    const strip = screen.getByTestId("build-plate-horizontal-strip");
    const option = within(strip).getByRole("radio", { name: "纹理PEI打印板" });
    expect(option.querySelector("img")).toHaveClass(
      "max-h-full",
      "max-w-full",
      "object-contain",
    );
    fireEvent.click(option);
    expect(onSelect).toHaveBeenCalledWith("textured-pei-plate");
  });

  it("reserves space around cards so edge selection rings are not clipped", () => {
    renderSelector();

    const strip = screen.getByTestId("build-plate-horizontal-strip");
    expect(strip).toHaveClass(
      "pt-0.5",
      "px-0.5",
    );
    expect(
      within(strip).getByRole("radio", { name: "纹理PEI打印板" }),
    ).toHaveClass("ring-inset");
  });

  it("scales the card and artwork frame for wide 4K viewports", () => {
    renderSelector();

    const option = screen.getAllByRole("radio")[0];
    expect(option).toHaveClass("w-[clamp(11rem,14vw,20rem)]");
    expect(option.querySelector("span")).toHaveClass(
      "h-[clamp(6rem,10vw,14rem)]",
    );
  });

  it("switches back to the official English label in English mode", () => {
    renderSelector(vi.fn(), "en");

    expect(
      screen.getByRole("radio", { name: "Textured PEI Plate" }),
    ).toBeInTheDocument();
  });

  it("uses roving tab stops and moves forward with wrapping", () => {
    const onSelect = vi.fn();
    renderSelector(onSelect);

    const options = screen.getAllByRole("radio");
    expect(options[0]).toHaveAttribute("tabindex", "0");
    expect(options[1]).toHaveAttribute("tabindex", "-1");
    expect(options[2]).toHaveAttribute("tabindex", "-1");

    options[0].focus();
    expect(fireEvent.keyDown(options[0], { key: "ArrowRight" })).toBe(false);
    expect(options[1]).toHaveFocus();
    expect(onSelect).toHaveBeenLastCalledWith("engineering-plate");

    expect(fireEvent.keyDown(options[1], { key: "ArrowDown" })).toBe(false);
    expect(options[2]).toHaveFocus();
    expect(onSelect).toHaveBeenLastCalledWith("supertack-plate");

    expect(fireEvent.keyDown(options[2], { key: "ArrowRight" })).toBe(false);
    expect(options[0]).toHaveFocus();
    expect(onSelect).toHaveBeenLastCalledWith("textured-pei-plate");
  });

  it("moves backward with wrapping and supports Home and End", () => {
    const onSelect = vi.fn();
    renderSelector(onSelect, "zh", "engineering-plate");

    const options = screen.getAllByRole("radio");
    expect(options[0]).toHaveAttribute("tabindex", "-1");
    expect(options[1]).toHaveAttribute("tabindex", "0");

    options[0].focus();
    expect(fireEvent.keyDown(options[0], { key: "ArrowLeft" })).toBe(false);
    expect(options[2]).toHaveFocus();
    expect(onSelect).toHaveBeenLastCalledWith("supertack-plate");

    expect(fireEvent.keyDown(options[2], { key: "ArrowUp" })).toBe(false);
    expect(options[1]).toHaveFocus();
    expect(onSelect).toHaveBeenLastCalledWith("engineering-plate");

    expect(fireEvent.keyDown(options[1], { key: "Home" })).toBe(false);
    expect(options[0]).toHaveFocus();
    expect(onSelect).toHaveBeenLastCalledWith("textured-pei-plate");

    expect(fireEvent.keyDown(options[0], { key: "End" })).toBe(false);
    expect(options[2]).toHaveFocus();
    expect(onSelect).toHaveBeenLastCalledWith("supertack-plate");
  });
});
