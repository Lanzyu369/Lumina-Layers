import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import UnifiedUploader from "../components/ui/UnifiedUploader";

// Mock i18n — return key as-is
vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
}));

const defaultProps = {
  batchFiles: [] as File[],
  isBatchMode: false,
  onFilesSelect: vi.fn(),
  onFileReplace: vi.fn(),
  onBatchFileRemove: vi.fn(),
  accept: "image/jpeg,image/png,image/svg+xml,image/webp,image/heic,image/heif",
};

describe("UnifiedUploader", () => {
  it("renders upload hint text in empty state", () => {
    render(<UnifiedUploader {...defaultProps} />);
    expect(screen.getByText("upload_unified_hint")).toBeInTheDocument();
  });

  it("does not render a preview image in empty state", () => {
    render(<UnifiedUploader {...defaultProps} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("renders preview image in SingleMode when singlePreview is provided", () => {
    render(
      <UnifiedUploader
        {...defaultProps}
        singlePreview="data:image/png;base64,fakedata"
      />,
    );
    const img = screen.getByRole("img");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "data:image/png;base64,fakedata");
  });

  it("renders separate replace and add controls in SingleMode", () => {
    render(
      <UnifiedUploader
        {...defaultProps}
        singlePreview="data:image/png;base64,fakedata"
      />,
    );

    expect(screen.getByText("upload_replace_current")).toBeInTheDocument();
    expect(screen.getByText("upload_add_more")).toBeInTheDocument();
  });

  it("routes the SingleMode replace input through onFileReplace", async () => {
    const onFilesSelect = vi.fn();
    const onFileReplace = vi.fn();
    const file = new File(["new"], "new.jpg", { type: "image/jpeg" });

    render(
      <UnifiedUploader
        {...defaultProps}
        onFilesSelect={onFilesSelect}
        onFileReplace={onFileReplace}
        singlePreview="data:image/png;base64,fakedata"
      />,
    );

    const replaceInput = document.querySelector(
      'input[type="file"]:not([multiple])',
    ) as HTMLInputElement;
    fireEvent.change(replaceInput, { target: { files: [file] } });

    await waitFor(() => expect(onFileReplace).toHaveBeenCalledWith(file));
    expect(onFilesSelect).not.toHaveBeenCalled();
  });

  it("routes the SingleMode add-more input through onFilesSelect", async () => {
    const onFilesSelect = vi.fn();
    const onFileReplace = vi.fn();
    const file = new File(["new"], "new.jpg", { type: "image/jpeg" });

    render(
      <UnifiedUploader
        {...defaultProps}
        onFilesSelect={onFilesSelect}
        onFileReplace={onFileReplace}
        singlePreview="data:image/png;base64,fakedata"
      />,
    );

    const addMoreInput = document.querySelector(
      'input[type="file"][multiple]',
    ) as HTMLInputElement;
    fireEvent.change(addMoreInput, { target: { files: [file] } });

    await waitFor(() => expect(onFilesSelect).toHaveBeenCalledWith([file]));
    expect(onFileReplace).not.toHaveBeenCalled();
  });

  it("uses a full-width preview frame so viewBox-only SVG previews keep a nonzero layout size", () => {
    render(
      <UnifiedUploader
        {...defaultProps}
        singlePreview="blob:svg-preview"
      />,
    );

    const img = screen.getByRole("img");
    expect(img).toHaveClass("block");
    expect(img.parentElement).toHaveClass("w-full");
  });

  it("renders file list with file names in BatchMode", () => {
    const files = [
      new File(["a"], "photo1.jpg", { type: "image/jpeg" }),
      new File(["b"], "photo2.png", { type: "image/png" }),
    ];
    render(
      <UnifiedUploader
        {...defaultProps}
        batchFiles={files}
        isBatchMode={true}
      />,
    );
    expect(screen.getByText("photo1.jpg")).toBeInTheDocument();
    expect(screen.getByText("photo2.png")).toBeInTheDocument();
  });

  it("renders delete buttons for each batch file", () => {
    const files = [
      new File(["a"], "img1.jpg", { type: "image/jpeg" }),
      new File(["b"], "img2.png", { type: "image/png" }),
    ];
    render(
      <UnifiedUploader
        {...defaultProps}
        batchFiles={files}
        isBatchMode={true}
      />,
    );
    // Each file should have a delete button with aria-label containing the file name
    const deleteButtons = screen.getAllByRole("button", { name: /upload_delete_file/i });
    expect(deleteButtons).toHaveLength(2);
  });

  it("file input has the multiple attribute", () => {
    render(<UnifiedUploader {...defaultProps} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.multiple).toBe(true);
  });

  it("renders 'add more' area in BatchMode", () => {
    const files = [
      new File(["a"], "a.jpg", { type: "image/jpeg" }),
      new File(["b"], "b.png", { type: "image/png" }),
    ];
    render(
      <UnifiedUploader
        {...defaultProps}
        batchFiles={files}
        isBatchMode={true}
      />,
    );
    expect(screen.getByText("upload_add_more")).toBeInTheDocument();
  });

  it("limits the rendered batch file rows for large drops", () => {
    const files = Array.from(
      { length: 151 },
      (_, index) =>
        new File(["a"], `pokemon-${String(index + 1).padStart(3, "0")}.png`, {
          type: "image/png",
        }),
    );

    render(
      <UnifiedUploader
        {...defaultProps}
        batchFiles={files}
        isBatchMode={true}
      />,
    );

    expect(screen.getByText("pokemon-001.png")).toBeInTheDocument();
    expect(screen.getByText("pokemon-040.png")).toBeInTheDocument();
    expect(screen.queryByText("pokemon-041.png")).not.toBeInTheDocument();
    expect(screen.getByText("upload_file_list_truncated")).toBeInTheDocument();
  });
});
