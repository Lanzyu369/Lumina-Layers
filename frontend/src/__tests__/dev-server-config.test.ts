import { describe, expect, it } from "vitest";

import { DEFAULT_DEV_PORT, resolveDevServerConfig } from "../../devServerConfig";

describe("devServerConfig", () => {
  it("uses a safe default dev port instead of the blocked 5174", () => {
    expect(DEFAULT_DEV_PORT).toBe(4174);
    expect(resolveDevServerConfig({})).toMatchObject({
      host: "0.0.0.0",
      port: 4174,
      strictPort: true,
    });
  });

  it("allows overriding the dev port via environment", () => {
    expect(resolveDevServerConfig({ VITE_DEV_PORT: "6123" })).toMatchObject({
      port: 6123,
    });
  });
});
