import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../components/ui/HelpDot", () => ({
  default: ({
    title,
    wikiPath,
  }: {
    title: string;
    wikiPath?: string;
  }) => <span data-testid={`help-${title}`} data-wiki-path={wikiPath} />,
}));

import Checkbox from "../components/ui/Checkbox";
import Dropdown from "../components/ui/Dropdown";
import RadioGroup from "../components/ui/RadioGroup";
import Slider from "../components/ui/Slider";

const wikiPath = "/docs/reference/converter-basic/actions/" as const;

describe("contextual Wiki-aware form controls", () => {
  it("forwards wikiPath from Slider to HelpDot", () => {
    render(
      <Slider
        label="Thickness"
        tooltip="Controls the final model thickness."
        wikiPath={wikiPath}
        value={1}
        min={0}
        max={2}
        step={0.1}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId("help-Thickness")).toHaveAttribute(
      "data-wiki-path",
      wikiPath,
    );
  });

  it("forwards wikiPath from Checkbox to HelpDot", () => {
    render(
      <Checkbox
        label="Precise matching"
        tooltip="Uses stricter color matching."
        wikiPath={wikiPath}
        checked={false}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId("help-Precise matching")).toHaveAttribute(
      "data-wiki-path",
      wikiPath,
    );
  });

  it("forwards wikiPath from Dropdown to HelpDot", () => {
    render(
      <Dropdown
        label="Source type"
        tooltip="Selects the input workflow."
        wikiPath={wikiPath}
        value="image"
        options={[{ label: "Image", value: "image" }]}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId("help-Source type")).toHaveAttribute(
      "data-wiki-path",
      wikiPath,
    );
  });

  it("forwards wikiPath from RadioGroup to HelpDot", () => {
    render(
      <RadioGroup
        label="Modeling mode"
        tooltip="Selects how geometry is generated."
        wikiPath={wikiPath}
        value="flat"
        options={[{ label: "Flat", value: "flat" }]}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId("help-Modeling mode")).toHaveAttribute(
      "data-wiki-path",
      wikiPath,
    );
  });
});
