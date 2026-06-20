import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import BatchResultSummary from "../ui/BatchResultSummary";
import type { BatchResponse } from "../../api/types";

const allSuccessResult: BatchResponse = {
  status: "ok",
  message: "batch done",
  download_url: "/output/batch_123.3mf",
  preview_3d_url: null,
  results: [
    { filename: "photo1.png", status: "success" },
    { filename: "photo2.jpg", status: "success" },
    { filename: "photo3.svg", status: "success" },
  ],
  warnings: [],
};

const allFailedResult: BatchResponse = {
  status: "failed",
  message: "all failed",
  download_url: null,
  preview_3d_url: null,
  results: [
    { filename: "bad1.png", status: "failed", error: "LUT not found" },
    { filename: "bad2.jpg", status: "failed", error: "Invalid dimensions" },
  ],
  warnings: [],
};

const mixedResult: BatchResponse = {
  status: "ok",
  message: "partial success",
  download_url: "/output/batch_789.3mf",
  preview_3d_url: null,
  results: [
    { filename: "good1.png", status: "success" },
    { filename: "good2.jpg", status: "success" },
    { filename: "fail1.svg", status: "failed", error: "Unsupported format" },
  ],
  warnings: [],
};

const rawFailureResult: BatchResponse = {
  status: "failed",
  message: "all failed",
  download_url: null,
  preview_3d_url: null,
  results: [
    {
      filename: "private.png",
      status: "failed",
      error: "cannot read /Users/min/private/batch-input/private.png: Permission denied",
    },
  ],
  warnings: [],
};

describe("BatchResultSummary", () => {
  describe("all success", () => {
    it("shows correct success count and total", () => {
      const { container } = render(<BatchResultSummary result={allSuccessResult} />);
      const text = container.textContent ?? "";
      expect(text).toContain("3");
      expect(text).toMatch(/成功.*3.*总计.*3/);
    });

    it("renders download button with relative href", () => {
      render(<BatchResultSummary result={allSuccessResult} />);
      const link = screen.getByRole("link", { name: "下载批量 3MF" });
      expect(link).toHaveAttribute("href", "/output/batch_123.3mf");
    });

    it("does not show failed section", () => {
      render(<BatchResultSummary result={allSuccessResult} />);
      expect(screen.queryByText("失败文件：")).not.toBeInTheDocument();
    });
  });

  describe("all failed", () => {
    it("shows correct counts with zero success", () => {
      const { container } = render(<BatchResultSummary result={allFailedResult} />);
      const text = container.textContent ?? "";
      expect(text).toMatch(/成功.*0.*总计.*2/);
      expect(text).toMatch(/失败.*2/);
    });

    it("does not render download button", () => {
      render(<BatchResultSummary result={allFailedResult} />);
      expect(screen.queryByRole("link", { name: "下载批量 3MF" })).not.toBeInTheDocument();
    });

    it("shows failed file details", () => {
      render(<BatchResultSummary result={allFailedResult} />);
      expect(screen.getByText("bad1.png")).toBeInTheDocument();
      expect(screen.getByText(/LUT not found/)).toBeInTheDocument();
      expect(screen.getByText("bad2.jpg")).toBeInTheDocument();
      expect(screen.getByText(/Invalid dimensions/)).toBeInTheDocument();
    });

    it("hides raw local paths from failed file details", () => {
      const { container } = render(<BatchResultSummary result={rawFailureResult} />);
      const text = container.textContent ?? "";
      expect(text).toContain("private.png");
      expect(text).toContain("这个文件无法转换。请重新上传该文件，或查看服务端日志了解详情。");
      expect(text).not.toContain("/Users/min/private");
      expect(text).not.toContain("Permission denied");
    });
  });

  describe("mixed", () => {
    it("shows correct counts", () => {
      const { container } = render(<BatchResultSummary result={mixedResult} />);
      const text = container.textContent ?? "";
      expect(text).toMatch(/成功.*2.*总计.*3/);
      expect(text).toMatch(/失败.*1/);
    });

    it("renders download button", () => {
      render(<BatchResultSummary result={mixedResult} />);
      const link = screen.getByRole("link", { name: "下载批量 3MF" });
      expect(link).toHaveAttribute("href", "/output/batch_789.3mf");
    });

    it("shows only failed item in failed list", () => {
      render(<BatchResultSummary result={mixedResult} />);
      const failedList = screen.getByRole("list", { name: "失败文件列表" });
      expect(failedList.textContent).toContain("fail1.svg");
      expect(failedList.textContent).not.toContain("good1.png");
      expect(failedList.textContent).not.toContain("good2.jpg");
    });
  });
});
