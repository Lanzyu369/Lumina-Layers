import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import AdvancedSettings from "../components/sections/AdvancedSettings";
import { useConverterStore } from "../stores/converter";

beforeEach(() => {
  useConverterStore.setState({
    enable_cleanup: true,
    separate_backing: false,
    hue_enable: false,
    use_lut_constrained: false,
    auto_dynamic_range: false,
    high_precision_3d_preview: false,
    chroma_gate: 15,
    quantize_colors_unlocked: false,
  } as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AdvancedSettings — LUT-Constrained K-Means toggle", () => {
  it("renders the precise color matching checkbox", () => {
    render(<AdvancedSettings />);
    expect(
      screen.getByRole("checkbox", { name: /高精度颜色匹配/ }),
    ).toBeInTheDocument();
  });

  it("defaults to unchecked", () => {
    render(<AdvancedSettings />);
    const checkbox = screen.getByRole("checkbox", {
      name: /高精度颜色匹配/,
    });
    expect(checkbox).not.toBeChecked();
    expect(useConverterStore.getState().use_lut_constrained).toBe(false);
  });

  it("toggles store state on click", () => {
    render(<AdvancedSettings />);
    const checkbox = screen.getByRole("checkbox", {
      name: /高精度颜色匹配/,
    });

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().use_lut_constrained).toBe(true);

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().use_lut_constrained).toBe(false);
  });

  it("disables hue protection checkbox when precise matching is on", () => {
    useConverterStore.setState({ use_lut_constrained: true } as never);
    render(<AdvancedSettings />);

    const hueCheckbox = screen.getByRole("checkbox", {
      name: /色相保护/,
    });
    expect(hueCheckbox).toBeDisabled();
    expect(hueCheckbox).not.toBeChecked();
  });

  it("renders the auto dynamic range checkbox", () => {
    render(<AdvancedSettings />);
    const checkbox = screen.getByRole("checkbox", {
      name: /自动动态范围/,
    });
    expect(checkbox).toBeInTheDocument();
    expect(checkbox).not.toBeChecked();
    expect(useConverterStore.getState().auto_dynamic_range).toBe(false);
  });

  it("toggles auto dynamic range store state on click", () => {
    render(<AdvancedSettings />);
    const checkbox = screen.getByRole("checkbox", {
      name: /自动动态范围/,
    });

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().auto_dynamic_range).toBe(true);

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().auto_dynamic_range).toBe(false);
  });

  it("toggles high-precision 3D preview store state on click", () => {
    render(<AdvancedSettings />);
    const checkbox = screen.getByRole("checkbox", {
      name: /3D高精度颜色预览/,
    });

    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().high_precision_3d_preview).toBe(true);

    fireEvent.click(checkbox);
    expect(useConverterStore.getState().high_precision_3d_preview).toBe(false);
  });

  it("hides chroma gate slider when precise matching is enabled", () => {
    useConverterStore.setState({
      use_lut_constrained: true,
      hue_enable: true,
    } as never);
    render(<AdvancedSettings />);

    expect(
      screen.queryByRole("slider", { name: /暗色彩度门槛/ }),
    ).not.toBeInTheDocument();
  });
});
