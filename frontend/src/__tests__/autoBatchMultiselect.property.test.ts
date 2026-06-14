import { describe, it, beforeEach, expect } from "vitest";
import * as fc from "fast-check";
import { useConverterStore } from "../stores/converter";
import { isValidImageType } from "../stores/converter";
import type { BatchResponse } from "../api/types";

// ========== Generators ==========

const validMimeTypes = [
  "image/jpeg",
  "image/png",
  "image/svg+xml",
  "image/webp",
  "image/heic",
  "image/heif",
];

const arbValidFile: fc.Arbitrary<File> = fc
  .tuple(
    fc.string({ minLength: 1, maxLength: 20 }),
    fc.constantFrom(...validMimeTypes),
  )
  .map(([name, type]) => new File(["data"], `${name}.img`, { type }));

// ========== Helpers ==========

/** Reset store to clean initial state before each test iteration */
function resetStore(): void {
  useConverterStore.setState({
    imageFile: null,
    imagePreviewUrl: null,
    aspectRatio: null,
    sessionId: null,
    batchMode: false,
    batchFiles: [],
    batchLoading: false,
    batchResult: null,
    previewImageUrl: null,
    previewGlbUrl: null,
    hasManualPreview: false,
    enableCrop: false,
    cropModalOpen: false,
  });
}

function makeBatchResult(): BatchResponse {
  return {
    status: "success",
    message: "old batch result",
    download_url: "/old.zip",
    threemf_disk_path: "/old.3mf",
    preview_3d_url: "/old.glb",
    results: [],
    warnings: [],
  };
}

// ========== Operation type for random sequences ==========

type Op =
  | { type: "addFiles"; files: File[] }
  | { type: "removeFile"; index: number };

// ========== Tests ==========

