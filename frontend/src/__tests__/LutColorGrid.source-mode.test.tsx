import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import LutColorGrid from "../components/sections/LutColorGrid";
import { useConverterStore } from "../stores/converter";

vi.mock("../components/sections/MaterialColorPicker", () => ({
  default: () => <div data-testid="material-color-picker" />,
}));

describe("LutColorGrid source dispatch", () => {
  beforeEach(() => {
    useConverterStore.setState({ source_version: "legacy" });
  });

  it("uses the material color picker for Lumina Box archives", () => {
    useConverterStore.setState({ source_version: "lumina_box" });

    render(<LutColorGrid />);

    expect(screen.getByTestId("material-color-picker")).toBeInTheDocument();
  });
});
