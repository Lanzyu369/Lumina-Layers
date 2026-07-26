import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SlicerLogo from "../components/slicer/SlicerLogo";
import {
  getSlicerLogoSource,
  resolveSlicerBrandingId,
} from "../utils/slicerBranding";

describe("slicer branding", () => {
  it("resolves settings ids and detected ids to the same bundled logo", () => {
    expect(resolveSlicerBrandingId("bambu_studio")).toBe("BambuStudio");
    expect(getSlicerLogoSource("BambuStudio")).toBe(
      getSlicerLogoSource("bambu_studio"),
    );
    expect(getSlicerLogoSource("AnycubicSlicerNext")).toMatch(
      /anycubic-slicer-next/,
    );
  });

  it("renders a generic fallback for an unknown slicer", () => {
    render(<SlicerLogo slicerId="unknown_slicer" />);

    expect(screen.getByTestId("slicer-logo-fallback")).toBeInTheDocument();
  });

  it("keeps the plate in place and falls back when a bundled image fails", () => {
    render(<SlicerLogo slicerId="OrcaSlicer" />);

    const plate = screen.getByTestId("slicer-logo-OrcaSlicer");
    const image = screen.getByTestId("slicer-logo-image");
    fireEvent.error(image);

    expect(plate).toHaveClass("h-7", "w-7");
    expect(screen.getByTestId("slicer-logo-fallback")).toBeInTheDocument();
  });

  it("replaces the image with an in-slot spinner while loading", () => {
    render(<SlicerLogo slicerId="OrcaSlicer" variant="onBrand" loading />);

    expect(screen.getByTestId("slicer-logo-spinner")).toBeInTheDocument();
    expect(screen.queryByTestId("slicer-logo-image")).not.toBeInTheDocument();
  });
});
