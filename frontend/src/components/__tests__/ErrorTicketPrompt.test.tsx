import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ErrorTicketPrompt } from "../ErrorTicketPrompt";
import { buildErrorTicketDescription } from "../../utils/errorTicketDescription";
import { translations } from "../../i18n/translations";
import type { ErrorTicketPromptInfo } from "../../stores/errorTicketPromptStore";

const zh = (key: string) => translations[key]?.zh ?? key;

const API_ERROR: ErrorTicketPromptInfo = {
  kind: "api",
  message: "预览生成失败",
  statusCode: 500,
  path: "/api/convert/preview",
  requestId: "req-42",
  occurredAt: Date.UTC(2026, 9, 7, 8, 30, 0),
};

describe("ErrorTicketPrompt", () => {
  it("renders nothing without a pending error", () => {
    render(
      <ErrorTicketPrompt info={null} onReport={vi.fn()} onDismiss={vi.fn()} onSuppress={vi.fn()} />,
    );

    expect(screen.queryByTestId("error-ticket-prompt")).toBeNull();
  });

  it("shows the error and routes each choice to its handler", () => {
    const onReport = vi.fn();
    const onDismiss = vi.fn();
    const onSuppress = vi.fn();
    render(
      <ErrorTicketPrompt
        info={API_ERROR}
        onReport={onReport}
        onDismiss={onDismiss}
        onSuppress={onSuppress}
      />,
    );

    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("出现了一个错误")).toBeInTheDocument();
    expect(screen.getByTestId("error-ticket-prompt-message")).toHaveTextContent(
      "HTTP 500 · 预览生成失败",
    );

    fireEvent.click(screen.getByRole("button", { name: "提交工单" }));
    fireEvent.click(screen.getByRole("button", { name: "暂不" }));
    fireEvent.click(screen.getByTestId("error-ticket-prompt-close"));
    fireEvent.click(screen.getByTestId("error-ticket-prompt-suppress"));

    expect(onReport).toHaveBeenCalledTimes(1);
    expect(onDismiss).toHaveBeenCalledTimes(2);
    expect(onSuppress).toHaveBeenCalledTimes(1);
  });

  it("truncates very long messages in the card", () => {
    render(
      <ErrorTicketPrompt
        info={{ ...API_ERROR, statusCode: undefined, message: "x".repeat(400) }}
        onReport={vi.fn()}
        onDismiss={vi.fn()}
        onSuppress={vi.fn()}
      />,
    );

    const text = screen.getByTestId("error-ticket-prompt-message").textContent ?? "";
    expect(text.length).toBeLessThan(200);
    expect(text.endsWith("…")).toBe(true);
  });
});

describe("buildErrorTicketDescription", () => {
  it("includes every captured API error field", () => {
    const text = buildErrorTicketDescription(API_ERROR, zh);

    expect(text).toContain(zh("error_ticket_preset_intro"));
    expect(text).toContain("类型: 接口错误 (HTTP 500)");
    expect(text).toContain("接口: /api/convert/preview");
    expect(text).toContain("请求 ID: req-42");
    expect(text).toContain("错误信息: 预览生成失败");
    expect(text).toContain("2026-10-07T08:30:00.000Z");
  });

  it("omits API-only fields for client runtime errors", () => {
    const text = buildErrorTicketDescription(
      { kind: "client", message: "TypeError: boom", occurredAt: 0 },
      zh,
    );

    expect(text).toContain("类型: 前端运行错误");
    expect(text).not.toContain("接口:");
    expect(text).not.toContain("请求 ID:");
  });
});
