import { describe, expect, it } from "vitest";
import {
  isGenerateRevisionConflict,
  newestEditorContentRevision,
} from "../stores/converter/editorRevision";

function httpError(status: number, detail: unknown) {
  return { response: { status, data: { detail } } };
}

describe("newestEditorContentRevision", () => {
  it("returns the largest finite revision", () => {
    expect(newestEditorContentRevision(3, 7, 5)).toBe(7);
    expect(newestEditorContentRevision(undefined, 4, null)).toBe(4);
    expect(newestEditorContentRevision(0)).toBe(0);
  });

  it("returns undefined when nothing is known", () => {
    expect(newestEditorContentRevision()).toBeUndefined();
    expect(newestEditorContentRevision(undefined, null, Number.NaN)).toBeUndefined();
  });
});

describe("isGenerateRevisionConflict", () => {
  it.each([
    "Visible content changed before generation started (editor content revision mismatch); refresh the editor state and try again.",
    "Visible content changed before large-format generation started; refresh the editor state and try again.",
    "Visible content changed before puzzle generation started (editor content revision mismatch); refresh the editor state and try again.",
    "Editor content changed while the generation snapshot was being assembled; refresh the editor state and try again.",
  ])("detects %s", (detail) => {
    expect(isGenerateRevisionConflict(httpError(409, detail))).toBe(true);
  });

  it("ignores other conflicts and statuses", () => {
    expect(
      isGenerateRevisionConflict(
        httpError(409, "Visible content changed while the selection tool was running (expected 1, current 2)."),
      ),
    ).toBe(false);
    expect(
      isGenerateRevisionConflict(
        httpError(409, "Editor selection changed before generation started; refresh the selection and try again."),
      ),
    ).toBe(false);
    expect(
      isGenerateRevisionConflict(
        httpError(500, "Visible content changed before generation started"),
      ),
    ).toBe(false);
    expect(isGenerateRevisionConflict(new Error("network"))).toBe(false);
    expect(isGenerateRevisionConflict(null)).toBe(false);
  });
});
