import { describe, it, expect, afterEach } from "vitest";
import * as fc from "fast-check";
import { render, screen, cleanup } from "@testing-library/react";
import BatchResultSummary from "../ui/BatchResultSummary";
import type { BatchResponse, BatchItemResult } from "../../api/types";

const arbSuccessItem: fc.Arbitrary<BatchItemResult> = fc.record({
  filename: fc.string({ minLength: 1, maxLength: 30 }),
  status: fc.constant("success"),
  error: fc.constant(undefined),
});

const arbFailedItem: fc.Arbitrary<BatchItemResult> = fc.record({
  filename: fc.string({ minLength: 1, maxLength: 30 }),
  status: fc.constant("failed"),
  error: fc.string({ minLength: 1, maxLength: 50 }),
});

const arbMixedBatchResponse: fc.Arbitrary<BatchResponse> = fc
  .tuple(
    fc.array(arbSuccessItem, { minLength: 0, maxLength: 8 }),
    fc.array(arbFailedItem, { minLength: 0, maxLength: 8 }),
  )
  .filter(([s, f]) => s.length + f.length > 0)
  .map(([successItems, failedItems]) => ({
    status: failedItems.length === 0 ? "ok" : "failed",
    message: "batch done",
    download_url: successItems.length > 0 ? "/output/batch.3mf" : null,
    preview_3d_url: null,
    results: [...successItems, ...failedItems],
    warnings: [],
  }));

const arbWithSuccess: fc.Arbitrary<BatchResponse> = fc
  .tuple(
    fc.array(arbSuccessItem, { minLength: 1, maxLength: 8 }),
    fc.array(arbFailedItem, { minLength: 0, maxLength: 5 }),
    fc.stringMatching(/^[a-zA-Z0-9_-]{1,40}$/),
  )
  .map(([successItems, failedItems, dlUrl]) => ({
    status: "ok",
    message: "done",
    download_url: `/output/${dlUrl}.3mf`,
    preview_3d_url: null,
    results: [...successItems, ...failedItems],
    warnings: [],
  }));

const arbAllFailed: fc.Arbitrary<BatchResponse> = fc
  .array(arbFailedItem, { minLength: 1, maxLength: 10 })
  .map((failedItems) => ({
    status: "failed",
    message: "all failed",
    download_url: null,
    preview_3d_url: null,
    results: failedItems,
    warnings: [],
  }));

afterEach(() => {
  cleanup();
});

describe("batch result summary properties", () => {
  it("shows correct counts and failed details", () => {
    fc.assert(
      fc.property(arbMixedBatchResponse, (batchResponse) => {
        cleanup();

        const successCount = batchResponse.results.filter((r) => r.status === "success").length;
        const failedCount = batchResponse.results.filter((r) => r.status === "failed").length;
        const total = batchResponse.results.length;

        const { container } = render(<BatchResultSummary result={batchResponse} />);
        const text = container.textContent ?? "";

        expect(text).toContain(String(successCount));
        expect(text).toContain(String(total));

        if (failedCount > 0) {
          expect(text).toContain(String(failedCount));
        }

        for (const item of batchResponse.results.filter((r) => r.status === "failed")) {
          expect(text).toContain(item.filename);
          if (item.error) {
            expect(text).toContain(item.error);
          }
        }
      }),
      { numRuns: 100 },
    );
  });

  it("renders download button with relative href when there is at least one success", () => {
    fc.assert(
      fc.property(arbWithSuccess, (batchResponse) => {
        cleanup();
        render(<BatchResultSummary result={batchResponse} />);

        const downloadLink = screen.getByRole("link", { name: "下载批量 3MF" });
        expect(downloadLink).toHaveAttribute("href", batchResponse.download_url);
      }),
      { numRuns: 100 },
    );
  });

  it("does not render download button when all failed", () => {
    fc.assert(
      fc.property(arbAllFailed, (batchResponse) => {
        cleanup();
        render(<BatchResultSummary result={batchResponse} />);

        const downloadLink = screen.queryByRole("link", { name: "下载批量 3MF" });
        expect(downloadLink).not.toBeInTheDocument();
      }),
      { numRuns: 100 },
    );
  });
});
