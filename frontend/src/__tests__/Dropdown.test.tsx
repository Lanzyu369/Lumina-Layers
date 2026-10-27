import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import Dropdown from "../components/ui/Dropdown";

describe("Dropdown", () => {
  it("renders flat options without changing the existing options API", () => {
    const onChange = vi.fn();
    render(
      <Dropdown
        label="Mode"
        value="a"
        options={[
          { label: "Option A", value: "a" },
          { label: "Option B", value: "b" },
        ]}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "Mode" }));

    expect(screen.getByRole("option", { name: "Option A" }))
      .toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("option", { name: "Option B" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("renders grouped option headers as non-selectable text", () => {
    const onChange = vi.fn();
    render(
      <Dropdown
        label="LUT"
        value=""
        groupedOptions={[
          {
            label: "4-Color",
            options: [{ label: "Brand A 4C", value: "a4" }],
          },
          {
            label: "8-Color",
            options: [{ label: "Brand A 8C", value: "a8" }],
          },
        ]}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "LUT" }));
    const listbox = screen.getByRole("listbox");

    expect(within(listbox).getByText("4-Color")).toBeInTheDocument();
    expect(within(listbox).getByText("8-Color")).toBeInTheDocument();
    expect(
      within(listbox).queryByRole("option", { name: "4-Color" }),
    ).not.toBeInTheDocument();

    fireEvent.click(within(listbox).getByText("4-Color"));
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("option", { name: "Brand A 8C" }));
    expect(onChange).toHaveBeenCalledWith("a8");
  });

  it("warns when flat and grouped options are provided together", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    render(
      <Dropdown
        label="LUT"
        value=""
        options={[{ label: "Flat", value: "flat" }]}
        groupedOptions={[
          {
            label: "Grouped",
            options: [{ label: "Grouped Item", value: "grouped" }],
          },
        ]}
        onChange={() => {}}
      />,
    );

    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("options and groupedOptions"),
    );
  });

  it("handles empty option arrays and skips empty group headers", () => {
    render(
      <Dropdown
        label="Empty"
        value=""
        groupedOptions={[
          { label: "Empty Group", options: [] },
          {
            label: "Non-empty Group",
            options: [{ label: "Only Item", value: "only" }],
          },
        ]}
        onChange={() => {}}
      />,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "Empty" }));

    expect(screen.queryByText("Empty Group")).not.toBeInTheDocument();
    expect(screen.getByText("Non-empty Group")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Only Item" })).toBeInTheDocument();
  });
});
