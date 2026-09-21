import { describe, expect, it } from "vitest";

import { isUnsafeVisibleErrorText } from "../visibleErrorText";

describe("isUnsafeVisibleErrorText", () => {
  it.each([
    "No preview cache. Call POST /convert/preview first.",
    "Call POST /api/convert/preview first.",
    "fetch failed for http://localhost:8000/api/files/model.3mf",
    "file:///Users/min/private/source.png",
    "AxiosError: Request failed with status code 500",
    "ERR_NETWORK while downloading preview",
    "Traceback (most recent call last)",
    "C:\\Users\\min\\private\\source.png",
  ])("treats technical text as unsafe: %s", (message) => {
    expect(isUnsafeVisibleErrorText(message)).toBe(true);
  });

  it.each([
    "LUT not found",
    "Unsupported format",
    "Selected material is missing",
    "value must be <= 500",
    "/conversion mode is not supported",
    "/materialize is unavailable",
  ])("keeps business text safe: %s", (message) => {
    expect(isUnsafeVisibleErrorText(message)).toBe(false);
  });
});
