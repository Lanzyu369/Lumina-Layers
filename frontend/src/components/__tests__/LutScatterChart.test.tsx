import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  LutScatterChart,
  deriveBounds,
  getPointRadius,
} from "../lutDetails/LutScatterChart";

describe("LutScatterChart", () => {
  it("normalizes chart bounds to keep x/y spans equal", () => {
    const bounds = deriveBounds([
      { x: 0, y: 0 },
      { x: 100, y: 10 },
    ]);

    expect(bounds.maxX - bounds.minX).toBeCloseTo(bounds.maxY - bounds.minY, 6);
  });

  it("reduces point radius as point count increases", () => {
    expect(getPointRadius(4)).toBeGreaterThan(getPointRadius(80));
    expect(getPointRadius(80)).toBeGreaterThan(getPointRadius(800));
  });

  it("uses preserved aspect ratio and suppresses labels for dense plots", () => {
    const points = Array.from({ length: 40 }, (_, index) => ({
      x: index,
      y: index % 7,
      hex_color: "#ff0000",
      label: `pt-${index}`,
    }));

    render(
      <LutScatterChart
        title="Dense"
        dataTestId="dense-chart"
        points={points}
        referenceImageHref="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E"
        fixedBounds={{ minX: -1, maxX: 1, minY: -1, maxY: 1 }}
        xLabel="X"
        yLabel="Y"
        emptyMessage="Empty"
      />,
    );

    const svg = screen.getByTestId("dense-chart");
    expect(svg.getAttribute("preserveAspectRatio")).toBe("xMidYMid meet");
    expect(svg.querySelectorAll('image[data-layer="reference"]').length).toBe(1);
    const visibleTexts = Array.from(svg.querySelectorAll("text")).map((node) => node.textContent);
    expect(visibleTexts).not.toContain("pt-0");
  });

  it("keeps a visible point stroke even for dense LUT plots", () => {
    const points = Array.from({ length: 1600 }, (_, index) => ({
      x: index % 40,
      y: Math.floor(index / 40),
      hex_color: "#f8fafc",
    }));

    render(
      <LutScatterChart
        title="Dense With Stroke"
        dataTestId="dense-stroke-chart"
        points={points}
        fixedBounds={{ minX: 0, maxX: 40, minY: 0, maxY: 40 }}
        xLabel="X"
        yLabel="Y"
        emptyMessage="Empty"
      />,
    );

    const firstPoint = screen.getByTestId("dense-stroke-chart").querySelector("circle");
    expect(firstPoint).not.toBeNull();
    expect(Number(firstPoint?.getAttribute("stroke-width") ?? "0")).toBeGreaterThan(0);
  });

  it("stretches the reference background to fill wide charts", () => {
    render(
      <LutScatterChart
        title="Wide Background"
        dataTestId="wide-background-chart"
        points={[{ x: 10, y: 20, hex_color: "#00ff00" }]}
        referenceImageHref="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'/%3E"
        fixedBounds={{ minX: 0, maxX: 100, minY: 0, maxY: 100 }}
        xLabel="Hue"
        yLabel="Saturation"
        emptyMessage="Empty"
        plotShape="wide"
      />,
    );

    const referenceImage = screen
      .getByTestId("wide-background-chart")
      .querySelector('image[data-layer="reference"]');

    expect(referenceImage).not.toBeNull();
    expect(referenceImage?.getAttribute("preserveAspectRatio")).toBe("none");
  });

  it("keeps uniform point opacity for points with different neutral/chromatic labels", () => {
    render(
      <LutScatterChart
        title="Neutral Emphasis"
        dataTestId="neutral-emphasis-chart"
        points={[
          { x: 0, y: 10, hex_color: "#666666", label: "neutral-0.01" },
          { x: 10, y: 20, hex_color: "#ff0000", label: "chromatic-0.15" },
        ]}
        fixedBounds={{ minX: 0, maxX: 20, minY: 0, maxY: 20 }}
        xLabel="Hue"
        yLabel="Lightness"
        emptyMessage="Empty"
        plotShape="wide"
      />,
    );

    const circles = Array.from(
      screen.getByTestId("neutral-emphasis-chart").querySelectorAll("circle"),
    );
    expect(circles.length).toBe(2);
    expect(Number(circles[0].getAttribute("fill-opacity") ?? "0")).toBe(
      Number(circles[1].getAttribute("fill-opacity") ?? "0"),
    );
  });
});
