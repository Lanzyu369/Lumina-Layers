import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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
  selectedCount: "Selected",
  brandInfo: "Brand Info",
  materialType: "Material Type",
  vendor: "Vendor",
  database: "Databases",
  databasePlaceholder: "No databases selected",
};

const manufacturerOptions = [
  { label: "Brand A", value: "Brand A" },
  { label: "Brand B", value: "Brand B" },
];

const groupedLutOptions = [
  {
    label: "4-Color",
    options: [
      { label: "A 4C", value: "a4" },
      { label: "B 4C", value: "b4" },
    ],
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
  it("renders the manufacturer dropdown and database panel", () => {
    renderSelector();

    expect(screen.getByRole("combobox", { name: "Brand" })).toBeInTheDocument();
    expect(screen.getByText(/Brand Info/)).toBeInTheDocument();
    expect(screen.getByText(/Databases/)).toBeInTheDocument();
  });

  it("emits manufacturer changes", () => {
    const onManufacturerChange = vi.fn();
    renderSelector({ onManufacturerChange });

    fireEvent.click(screen.getByRole("combobox", { name: "Brand" }));
    fireEvent.click(screen.getByRole("option", { name: "Brand B" }));

    expect(onManufacturerChange).toHaveBeenCalledWith("Brand B");
  });

  it("renders all database checkboxes", () => {
    renderSelector();

    expect(screen.getByRole("checkbox", { name: "A 4C" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "B 4C" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "A 8C" })).toBeInTheDocument();
  });

  it("emits multi-selected LUT names in grouped order", () => {
    const onLutSelectionChange = vi.fn();
    renderSelector({
      selectedLutNames: ["a4"],
      onLutSelectionChange,
      labels: {
        ...labels,
        multiSelect: "Multi-select LUTs",
      },
    });

    fireEvent.click(screen.getByRole("checkbox", { name: "B 4C" }));

    expect(onLutSelectionChange).toHaveBeenCalledWith(["a4", "b4"]);
    expect(screen.getByText("Selected: 1")).toBeInTheDocument();
  });

  it("allows selecting LUTs across color groups", () => {
    const onLutSelectionChange = vi.fn();
    renderSelector({
      selectedLutNames: ["a4"],
      onLutSelectionChange,
      labels: {
        ...labels,
        multiSelect: "Multi-select LUTs",
      },
    });

    expect(screen.getByRole("checkbox", { name: "A 4C" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "A 8C" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "A 8C" }));

    expect(onLutSelectionChange).toHaveBeenCalledWith(["a4", "a8"]);
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

    expect(screen.getByText("Pick a brand first")).toBeInTheDocument();
  });
});
