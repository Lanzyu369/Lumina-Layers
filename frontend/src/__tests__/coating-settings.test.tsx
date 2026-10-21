import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CoatingSettings from "../components/sections/CoatingSettings";
import { listGradientCardMaterials } from "../api/extractor";
import { useConverterStore } from "../stores/converter";
import { DEFAULT_STATE } from "../stores/converter/store";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";
import { buildBatchParams, buildGenerateParams } from "../stores/converter/requests";
import { buildConversionSourceParams } from "../stores/converter/sources";

vi.mock("../api/extractor", () => ({ listGradientCardMaterials: vi.fn() }));
vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listGradientCardMaterials).mockResolvedValue({ status: "ok", message: "ok", materials: [] });
  useConverterStore.setState({ ...DEFAULT_STATE, enable_coating: false });
});

describe("coating toggle and thickness", () => {
  it("enables coating without a material selector or library request", () => {
    render(<CoatingSettings />);
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /coating_enable/ }));
    expect(useConverterStore.getState().enable_coating).toBe(true);
    expect(screen.getByRole("slider")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(listGradientCardMaterials).not.toHaveBeenCalled();
  });

  it("keeps the selected thickness when coating is toggled off and on", () => {
    useConverterStore.setState({ enable_coating: true });
    render(<CoatingSettings />);
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0.12" } });
    expect(useConverterStore.getState().coating_height_mm).toBe(0.12);
    fireEvent.click(screen.getByRole("checkbox", { name: /coating_enable/ }));
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /coating_enable/ }));
    expect(screen.getByRole("slider")).toHaveValue("0.12");
  });

  it("sends only the coating switch and thickness for single and batch generation", () => {
    const state = { ...useConverterStore.getState(), lut_name: "colors", enable_coating: true, coating_height_mm: 0.12 };
    const source = buildConversionSourceParams(state)!;
    for (const params of [
      buildGenerateParams(state, DEFAULT_SETTINGS, source, undefined, undefined),
      buildBatchParams(state, DEFAULT_SETTINGS, source),
    ]) {
      expect(params.enable_coating).toBe(true);
      expect(params.coating_height_mm).toBe(0.12);
      expect(params).not.toHaveProperty("coating_material");
    }
  });
});
