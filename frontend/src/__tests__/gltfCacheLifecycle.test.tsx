import { StrictMode, type PropsWithChildren } from "react";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  GLTF_CACHE_RELEASE_DELAY_MS,
  resetGltfCacheLifecycleForTests,
  useGltfCacheLifecycle,
} from "../components/useGltfCacheLifecycle";

function StrictModeWrapper({ children }: PropsWithChildren) {
  return <StrictMode>{children}</StrictMode>;
}

describe("useGltfCacheLifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetGltfCacheLifecycleForTests();
  });

  afterEach(() => {
    act(() => {
      vi.runOnlyPendingTimers();
    });
    resetGltfCacheLifecycleForTests();
    vi.useRealTimers();
  });

  it("preserves the same URL across cross-instance unmount and remount", () => {
    const clear = vi.fn();
    const first = renderHook(({ url }) => useGltfCacheLifecycle(url, clear), {
      initialProps: { url: "/api/files/preview-a" },
      wrapper: StrictModeWrapper,
    });

    first.unmount();

    const second = renderHook(({ url }) => useGltfCacheLifecycle(url, clear), {
      initialProps: { url: "/api/files/preview-a" },
      wrapper: StrictModeWrapper,
    });

    act(() => {
      vi.advanceTimersByTime(GLTF_CACHE_RELEASE_DELAY_MS + 1);
    });

    expect(clear).not.toHaveBeenCalled();
    second.unmount();
  });

  it("eventually clears a stale URL after cross-instance replacement with a different URL", () => {
    const clear = vi.fn();
    const first = renderHook(({ url }) => useGltfCacheLifecycle(url, clear), {
      initialProps: { url: "/api/files/preview-a" },
      wrapper: StrictModeWrapper,
    });

    first.unmount();

    const second = renderHook(({ url }) => useGltfCacheLifecycle(url, clear), {
      initialProps: { url: "/api/files/preview-b" },
      wrapper: StrictModeWrapper,
    });

    expect(clear).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(GLTF_CACHE_RELEASE_DELAY_MS + 1);
    });

    expect(clear).toHaveBeenCalledTimes(1);
    expect(clear).toHaveBeenCalledWith("/api/files/preview-a");
    expect(clear).not.toHaveBeenCalledWith("/api/files/preview-b");
    second.unmount();
  });

  it("clears the previous URL exactly once when the same instance switches models", () => {
    const clear = vi.fn();
    const view = renderHook(({ url }) => useGltfCacheLifecycle(url, clear), {
      initialProps: { url: "/api/files/preview-a" },
      wrapper: StrictModeWrapper,
    });

    view.rerender({ url: "/api/files/preview-b" });

    expect(clear).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(GLTF_CACHE_RELEASE_DELAY_MS + 1);
    });

    expect(clear).toHaveBeenCalledTimes(1);
    expect(clear).toHaveBeenCalledWith("/api/files/preview-a");
    view.unmount();
  });
});
