import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CropModal } from "../CropModal";

const cropper = vi.hoisted(() => ({
  getData: vi.fn(() => ({ x: 10, y: 20, width: 120, height: 80 })),
  rotateTo: vi.fn(),
  clear: vi.fn(),
  crop: vi.fn(),
  getCanvasData: vi.fn(() => ({ naturalWidth: 120, naturalHeight: 80 })),
  getContainerData: vi.fn(() => ({ width: 600, height: 400 })),
  zoomTo: vi.fn(),
  setCanvasData: vi.fn(),
  setData: vi.fn(),
}));

vi.mock("react-cropper", async () => {
  const { forwardRef, useImperativeHandle } = await import("react");
  return { default: forwardRef(function MockCropper(_, ref) {
    useImperativeHandle(ref, () => ({ cropper }));
    return <div />;
  }) };
});

describe("CropModal rotation drafts", () => {
  beforeEach(() => vi.clearAllMocks());

  it("combines quarter turns with the current crop only when confirmed", () => {
    const onConfirm = vi.fn();
    render(<CropModal open imageSrc="blob:test" onConfirm={onConfirm} onClose={vi.fn()} onUseOriginal={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "向左旋转 90°" }));
    expect(cropper.rotateTo).toHaveBeenLastCalledWith(270);
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "应用更改" }));
    expect(onConfirm).toHaveBeenCalledWith({ x: 10, y: 20, width: 120, height: 80, rotation: 270 });
  });

  it("discards rotation on cancel and starts the next edit unrotated", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const props = { imageSrc: "blob:test", onConfirm, onClose: onCancel, onUseOriginal: onCancel };
    const view = render(<CropModal {...props} open />);
    fireEvent.click(screen.getByRole("button", { name: "向右旋转 90°" }));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
    view.rerender(<CropModal {...props} open={false} />);
    view.rerender(<CropModal {...props} open />);
    fireEvent.click(screen.getByRole("button", { name: "应用更改" }));
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ rotation: 0 }));
  });

  it("wraps four right turns back to the original orientation", () => {
    const onConfirm = vi.fn();
    render(<CropModal open imageSrc="blob:test" onConfirm={onConfirm} onClose={vi.fn()} onUseOriginal={vi.fn()} />);
    for (let i = 0; i < 4; i++) fireEvent.click(screen.getByRole("button", { name: "向右旋转 90°" }));
    expect(cropper.rotateTo).toHaveBeenLastCalledWith(0);
    fireEvent.click(screen.getByRole("button", { name: "应用更改" }));
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ rotation: 0 }));
  });
});
