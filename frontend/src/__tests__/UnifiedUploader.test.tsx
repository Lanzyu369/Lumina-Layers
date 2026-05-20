import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import UnifiedUploader from "../components/ui/UnifiedUploader";

// Mock i18n — return key as-is
vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
}));

const defaultProps = {
  batchFiles: [] as File[],
  isBatchMode: false,
  onFilesSelect: vi.fn(),
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
