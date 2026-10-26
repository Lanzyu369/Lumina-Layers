import { describe, expect, it, vi } from "vitest";

import { retryAsync } from "../utils/retryAsync";

describe("retryAsync", () => {
  it("retries transient failures until the operation succeeds", async () => {
    const operation = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new Error("backend warming up"))
      .mockRejectedValueOnce(new Error("backend warming up"))
      .mockResolvedValue("ok");
    const sleep = vi.fn<(delayMs: number) => Promise<void>>().mockResolvedValue();

    await expect(
      retryAsync(operation, {
        attempts: 3,
        delayMs: 250,
        sleep,
      }),
    ).resolves.toBe("ok");

    expect(operation).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenNthCalledWith(1, 250);
    expect(sleep).toHaveBeenNthCalledWith(2, 250);
  });

  it("rethrows the last error after exhausting all attempts", async () => {
    const error = new Error("still failing");
    const operation = vi
      .fn<() => Promise<string>>()
      .mockRejectedValue(error);
    const sleep = vi.fn<(delayMs: number) => Promise<void>>().mockResolvedValue();

    await expect(
      retryAsync(operation, {
        attempts: 2,
        delayMs: 500,
        sleep,
      }),
    ).rejects.toThrow("still failing");

    expect(operation).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenCalledTimes(1);
    expect(sleep).toHaveBeenCalledWith(500);
  });
});
