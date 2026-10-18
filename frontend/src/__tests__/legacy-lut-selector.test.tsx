import { useState } from "react";
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
  selectedCount: "Selected",
  brandInfo: "Brand Info",
  materialType: "Material Type",
  vendor: "Vendor",
  database: "Databases",
  databasePlaceholder: "No databases selected",
  dialogTitle: "Choose LUT",
  dialogSearchPlaceholder: "Search LUTs…",
  dialogAllGroups: "All color modes",
  dialogNoMatch: "No matching LUTs",
  dialogDeselectAll: "Deselect all",
  dialogConfirm: "Confirm",
  dialogCancel: "Cancel",
  openPicker: "Choose LUT databases…",
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
  it("renders the trigger button and refresh button", () => {
    renderSelector();

    // The trigger button opens the picker dialog
    expect(screen.getByTestId("lut-picker-trigger")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload LUT directory" })).toBeInTheDocument();
  });

  it("shows selected brand chip on the trigger", () => {
    renderSelector();
    const trigger = screen.getByTestId("lut-picker-trigger");
    expect(trigger).toHaveTextContent("Brand A");
  });

  it("shows selected LUT chip on the trigger", () => {
    renderSelector({ selectedLutNames: ["a4"] });
    const trigger = screen.getByTestId("lut-picker-trigger");
    expect(trigger).toHaveTextContent("A 4C");
  });

  it("shows overflow badge when more LUTs are selected than the visible limit", () => {
    renderSelector({ selectedLutNames: ["a4", "b4", "a8"] });
    const trigger = screen.getByTestId("lut-picker-trigger");
    // 2 visible chips + 1 overflow
    expect(trigger).toHaveTextContent("A 4C");
    expect(trigger).toHaveTextContent("B 4C");
    expect(trigger).toHaveTextContent("+1");
  });

  it("shows the LUT placeholder when brand is selected but no LUT is chosen", () => {
    renderSelector({ lutName: "", selectedLutNames: [] });
    const trigger = screen.getByTestId("lut-picker-trigger");
    expect(trigger).toHaveTextContent("Select a LUT");
  });

  it("shows the brand placeholder when no brand is selected", () => {
    renderSelector({ manufacturer: "", lutName: "", selectedLutNames: [] });
    const trigger = screen.getByTestId("lut-picker-trigger");
    expect(trigger).toHaveTextContent("Select a brand");
  });

  it("shows loading hint inside the dialog when loading", () => {
    renderSelector({ loading: true });

    // Open the dialog
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Loading LUT catalog")).toBeInTheDocument();
  });

  it("opens the picker dialog and shows brand sidebar", () => {
    renderSelector();

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByTestId("lut-picker-brand-sidebar")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Brand A" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Brand B" })).toBeInTheDocument();
  });

  it("shows all LUT options in the picker dialog", () => {
    renderSelector();

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("A 4C")).toBeInTheDocument();
    expect(within(dialog).getByText("B 4C")).toBeInTheDocument();
    expect(within(dialog).getByText("A 8C")).toBeInTheDocument();
  });

  it("emits manufacturer changes when a brand is clicked in the sidebar", () => {
    const onManufacturerChange = vi.fn();
    renderSelector({ onManufacturerChange });

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    fireEvent.click(screen.getByRole("button", { name: "Brand B" }));

    expect(onManufacturerChange).toHaveBeenCalledWith("Brand B");
  });

  it("emits multi-selected LUT names in selection order when confirm is clicked", () => {
    const onLutSelectionChange = vi.fn();
    renderSelector({ selectedLutNames: ["a4"], onLutSelectionChange });

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));

    const dialog = screen.getByRole("dialog");
    // Toggle B 4C on
    const b4cOption = within(dialog)
      .getAllByRole("checkbox")
      .find((el) => el.textContent?.includes("B 4C"));
    fireEvent.click(b4cOption!);

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    // a4 was pre-staged, b4 was added → grouped order a4, b4
    expect(onLutSelectionChange).toHaveBeenCalledWith(["a4", "b4"]);
  });

  it("deselects a LUT when toggled off in the dialog", () => {
    const onLutSelectionChange = vi.fn();
    renderSelector({ selectedLutNames: ["a4", "b4"], onLutSelectionChange });

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));

    const dialog = screen.getByRole("dialog");
    const b4cOption = within(dialog)
      .getAllByRole("checkbox")
      .find((el) => el.textContent?.includes("B 4C"));
    fireEvent.click(b4cOption!);
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    expect(onLutSelectionChange).toHaveBeenCalledWith(["a4"]);
  });

  it("retains cross-brand selections through navigation, confirm and reopening", () => {
    const onLutSelectionChange = vi.fn();
    const onManufacturerChange = vi.fn();

    // Each brand exposes its own list; applied names change only on confirm.
    function Harness() {
      const [manufacturer, setManufacturer] = useState("Brand A");
      const [names, setNames] = useState<string[]>(["a4"]);
      const grouped = manufacturer === "Brand A"
        ? [{ label: "4-Color", options: [{ label: "A 4C", value: "a4" }] }]
        : [{ label: "4-Color", options: [{ label: "B 4C", value: "b4" }] }];
      return (
        <LegacyLutSelector
          manufacturer={manufacturer}
          lutName={names[0] ?? ""}
          selectedLutNames={names}
          manufacturerOptions={manufacturerOptions}
          groupedLutOptions={grouped}
          allLutOptions={groupedLutOptions.flatMap((group) => group.options)}
          onManufacturerChange={(value) => {
            setManufacturer(value);
            onManufacturerChange(value);
          }}
          onLutChange={() => {}}
          onLutSelectionChange={(next) => {
            setNames(next);
            onLutSelectionChange(next);
          }}
          onRefresh={() => {}}
          onUploadClick={() => {}}
          labels={labels}
        />
      );
    }

    render(<Harness />);
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    const dialog = screen.getByRole("dialog");

    // Brand A's LUT arrives pre-staged from the current selection.
    expect(
      within(dialog).getAllByRole("checkbox")[0],
    ).toHaveAttribute("aria-checked", "true");

    fireEvent.click(within(dialog).getByRole("button", { name: "Brand B" }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /B 4C/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Brand A" }));
    expect(within(dialog).getByRole("checkbox", { name: /A 4C/ }))
      .toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    expect(onLutSelectionChange).toHaveBeenCalledWith(["a4", "b4"]);
    expect(screen.getByTestId("lut-picker-trigger")).toHaveTextContent("B 4C");
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    const reopened = screen.getByRole("dialog");
    fireEvent.click(within(reopened).getByRole("button", { name: "Brand B" }));
    expect(within(reopened).getByRole("checkbox", { name: /B 4C/ }))
      .toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(reopened).getByRole("checkbox", { name: /B 4C/ }));
    fireEvent.click(within(reopened).getByRole("button", { name: "Confirm" }));
    expect(onLutSelectionChange).toHaveBeenLastCalledWith(["a4"]);
  });

  it("cancels without committing when Escape is pressed", () => {
    const onLutSelectionChange = vi.fn();
    renderSelector({ selectedLutNames: ["a4"], onLutSelectionChange });

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onLutSelectionChange).not.toHaveBeenCalled();
  });

  it("shows the 'no brand' hint inside the dialog when no brand is selected", () => {
    renderSelector({ manufacturer: "", lutName: "" });

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));

    expect(screen.getByText("Pick a brand first")).toBeInTheDocument();
  });

  it("shows the sr-only live region with selected count", () => {
    renderSelector({ selectedLutNames: ["a4", "b4"] });

    // The sr-only region specifically
    const liveRegion = document.querySelector('[aria-live="polite"].sr-only');
    expect(liveRegion).not.toBeNull();
    expect(liveRegion!.textContent).toMatch(/2/);
  });
});