describe("Auto-Batch Multiselect Property-Based Tests", () => {
  beforeEach(() => {
    resetStore();
  });

  // **Validates: Requirements 2.3, 4.1**
  describe("Property 1: batchMode 状态不变量", () => {
    it("batchMode always equals batchFiles.length > 0 after any sequence of operations", () => {
      // Generator: random sequence of addFiles / removeFile operations
      const arbOp: fc.Arbitrary<Op> = fc.oneof(
        fc
          .array(arbValidFile, { minLength: 1, maxLength: 5 })
          .map((files) => ({ type: "addFiles" as const, files })),
        fc
          .nat({ max: 9 })
          .map((index) => ({ type: "removeFile" as const, index })),
      );

      fc.assert(
        fc.property(
          fc.array(arbOp, { minLength: 1, maxLength: 20 }),
          (operations) => {
            resetStore();

            for (const op of operations) {
              if (op.type === "addFiles") {
                useConverterStore.getState().handleFilesSelect(op.files);
              } else {
                const state = useConverterStore.getState();
                // Only remove if there are batch files to remove from
                if (state.batchFiles.length > 0) {
                  const safeIndex = op.index % state.batchFiles.length;
                  useConverterStore.getState().removeBatchFile(safeIndex);
                }
              }

              // Invariant check after every operation
              const current = useConverterStore.getState();
              expect(current.batchMode).toBe(current.batchFiles.length > 0);
            }
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  // **Validates: Requirements 1.3, 3.4**
  describe("Property 2: 单文件选择进入 SingleMode", () => {
    it("single file from empty state sets imageFile and stays in SingleMode", () => {
      fc.assert(
        fc.property(arbValidFile, (file) => {
          resetStore();

          useConverterStore.getState().handleFilesSelect([file]);

          const state = useConverterStore.getState();
          expect(state.imageFile).toBe(file);
          expect(state.batchFiles).toEqual([]);
          expect(state.batchMode).toBe(false);
        }),
        { numRuns: 100 },
      );
    });

    it("single file from SingleMode appends to the current list and switches to BatchMode", () => {
      fc.assert(
        fc.property(arbValidFile, arbValidFile, (existingFile, newFile) => {
          resetStore();

          // Set up SingleMode with an existing file
          useConverterStore.getState().handleFilesSelect([existingFile]);
          // Verify we are in SingleMode
          expect(useConverterStore.getState().imageFile).toBe(existingFile);

          // Now select a new single file
          useConverterStore.getState().handleFilesSelect([newFile]);

          const state = useConverterStore.getState();
          expect(state.imageFile).toBeNull();
          expect(state.batchFiles).toEqual([existingFile, newFile]);
          expect(state.batchMode).toBe(true);
          expect(state.previewImageUrl).toBeNull();
          expect(state.sessionId).toBeNull();
          expect(state.previewGlbUrl).toBeNull();
        }),
        { numRuns: 100 },
      );
    });

    it("clears stale batch results when appending from SingleMode", () => {
      resetStore();
      const existingFile = new File(["a"], "existing.png", { type: "image/png" });
      const newFile = new File(["b"], "new.png", { type: "image/png" });

      useConverterStore.setState({
        imageFile: existingFile,
        batchResult: makeBatchResult(),
      });
      useConverterStore.getState().handleFilesSelect([newFile]);

      expect(useConverterStore.getState().batchFiles).toEqual([
        existingFile,
        newFile,
      ]);
      expect(useConverterStore.getState().batchResult).toBeNull();
    });

    it("clears stale batch results when appending while already in BatchMode", () => {
      resetStore();
      const existingFile = new File(["a"], "existing.png", { type: "image/png" });
      const newFile = new File(["b"], "new.png", { type: "image/png" });

      useConverterStore.setState({
        batchFiles: [existingFile],
        batchMode: true,
        batchResult: makeBatchResult(),
      });
      useConverterStore.getState().handleFilesSelect([newFile]);

      expect(useConverterStore.getState().batchFiles).toEqual([
        existingFile,
        newFile,
      ]);
      expect(useConverterStore.getState().batchResult).toBeNull();
    });
  });

  // **Validates: Requirements 1.4**
  describe("Property 3: 多文件选择进入 BatchMode", () => {
    it("selecting 2+ files from empty state enters BatchMode with all files", () => {
      fc.assert(
        fc.property(
          fc.array(arbValidFile, { minLength: 2, maxLength: 10 }),
          (files) => {
            resetStore();

            useConverterStore.getState().handleFilesSelect(files);

            const state = useConverterStore.getState();
            expect(state.batchFiles).toHaveLength(files.length);
            // Verify same file references
            for (let i = 0; i < files.length; i++) {
              expect(state.batchFiles[i]).toBe(files[i]);
            }
            expect(state.imageFile).toBeNull();
            expect(state.batchMode).toBe(true);
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  // **Validates: Requirements 1.6, 5.3**
  describe("Property 4: 无效文件格式过滤", () => {
    const invalidMimeTypes = [
      "text/plain",
      "application/pdf",
      "video/mp4",
      "audio/mpeg",
      "application/json",
    ];

    const arbInvalidFile: fc.Arbitrary<File> = fc
      .tuple(
        fc.string({ minLength: 1, maxLength: 20 }),
        fc.constantFrom(...invalidMimeTypes),
      )
      .map(([name, type]) => new File(["data"], `${name}.txt`, { type }));

    const arbMixedFiles = fc
      .tuple(
        fc.array(arbValidFile, { minLength: 1, maxLength: 10 }),
        fc.array(arbInvalidFile, { minLength: 1, maxLength: 5 }),
      )
      .map(([valid, invalid]) => [...valid, ...invalid]);

    it("mixed files: only valid image files are retained in store", () => {
      fc.assert(
        fc.property(arbMixedFiles, (mixedFiles) => {
          resetStore();

          // Shuffle to test different orderings
          const shuffled = [...mixedFiles].sort(() => Math.random() - 0.5);
          useConverterStore.getState().handleFilesSelect(shuffled);

          const state = useConverterStore.getState();
          const expectedValidCount = mixedFiles.filter((f) =>
            isValidImageType(f.type),
          ).length;

          if (expectedValidCount === 0) {
            // No valid files → store unchanged
            expect(state.imageFile).toBeNull();
            expect(state.batchFiles).toEqual([]);
          } else if (expectedValidCount === 1) {
            // Single valid file → SingleMode
            expect(state.imageFile).not.toBeNull();
            expect(isValidImageType(state.imageFile!.type)).toBe(true);
            expect(state.batchFiles).toEqual([]);
          } else {
            // Multiple valid files → BatchMode
            expect(state.batchFiles).toHaveLength(expectedValidCount);
            for (const f of state.batchFiles) {
              expect(isValidImageType(f.type)).toBe(true);
            }
            expect(state.imageFile).toBeNull();
          }
        }),
        { numRuns: 100 },
      );
    });

    it("all invalid files: store remains unchanged", () => {
      fc.assert(
        fc.property(
          fc.array(arbInvalidFile, { minLength: 1, maxLength: 10 }),
          (invalidFiles) => {
            resetStore();

            useConverterStore.getState().handleFilesSelect(invalidFiles);

            const state = useConverterStore.getState();
            expect(state.imageFile).toBeNull();
            expect(state.batchFiles).toEqual([]);
            expect(state.batchMode).toBe(false);
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  // **Validates: Requirements 4.5**
  describe("Property 5: 批量文件删除至单张自动降级", () => {
    it("removing batch files one-by-one until 1 remains auto-downgrades to SingleMode", () => {
      fc.assert(
        fc.property(
          fc.array(arbValidFile, { minLength: 2, maxLength: 10 }),
          (files) => {
            resetStore();

            // Enter BatchMode with all files
            useConverterStore.getState().handleFilesSelect(files);
            expect(useConverterStore.getState().batchMode).toBe(true);
            expect(useConverterStore.getState().batchFiles).toHaveLength(
              files.length,
            );

            // Remove files one by one (always index 0) until only 1 remains
            const totalToRemove = files.length - 1;
            for (let i = 0; i < totalToRemove; i++) {
              useConverterStore.getState().removeBatchFile(0);
            }

            // After removing all but one, should auto-downgrade to SingleMode
            const state = useConverterStore.getState();
            expect(state.imageFile).not.toBeNull();
            expect(state.imageFile).toBe(files[files.length - 1]);
            expect(state.batchFiles).toEqual([]);
            expect(state.batchMode).toBe(false);
          },
        ),
        { numRuns: 100 },
      );
    });
  });

  // **Validates: Requirements 6.1, 6.2**
  describe("Property 6: 单图模式合并到批量模式", () => {
    it("selecting new files in SingleMode merges existing imageFile into batchFiles and switches to BatchMode", () => {
      fc.assert(
        fc.property(
          arbValidFile,
          fc.array(arbValidFile, { minLength: 1, maxLength: 10 }),
          (existingFile, newFiles) => {
            resetStore();

            // Step 1: Enter SingleMode with existingFile
            useConverterStore.getState().handleFilesSelect([existingFile]);
            const singleState = useConverterStore.getState();
            expect(singleState.imageFile).toBe(existingFile);
            expect(singleState.batchFiles).toEqual([]);
            expect(singleState.batchMode).toBe(false);

            // Step 2: Select new files to trigger merge into BatchMode
            useConverterStore.getState().handleFilesSelect(newFiles);

            // Step 3: Verify merged state
            const state = useConverterStore.getState();

            // batchFiles should contain original imageFile + all new files
            expect(state.batchFiles).toHaveLength(1 + newFiles.length);
            // The original imageFile should be first in batchFiles
            expect(state.batchFiles[0]).toBe(existingFile);
            // All new files follow
            for (let i = 0; i < newFiles.length; i++) {
              expect(state.batchFiles[i + 1]).toBe(newFiles[i]);
            }

            // imageFile should be cleared
            expect(state.imageFile).toBeNull();
            // Should be in BatchMode
            expect(state.batchMode).toBe(true);

            // Preview state should be cleared (Requirement 6.2)
            expect(state.previewImageUrl).toBeNull();
            expect(state.sessionId).toBeNull();
            expect(state.previewGlbUrl).toBeNull();
          },
        ),
        { numRuns: 100 },
      );
    });
  });
});
