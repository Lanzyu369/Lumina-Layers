import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  isTicketWorthyApiError,
  isTicketWorthyClientError,
  useErrorTicketPromptStore,
} from "../errorTicketPromptStore";

const store = () => useErrorTicketPromptStore.getState();

function report500(path = "/api/convert/preview") {
  store().reportApiError({
    statusCode: 500,
    path,
    requestId: "req-1",
    message: "Internal error",
  });
}

describe("errorTicketPromptStore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-07T00:00:00Z"));
    store()._resetForTests();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("prompts for a 5xx API failure with its details", () => {
    report500();

    expect(store().pending).toMatchObject({
      kind: "api",
      statusCode: 500,
      path: "/api/convert/preview",
      requestId: "req-1",
      message: "Internal error",
    });
  });

  it("does not prompt for 4xx validation errors or missing status codes", () => {
    store().reportApiError({ statusCode: 422, path: "/api/x", message: "bad" });
    store().reportApiError({ statusCode: null, path: "/api/x", message: "offline" });

    expect(store().pending).toBeNull();
  });

  it("ignores failures of the feedback pipeline itself", () => {
    report500("/api/feedback/bug-report");
    report500("/api/client-log");

    expect(store().pending).toBeNull();
  });

  it("keeps the first error while a prompt is already showing", () => {
    report500("/api/first");
    report500("/api/second");

    expect(store().pending?.path).toBe("/api/first");
  });

  it("prompts again immediately once the previous card is closed", () => {
    report500("/api/first");
    store().dismiss();

    report500("/api/second");
    expect(store().pending?.path).toBe("/api/second");
  });

  it("stops prompting for the rest of the session after opting out", () => {
    report500();
    store().suppressForSession();
    vi.advanceTimersByTime(10 * 60_000);
    report500();

    expect(store().pending).toBeNull();
    expect(store().suppressed).toBe(true);
  });

  it("prompts for real client errors but ignores browser noise", () => {
    store().reportClientError("ResizeObserver loop completed with undelivered notifications.");
    store().reportClientError("Script error.");
    store().reportClientError("   ");
    expect(store().pending).toBeNull();

    store().reportClientError("Cannot read properties of undefined (reading 'x')");
    expect(store().pending).toMatchObject({
      kind: "client",
      message: "Cannot read properties of undefined (reading 'x')",
    });
  });

  it("exposes pure classifiers for API and client errors", () => {
    expect(isTicketWorthyApiError(503, "/api/generate")).toBe(true);
    expect(isTicketWorthyApiError(404, "/api/generate")).toBe(false);
    expect(isTicketWorthyApiError(500, null)).toBe(true);
    expect(isTicketWorthyClientError("TypeError: boom")).toBe(true);
    expect(isTicketWorthyClientError("")).toBe(false);
  });
});
