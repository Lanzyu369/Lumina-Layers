import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useConverterStore } from "../../stores/converter";
import BasicSettings from "../sections/BasicSettings";

// Mock heavy child components to isolate conditional rendering logic
vi.mock("../ui/CropModal", () => ({
  CropModal: () => null,
}));

vi.mock("../ui/Dropdown", () => ({
  default: ({ label }: { label: string }) => (
    <div data-testid={`dropdown-${label}`}>{label}</div>
  ),
}));

vi.mock("../ui/Slider", () => ({
  default: ({ label }: { label: string }) => (
    <div data-testid={`slider-${label}`}>{label}</div>
  ),
}));

vi.mock("../ui/RadioGroup", () => ({
  default: ({ label }: { label: string }) => (
    <div data-testid={`radio-${label}`}>{label}</div>
  ),
}));

function makeFile(name: string, type = "image/png"): File {
  return new File(["dummy"], name, { type });
}

function getConverterImageInput(multiple: boolean): HTMLInputElement {
  const input = Array.from(
    document.querySelectorAll<HTMLInputElement>('input[type="file"]'),
  ).find(
    (candidate) =>
      candidate.accept.includes("image/png") && candidate.multiple === multiple,
  );
  if (!input) throw new Error("converter image input not found");
  return input;
}

describe("BasicSettings — auto batch mode (unified uploader)", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:test-preview");
    URL.revokeObjectURL = vi.fn();
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imageFile: null,
      imagePreviewUrl: null,
      lut_name: "",
      lutList: [],
      target_width_mm: 60,
      target_height_mm: 60,
      spacer_thick: 1.2,
      enableCrop: false,
      cropModalOpen: false,
      isCropping: false,
    });
  });

  it("does NOT render a batch mode checkbox (removed)", () => {
    render(<BasicSettings />);
    expect(
      screen.queryByRole("checkbox", { name: "批量模式" }),
    ).not.toBeInTheDocument();
  });

  it("shows UnifiedUploader upload hint when no image is selected", () => {
    render(<BasicSettings />);
    expect(
      screen.getByText("拖拽图片或 Lumina 项目文件"),
    ).toBeInTheDocument();
  });

  it("shows crop checkbox in SingleMode (imageFile set, no batchFiles)", () => {
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imageFile: makeFile("photo.png"),
      imagePreviewUrl: "blob:photo-preview",
    });
    render(<BasicSettings />);
    expect(
      screen.getByRole("checkbox", { name: "上传后裁剪" }),
    ).toBeInTheDocument();
  });

  it("shows separate replace and add actions in SingleMode", () => {
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imageFile: makeFile("photo.png"),
      imagePreviewUrl: "blob:photo-preview",
    });
    render(<BasicSettings />);
    expect(screen.getByText("更换当前图片")).toBeInTheDocument();
    expect(screen.getByText("添加更多图片")).toBeInTheDocument();
  });

  it("replaces the current SingleMode image without entering BatchMode", async () => {
    const oldFile = makeFile("old.png");
    const newFile = makeFile("new.png");
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imageFile: oldFile,
      imagePreviewUrl: "blob:old-preview",
    });
    render(<BasicSettings />);

    fireEvent.change(getConverterImageInput(false), {
      target: { files: [newFile] },
    });

    await waitFor(() => {
      const state = useConverterStore.getState();
      expect(state.imageFile).toBe(newFile);
      expect(state.batchFiles).toEqual([]);
      expect(state.batchMode).toBe(false);
    });
  });

  it("keeps add-more behavior as batch append from SingleMode", async () => {
    const oldFile = makeFile("old.png");
    const newFile = makeFile("new.png");
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imageFile: oldFile,
      imagePreviewUrl: "blob:old-preview",
    });
    render(<BasicSettings />);

    fireEvent.change(getConverterImageInput(true), {
      target: { files: [newFile] },
    });

    await waitFor(() => {
      const state = useConverterStore.getState();
      expect(state.imageFile).toBeNull();
      expect(state.batchFiles).toEqual([oldFile, newFile]);
      expect(state.batchMode).toBe(true);
    });
  });

  it("ignores invalid files from the replace input", async () => {
    const oldFile = makeFile("old.png");
    const invalidFile = makeFile("notes.txt", "text/plain");
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imageFile: oldFile,
      imagePreviewUrl: "blob:old-preview",
    });
    render(<BasicSettings />);

    fireEvent.change(getConverterImageInput(false), {
      target: { files: [invalidFile] },
    });

    await waitFor(() => {
      const state = useConverterStore.getState();
      expect(state.imageFile).toBe(oldFile);
      expect(state.batchFiles).toEqual([]);
      expect(state.batchMode).toBe(false);
    });
  });

  it("hides crop checkbox in BatchMode", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png"), makeFile("b.png")],
    });
    render(<BasicSettings />);
    expect(
      screen.queryByRole("checkbox", { name: "上传后裁剪" }),
    ).not.toBeInTheDocument();
  });

  it("shows batch file list when batchFiles exist", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png"), makeFile("b.jpg")],
    });
    render(<BasicSettings />);
    expect(screen.getByText("a.png")).toBeInTheDocument();
    expect(screen.getByText("b.jpg")).toBeInTheDocument();
    expect(screen.getByText("已选 2 个文件")).toBeInTheDocument();
  });
});
