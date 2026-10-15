import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CoatingSettings from "../components/sections/CoatingSettings";
import { listGradientCardMaterials } from "../api/extractor";
import { useConverterStore } from "../stores/converter";
import { DEFAULT_STATE } from "../stores/converter/store";

vi.mock("../api/extractor", () => ({ listGradientCardMaterials: vi.fn() }));
vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" }),
}));

const materials = [
  { material_name: "White PETG", directory_name: "white-petg", material_type: "PETG",
    estimated_rgb: [250, 250, 250], material_file_url: null },
  { material_name: "Clear PLA", directory_name: "clear-pla", material_type: "PLA",
    estimated_rgb: [240, 240, 240], material_file_url: null },
];

beforeEach(() => {
  vi.clearAllMocks();
  useConverterStore.setState({ ...DEFAULT_STATE, source_version: "material",
    selectedMaterialDirNames: ["white-petg"], enable_coating: true, coatingMaterial: null });
  vi.mocked(listGradientCardMaterials).mockResolvedValue({ status: "ok", message: "ok", materials });
});

describe("explicit coating material selection", () => {
  it("does not guess a coating and offers actual palette materials", async () => {
    render(<CoatingSettings />);
    await waitFor(() => expect(listGradientCardMaterials).toHaveBeenCalledOnce());
    expect(useConverterStore.getState().coatingMaterial).toBeNull();
    fireEvent.click(screen.getByRole("combobox", { name: "coating_material" }));
    const paletteOption = await screen.findAllByRole("option", { name: "White PETG · PETG" });
    fireEvent.click(paletteOption[0]);
    expect(useConverterStore.getState().coatingMaterial).toEqual({ source: "palette", key: "White PETG" });
  });

  it("preserves an intentional independent PLA coating and warns about mixed types", async () => {
    render(<CoatingSettings />);
    fireEvent.click(screen.getByRole("combobox", { name: "coating_material" }));
    fireEvent.click(await screen.findByRole("option", { name: "Clear PLA · PLA" }));
    expect(useConverterStore.getState().coatingMaterial).toEqual({ source: "material_archive", key: "clear-pla" });
    expect(screen.getByText("coating_material_mixed")).toBeInTheDocument();
    expect(useConverterStore.getState().selectedMaterialDirNames).toEqual(["white-petg"]);
  });

  it("keeps a saved identity while the library is unavailable and allows retry", async () => {
    vi.mocked(listGradientCardMaterials).mockRejectedValueOnce(new Error("offline"));
    useConverterStore.setState({ coatingMaterial: { source: "material_archive", key: "clear-pla" } });
    render(<CoatingSettings />);
    expect(await screen.findByText("coating_material_load_failed")).toBeInTheDocument();
    expect(useConverterStore.getState().coatingMaterial?.key).toBe("clear-pla");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "coating_material_retry" })));
    await waitFor(() => expect(screen.queryByText("coating_material_load_failed")).not.toBeInTheDocument());
    expect(screen.getByRole("combobox", { name: "coating_material" })).toHaveTextContent("Clear PLA · PLA");
  });
});
