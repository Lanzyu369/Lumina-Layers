import { expect, it, vi } from "vitest";
vi.mock("../client", () => ({ default: { post: vi.fn().mockResolvedValue({ data: { ticket_id: "test" } }) } }));
import apiClient from "../client";
import { submitBugReport, type BugReportRequestPayload } from "../feedback";

it("uploads model and batch sources together with the exact original", async () => {
  const original = new File(["<svg>original</svg>"], "source.svg");
  const model = new File(["solid plate"], "plate.stl");
  const batch = new File(["image"], "second.png");
  await submitBugReport({ description: "error", context: {} } as BugReportRequestPayload, original, [original, model, batch]);
  const form = vi.mocked(apiClient.post).mock.calls.at(-1)?.[1] as FormData;
  expect(form.get("original_image")).toMatchObject({ name: original.name, size: original.size });
  expect(form.getAll("source_files").map((file) => (file as File).name)).toEqual([model.name, batch.name]);
});
