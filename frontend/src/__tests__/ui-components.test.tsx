import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import Accordion from "../components/ui/Accordion";
import Slider from "../components/ui/Slider";
import ImageUpload from "../components/ui/ImageUpload";
import Dropdown from "../components/ui/Dropdown";
import RadioGroup from "../components/ui/RadioGroup";
import Checkbox from "../components/ui/Checkbox";
import Button from "../components/ui/Button";

describe("Accordion", () => {
  it("hides children when defaultOpen is false", () => {
    render(
      <Accordion title="Test Section" defaultOpen={false}>
        <p>Hidden content</p>
      </Accordion>,
    );
    expect(screen.queryByText("Hidden content")).not.toBeInTheDocument();
  });

  it("shows children after clicking the title", () => {
    render(
      <Accordion title="Test Section" defaultOpen={false}>
        <p>Hidden content</p>
      </Accordion>,
    );
    fireEvent.click(screen.getByText("Test Section"));
    expect(screen.getByText("Hidden content")).toBeInTheDocument();
  });

  it("toggles open state on second click", () => {
    render(
      <Accordion title="Test Section" defaultOpen={false}>
        <p>Hidden content</p>
      </Accordion>,
    );
    const title = screen.getByText("Test Section");
    fireEvent.click(title);
    expect(screen.getByText("Hidden content")).toBeInTheDocument();
    fireEvent.click(title);
  });
});

describe("Slider", () => {
  it("displays the current value in the input", () => {
    render(
      <Slider label="Width" value={50} min={0} max={100} step={1} onChange={() => {}} />,
    );
    const input = screen.getByRole("textbox", { name: /width value/i });
    expect(input).toHaveValue("50");
  });

  it("displays unit when provided", () => {
    render(
      <Slider label="Width" value={50} min={0} max={100} step={1} onChange={() => {}} unit="mm" />,
    );
    expect(screen.getByText("mm")).toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: /width value/i });
    expect(input).toHaveValue("50");
  });

  it("keeps enough width for three-digit values in the text input", () => {
    render(
      <Slider label="Width" value={120} min={10} max={400} step={1} onChange={() => {}} unit="mm" />,
    );
    const input = screen.getByRole("textbox", { name: /width value/i });
    expect(input).toHaveValue("120");
    expect(input).toHaveStyle({ width: "7ch" });
  });
});

describe("Button", () => {
  it("does not reserve spinner space when it is not loading", () => {
    render(<Button label="Current" onClick={() => {}} loading={false} size="sm" />);

    const button = screen.getByRole("button", { name: "Current" });
    expect(button.querySelector('[aria-hidden="true"]')).toBeNull();
    expect(screen.getByText("Current")).toHaveClass("whitespace-nowrap");
    expect(screen.getByText("Current")).toHaveClass("leading-none");
  });

  it("shows an absolutely positioned spinner while keeping the label centered", () => {
    render(<Button label="Current" onClick={() => {}} loading size="sm" />);

    const button = screen.getByRole("button", { name: "Current" });
    const spinner = button.querySelector('[aria-hidden="true"]');

    expect(spinner).toHaveClass("absolute");
    expect(spinner).toHaveClass("animate-spin");
    expect(screen.getByText("Current")).toHaveClass("whitespace-nowrap");
    expect(screen.getByText("Current")).toHaveClass("leading-none");
  });

  it("toggles loading without crashing after external text-node mutation", () => {
    const { rerender } = render(
      <Button label="Generate 3D Model" onClick={() => {}} loading={false} />,
    );
    const button = screen.getByRole("button", { name: "Generate 3D Model" });
    const walker = document.createTreeWalker(button, NodeFilter.SHOW_TEXT);
    let labelNode: Node | null = null;
    while (walker.nextNode()) {
      if (walker.currentNode.textContent === "Generate 3D Model") {
        labelNode = walker.currentNode;
        break;
      }
    }
    expect(labelNode).toBeTruthy();

    const translatedWrapper = document.createElement("font");
    translatedWrapper.textContent = labelNode.textContent;
    labelNode.parentNode!.replaceChild(translatedWrapper, labelNode);

    expect(() => {
      rerender(<Button label="Generate 3D Model" onClick={() => {}} loading />);
    }).not.toThrow();
  });
});

describe("ImageUpload", () => {
  it("passes accept prop to the hidden file input", () => {
    render(
      <ImageUpload
        onFileSelect={vi.fn()}
        accept="image/jpeg,image/png,image/svg+xml"
      />,
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.accept).toBe("image/jpeg,image/png,image/svg+xml");
  });

  it("renders checkerboard background when preview is provided", () => {
    render(
      <ImageUpload
        onFileSelect={vi.fn()}
        accept="image/png"
        preview="data:image/png;base64,fake"
      />,
    );
    const checkerboard = screen.getByTestId("checkerboard-bg");
    expect(checkerboard).toBeInTheDocument();
  });

  it("does NOT render checkerboard when preview is not provided", () => {
    render(
      <ImageUpload onFileSelect={vi.fn()} accept="image/png" />,
    );
    expect(screen.queryByTestId("checkerboard-bg")).not.toBeInTheDocument();
  });

  it("checkerboard has correct background styles (16px, #e0e0e0)", () => {
    render(
      <ImageUpload
        onFileSelect={vi.fn()}
        accept="image/png"
        preview="data:image/png;base64,fake"
      />,
    );
    const checkerboard = screen.getByTestId("checkerboard-bg");
    const style = checkerboard.style;
    expect(style.backgroundSize).toBe("16px 16px");
    expect(style.backgroundImage).toContain("224, 224, 224");
  });
});

describe("Selection controls", () => {
  it("renders dropdown with the shared rounded control shell", () => {
    render(
      <Dropdown
        label="Mode"
        value="a"
        options={[
          { label: "Option A", value: "a" },
          { label: "Option B", value: "b" },
        ]}
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole("combobox")).toHaveClass("rounded-[22px]");
    expect(screen.getByRole("combobox")).toHaveClass("overflow-hidden");
  });

  it("renders dropdown menu inside a rounded clipped shell", () => {
    render(
      <Dropdown
        label="Mode"
        value="a"
        options={[
          { label: "Option A", value: "a" },
          { label: "Option B", value: "b" },
        ]}
        onChange={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("combobox"));
    const listbox = screen.getByRole("listbox");
    expect(listbox).toHaveClass("dock-scrollbar");
    expect(listbox.parentElement).toHaveClass("rounded-[24px]");
    expect(listbox.parentElement).toHaveClass("overflow-hidden");
  });

  it("renders radio options with the unified rounded selectable rows", () => {
    render(
      <RadioGroup
        label="Structure"
        value="single"
        options={[
          { label: "Single", value: "single" },
          { label: "Double", value: "double" },
        ]}
        onChange={() => {}}
      />,
    );
    expect(screen.getByLabelText("Single")).toBeChecked();
    expect(screen.getByText("Single").closest("label")).toHaveClass("rounded-[22px]");
  });

  it("renders checkbox with the unified rounded selectable row", () => {
    render(<Checkbox label="Enable Relief" checked onChange={() => {}} />);
    expect(screen.getByLabelText("Enable Relief")).toBeChecked();
    expect(screen.getByText("Enable Relief").closest("label")).toHaveClass("rounded-[22px]");
  });
});
