import { describe, expect, it } from "vitest";
import { tRuntime } from "../i18n/runtime";
import { lutErrorToVisibleMessage } from "../stores/lutErrorMessages";

function makeAxiosLikeError(
  status: number,
  detail: string,
): Error & { response: { status: number; data: { detail: string } } } {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: { detail } },
  });
}

describe("lutErrorToVisibleMessage", () => {
  it.each([
    "LUT not found: stale-lut",
    "Selected LUT was not found or is unavailable.",
  ])("maps missing LUT 404 details to the refresh message", (detail) => {
    const error = makeAxiosLikeError(404, detail);

    const message = lutErrorToVisibleMessage(error);

    expect(message).toBe(tRuntime("lut_error_missing_refresh"));
    expect(message).not.toMatch(/LUT not found/i);
    expect(message).not.toBe("Selected LUT was not found or is unavailable.");
  });

  it("preserves actionable non-missing LUT details", () => {
    const detail = "The selected LUT does not support this color mode.";
    const error = makeAxiosLikeError(422, detail);

    expect(lutErrorToVisibleMessage(error)).toBe(detail);
  });
});
