import { describe, expect, it } from "vitest";

import {
  DEFAULT_API_PROXY_TARGET,
  DEFAULT_DEV_PORT,
  resolveApiProxyTarget,
  resolveDevServerConfig,
} from "../../devServerConfig";

const DEFAULT_BACKEND_TARGET = ["http://localhost", "8000"].join(":");

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

  it("allows pointing the dev API proxy at a non-default backend", () => {
    expect(DEFAULT_API_PROXY_TARGET).toBe(DEFAULT_BACKEND_TARGET);
    expect(resolveApiProxyTarget({})).toBe(DEFAULT_BACKEND_TARGET);
    expect(
      resolveApiProxyTarget({
        VITE_API_PROXY_TARGET: " http://127.0.0.1:8001 ",
      }),
    ).toBe("http://127.0.0.1:8001");
  });

  it("allows all hosts only when explicitly requested", () => {
    expect(resolveDevServerConfig({}).allowedHosts).toEqual([
      "online.luminastudio.com.cn",
    ]);
    expect(
      resolveDevServerConfig({ VITE_ALLOW_ALL_HOSTS: "true" }).allowedHosts,
    ).toBe(true);
  });

  it("parses comma-separated allowed hosts from environment", () => {
    expect(
      resolveDevServerConfig({
        VITE_ALLOWED_HOSTS: "example.test, tunnel.example.test ",
      }).allowedHosts,
    ).toEqual([
      "online.luminastudio.com.cn",
      "example.test",
      "tunnel.example.test",
    ]);
  });
});
