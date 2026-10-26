/**
 * Tests for ``useReproMode``.
 *
 * Verifies that the ``?repro_session=<ticket>`` URL query flips the hook
 * into reproduction mode without triggering any store side effects.
 */

import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useReproMode } from "../hooks/useReproMode";

describe("useReproMode", () => {
  const originalHref = window.location.href;

  beforeEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, href: "http://localhost:5174/" },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, href: originalHref },
    });
  });

  it("returns disabled when no query param is present", () => {
    const { result } = renderHook(() => useReproMode());
    expect(result.current.enabled).toBe(false);
    expect(result.current.ticketId).toBeNull();
  });

  it("detects repro_session query param", () => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        ...window.location,
        href: "http://localhost:5174/?repro_session=LUM-20260511-001",
      },
    });
    const { result } = renderHook(() => useReproMode());
    expect(result.current.enabled).toBe(true);
    expect(result.current.ticketId).toBe("LUM-20260511-001");
  });

  it("survives malformed URL without throwing", () => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, href: "" },
    });
    expect(() => renderHook(() => useReproMode())).not.toThrow();
  });
});
