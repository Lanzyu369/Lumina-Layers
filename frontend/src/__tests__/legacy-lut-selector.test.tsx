import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import LegacyLutSelector from "../components/sections/LegacyLutSelector";

const labels = {
  manufacturer: "Brand",
  manufacturerPlaceholder: "Select a brand",
  lut: "LUT",
  lutPlaceholder: "Select a LUT",
  refreshTooltip: "Reload LUT directory",
  upload: "Upload",
  loadingHint: "Loading LUT catalog",
  noBrandHint: "Pick a brand first",
};

const manufacturerOptions = [
  { label: "Brand A", value: "Brand A" },
  { label: "Brand B", value: "Brand B" },
];

const groupedLutOptions = [
  {
    label: "4-Color",
    options: [{ label: "A 4C", value: "a4" }],
  },
  {
    label: "8-Color",
    options: [{ label: "A 8C", value: "a8" }],
  },
];

function renderSelector(overrides = {}) {
  return render(
    <LegacyLutSelector
      manufacturer="Brand A"
      lutName="a4"
      manufacturerOptions={manufacturerOptions}
      groupedLutOptions={groupedLutOptions}
      onManufacturerChange={() => {}}
      onLutChange={() => {}}
      onRefresh={() => {}}
      onUploadClick={() => {}}
      labels={labels}
      {...overrides}
    />,
  );
}

describe("LegacyLutSelector", () => {
  it("renders manufacturer and LUT dropdowns", () => {
    renderSelector();

    expect(screen.getByRole("combobox", { name: "Brand" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "LUT" })).toBeInTheDocument();
  });

  it("emits manufacturer changes", () => {
    const onManufacturerChange = vi.fn();
    renderSelector({ onManufacturerChange });

    fireEvent.click(screen.getByRole("combobox", { name: "Brand" }));
    fireEvent.click(screen.getByRole("option", { name: "Brand B" }));

    expect(onManufacturerChange).toHaveBeenCalledWith("Brand B");
  });

  it("renders LUT groups in the provided order", () => {
    renderSelector();

    fireEvent.click(screen.getByRole("combobox", { name: "LUT" }));
    const listbox = screen.getByRole("listbox");
    const labelsInOrder = within(listbox)
      .getAllByText(/Color$/)
      .map((node) => node.textContent);

    expect(labelsInOrder).toEqual(["4-Color", "8-Color"]);
  });

  it("emits multi-selected LUT names in grouped order", () => {
    const onLutSelectionChange = vi.fn();
    renderSelector({
      selectedLutNames: ["a4"],
      onLutSelectionChange,
      labels: {
        ...labels,
        multiSelect: "Multi-select LUTs",
        selectedCount: "Selected",
      },
    });

    fireEvent.click(screen.getByRole("checkbox", { name: "A 8C" }));

    expect(onLutSelectionChange).toHaveBeenCalledWith(["a4", "a8"]);
    expect(screen.getByText("Selected: 1")).toBeInTheDocument();
  });

  it("uses a vertical stack in compact mode", () => {
    const { container } = renderSelector({ compact: true });

    expect(container.firstElementChild).toHaveClass("grid-cols-1");
  });

  it("disables the brand dropdown while loading", () => {
    renderSelector({ loading: true });

    expect(screen.getByRole("combobox", { name: "Brand" })).toBeDisabled();
    expect(screen.getByText("Loading LUT catalog")).toBeInTheDocument();
  });

  it("disables the LUT dropdown until a brand is selected", () => {
    renderSelector({ manufacturer: "", lutName: "" });

    expect(screen.getByRole("combobox", { name: "LUT" })).toBeDisabled();
    expect(screen.getByText("Pick a brand first")).toBeInTheDocument();
  });
});
