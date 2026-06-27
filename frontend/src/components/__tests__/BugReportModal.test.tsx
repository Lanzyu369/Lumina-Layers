import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../../api/feedback", () => ({
  relayBugReport: vi.fn(),
  submitBugReport: vi.fn(),
}));

vi.mock("../../utils/bugReportContext", () => ({
  collectBugReportContext: vi.fn(),
}));

import { relayBugReport, submitBugReport } from "../../api/feedback";
import { collectBugReportContext } from "../../utils/bugReportContext";
import { BugReportModal } from "../BugReportModal";

function createBugReportContext(
  overrides: Partial<ReturnType<typeof collectBugReportContext>> = {},
): ReturnType<typeof collectBugReportContext> {
  return {
    url: "http://localhost:5174/",
    user_agent: "vitest-agent",
    screen_width: 1280,
    screen_height: 720,
    device_pixel_ratio: 1,
    app_version: "2.0.0",
    language: "zh",
    theme: "light",
    active_tab: "converter",
    active_session_ids: {
      converter: "session-12345678",
      single_stage: null,
    },
    color_mode: "4-Color (RYBW)",
    lut_name: "Test LUT",
    source_version: "legacy",
    selected_native_brand_key: null,
    selected_native_db_names: [],
    selected_material_dir_names: [],
    material_layer_count: null,
    material_layer_height_mm: null,
    material_backing_material_dir_name: null,
    recent_client_logs: [],
    ...overrides,
  };
}

function createSensitiveBugReportContext(): ReturnType<typeof collectBugReportContext> {
  return createBugReportContext({
    active_final_artifact_ref: {
      session_id: "session-12345678",
      download_url: "/api/files/output-model",
      artifact_type: "3mf",
      disk_path: "/Users/min/private/final-output.3mf",
      source: "converter",
    },
    action_history: [
      {
        timestamp: 1_781_999_000_000,
        action_type: "api_error",
        snapshot: {
          color_mode: "4-Color (RYBW)",
          lut_name: "Test LUT",
          source_version: "legacy",
          selected_native_db_names: [],
          selected_material_dir_names: [],
          material_layer_count: null,
          material_layer_height_mm: null,
          material_backing_material_dir_name: null,
          active_tab: "converter",
          advanced_params: null,
        },
        error: {
          status_code: 500,
          path: "/api/converter/preview",
          error_message:
            "Request failed with status code 500 while reading /Users/min/private/source.png",
        },
      },
    ],
    recent_client_logs: [
      {
        timestamp: "2026-06-21T10:00:00.000Z",
        method: "error",
        label: "Request failed with status code 500",
        elapsed_ms: null,
        scope: "\\\\LUMINA-NAS\\private\\trace.log",
        details: {
          "Request failed with status code 500": "transport",
          api_path_transport_error:
            "Request failed with status code 500 at /api/files/output-model",
          error_message:
            "AxiosError: Request failed with status code 500 at /Users/min/private/source.png",
          home_path: "/home/min/private/source.png",
          private_tmp_path: "/private/tmp/lumina/private/source.png",
          tmp_path: "/tmp/lumina/private/source.png",
          var_path: "/var/folders/private/source.png",
          volume_path: "/Volumes/Work/private/source.png",
          mnt_path: "/mnt/lumina/private/source.png",
          opt_path: "/opt/lumina/private/source.png",
          error_stack:
            "Error: boom\n    at convert (/Users/min/CascadeProjects/Lumina-studio/frontend/src/api/client.ts:12:3)",
          path: "/Users/min/private/output.3mf",
          cache_url: "file:///Users/min/private/cache/model.glb",
          local_cache_url: "file://localhost/Users/min/private/cache/model.glb",
          unc_path: "\\\\LUMINA-NAS\\share\\secret.3mf",
          windows_file_url: "file:///C:/tmp/lumina/model.glb",
          windows_path: "C:\\Users\\min\\private\\output.3mf",
          windows_tmp_path: "C:\\tmp\\lumina\\output.3mf",
          windows_program_data_path: "C:/ProgramData/Lumina/output.3mf",
          windows_temp_path: "C:\\Windows\\Temp\\lumina\\output.3mf",
          status_code: 500,
        },
      },
    ],
  });
}

function expectManualFallbackTextRedacted(
  text: string,
  description?: string,
): void {
  if (description != null) {
    expect(text).toContain(`"description": "${description}"`);
  }
  expectNoSensitiveManualFallbackText(text);
  const statusScanText = description ? text.split(description).join("") : text;
  expect(statusScanText).not.toContain("Request failed with status code 500");
  expect(statusScanText).not.toMatch(/\b500\b/);
  expect(text).toContain("/api/files/output-model");
}

function expectNoSensitiveManualFallbackText(text: string): void {
  expect(text).not.toContain("/Users/min");
  expect(text).not.toContain("/home/min");
  expect(text).not.toContain("/private/tmp");
  expect(text).not.toContain("/tmp/lumina");
  expect(text).not.toContain("/var/folders");
  expect(text).not.toContain("/Volumes/Work");
  expect(text).not.toContain("/mnt/lumina");
  expect(text).not.toContain("/opt/lumina");
  expect(text).not.toContain("C:\\Users");
  expect(text).not.toContain("C:\\tmp");
  expect(text).not.toContain("C:/ProgramData");
  expect(text).not.toContain("C:\\Windows\\Temp");
  expect(text).not.toContain("file:///Users");
  expect(text).not.toContain("file://localhost/Users");
  expect(text).not.toContain("file:///C:");
  expect(text).not.toContain("\\\\LUMINA-NAS");
  expect(text).not.toContain("error_stack");
}

describe("BugReportModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: undefined,
    });
    vi.mocked(collectBugReportContext).mockReturnValue(createBugReportContext());
  });

  it("disables submit until description has content", () => {
    render(<BugReportModal open onClose={() => {}} />);

    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    expect(screen.getByRole("button", { name: "发送" })).not.toBeDisabled();
  });

  it("summarizes recent API client errors from the captured context", () => {
    vi.mocked(collectBugReportContext).mockReturnValueOnce(createBugReportContext({
      recent_client_logs: [
        {
          timestamp: "2026-06-18T15:00:00.000Z",
          method: "error",
          label: "api: request failed",
          elapsed_ms: null,
          scope: "api",
          phase: "request-failed",
          details: {
            status_code: 500,
            url: "/convert/generate",
            error_message: "The server hit an internal error.",
          },
        },
      ],
    }));

    render(<BugReportModal open onClose={() => {}} />);

    expect(screen.getByText("近期接口错误")).toBeInTheDocument();
    expect(
      screen.getByText("The server hit an internal error. · /convert/generate"),
    ).toBeInTheDocument();
  });

  it("replaces generic status-code API errors in the context summary", () => {
    vi.mocked(collectBugReportContext).mockReturnValueOnce(createBugReportContext({
      recent_client_logs: [
        {
          timestamp: "2026-06-18T15:00:00.000Z",
          method: "error",
          label: "api: request failed",
          elapsed_ms: null,
          scope: "api",
          phase: "request-failed",
          details: {
            status_code: 402,
            url: "/api/quota/check",
            error_message: "Request failed with status code 402",
          },
        },
      ],
    }));

    render(<BugReportModal open onClose={() => {}} />);

    expect(
      screen.getByText("此操作需要可用额度或付款状态后才能继续。 · /api/quota/check"),
    ).toBeInTheDocument();
    expect(screen.queryByText("402 · /api/quota/check")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Request failed with status code 402"),
    ).not.toBeInTheDocument();
  });

  it("submits the built payload and shows a success toast", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      emailed: false,
      email_status: "unconfigured",
      relay_available: false,
      dump_path: "feedback/abc12345.json",
    });

    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed after generate." },
    });
    fireEvent.change(screen.getByLabelText("你的邮箱（可选，方便我们回复你）"), {
      target: { value: "user@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(submitBugReport).toHaveBeenCalledWith({
        description: "Preview failed after generate.",
        user_email: "user@example.com",
        context: vi.mocked(collectBugReportContext).mock.results[0]?.value,
        screenshot_data_url: null,
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent("工单号：abc12345");
  });

  it("submits an attached screenshot data URL", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      emailed: false,
      email_status: "unconfigured",
      relay_available: false,
      dump_path: "feedback/abc12345.json",
    });
    const screenshot = new File(["fake png"], "preview.png", { type: "image/png" });

    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed after generate." },
    });
    fireEvent.change(screen.getByLabelText("截图（可选）"), {
      target: { files: [screenshot] },
    });

    expect(await screen.findByText("preview.png")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(submitBugReport).toHaveBeenCalledWith(
        expect.objectContaining({
          screenshot_data_url: expect.stringMatching(/^data:image\/png;base64,/),
        }),
      );
    });
  });

  it("rejects non-image screenshot attachments before submit", async () => {
    const textFile = new File(["not image"], "notes.txt", { type: "text/plain" });

    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("截图（可选）"), {
      target: { files: [textFile] },
    });

    expect(await screen.findByText("请选择图片文件作为截图。")).toBeInTheDocument();
    expect(submitBugReport).not.toHaveBeenCalled();
  });

  it("renders a persistent success view with ticket id and a manual close button when not emailed", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      emailed: false,
      email_status: "unconfigured",
      relay_available: false,
      dump_path: "feedback/20260429T162531Z_abc.json",
    });
    const onClose = vi.fn();

    render(<BugReportModal open onClose={onClose} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed after generate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByTestId("bug-report-ticket-id")).toHaveTextContent("abc12345");
    expect(screen.queryByTestId("bug-report-dump-path")).not.toBeInTheDocument();
    expect(screen.queryByText("feedback/20260429T162531Z_abc.json")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "本机未配置邮件，报告已保存到本地。请选择官方转发或手动发送。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "完成" })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("问题描述")).not.toBeInTheDocument();
  });

  it("does not show the local dump path when the report was emailed", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "deadbeef",
      emailed: true,
      email_status: "sent",
      relay_available: false,
      dump_path: "feedback/20260429T162531Z_deadbeef.json",
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByTestId("bug-report-ticket-id")).toHaveTextContent("deadbeef");
    expect(screen.getByText("报告已通过本机邮件发送给开发者。")).toBeInTheDocument();
    expect(screen.queryByTestId("bug-report-dump-path")).not.toBeInTheDocument();
    expect(
      screen.queryByText("feedback/20260429T162531Z_deadbeef.json"),
    ).not.toBeInTheDocument();
  });

  it("shows pending email status without relay prompt or manual fallback", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "pending123",
      emailed: false,
      email_status: "pending",
      relay_available: true,
      dump_path: "feedback/pending123.json",
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    const emailStatus = await screen.findByTestId("bug-report-email-status");
    expect(emailStatus).toHaveAttribute("data-status", "pending");
    expect(emailStatus).toHaveTextContent(
      "报告已收到，邮件正在后台发送。你可以关闭此对话框，结果会在日志中记录。",
    );
    expect(screen.queryByText(
      "本机邮件未成功发送。是否同意将这份反馈转发到 Lumina Studio 官方问题收集服务？",
    )).not.toBeInTheDocument();
    expect(screen.queryByTestId("bug-report-relay-send")).not.toBeInTheDocument();
    expect(screen.queryByTestId("bug-report-copy-submitted-report")).not.toBeInTheDocument();
  });

  it("asks for consent and relays through the official service when local email fails", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "relay123",
      emailed: false,
      email_status: "failed",
      relay_available: true,
      dump_path: "feedback/relay123.json",
    });
    vi.mocked(relayBugReport).mockResolvedValueOnce({ forwarded: true });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByText(
      "本机邮件未成功发送。是否同意将这份反馈转发到 Lumina Studio 官方问题收集服务？",
    )).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("bug-report-relay-send"));

    await waitFor(() => {
      expect(relayBugReport).toHaveBeenCalledWith(
        "relay123",
        expect.objectContaining({ description: "Crash after generate." }),
      );
    });
    expect(await screen.findByText("已转发到官方问题收集服务。")).toBeInTheDocument();
    expect(screen.queryByTestId("bug-report-copy-submitted-report")).not.toBeInTheDocument();
  });

  it("shows manual fallback after skipping official relay", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "relayskip",
      emailed: false,
      email_status: "unconfigured",
      relay_available: true,
      dump_path: "feedback/relayskip.json",
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByTestId("bug-report-relay-skip");

    fireEvent.click(screen.getByTestId("bug-report-relay-skip"));

    expect(await screen.findByText("未转发到官方服务，请使用下面的手动方式发送。")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-copy-submitted-report")).toBeInTheDocument();
  });

  it("redacts client log internals from the submitted manual fallback", async () => {
    const sensitiveContext = createSensitiveBugReportContext();
    vi.mocked(collectBugReportContext).mockReturnValue(sensitiveContext);
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "emailfail",
      emailed: false,
      email_status: "failed",
      relay_available: false,
      dump_path: "feedback/emailfail.json",
    });
    const writeText = vi.fn().mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    const fallbackText = await screen.findByTestId(
      "bug-report-submitted-fallback-text",
    );
    expectManualFallbackTextRedacted(
      fallbackText.textContent ?? "",
      "Crash after generate.",
    );
    expectManualFallbackTextRedacted(
      decodeURIComponent(
        screen.getByText("用默认邮箱发送").getAttribute("href") ?? "",
      ),
      "Crash after generate.",
    );
    expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ context: sensitiveContext }),
    );

    fireEvent.click(screen.getByTestId("bug-report-copy-submitted-report"));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expectManualFallbackTextRedacted(
      String(writeText.mock.calls[0]?.[0]),
      "Crash after generate.",
    );
  });

  it("redacts non-error HTTP status text from the submitted manual fallback", async () => {
    vi.mocked(collectBugReportContext).mockReturnValueOnce(createBugReportContext({
      recent_client_logs: [
        {
          timestamp: "2026-06-21T10:00:00.000Z",
          method: "error",
          label: "Request failed with status code 302",
          elapsed_ms: null,
          scope: "api",
          details: {
            status_code: 302,
            url: "/api/files/output-model",
            error_message: "Request failed with status code 302",
          },
        },
      ],
    }));
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "redirect",
      emailed: false,
      email_status: "failed",
      relay_available: false,
      dump_path: "feedback/redirect.json",
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview redirected after generate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    const fallbackText = await screen.findByTestId(
      "bug-report-submitted-fallback-text",
    );
    const text = fallbackText.textContent ?? "";
    expect(text).not.toContain("Request failed with status code 302");
    expect(text).not.toMatch(/\b302\b/);
    expect(text).toContain("Request failed. Please try again.");
  });

  it("keeps manual fallback actions visible when official relay fails", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "relayfail",
      emailed: false,
      email_status: "failed",
      relay_available: true,
      dump_path: "feedback/relayfail.json",
    });
    vi.mocked(relayBugReport).mockRejectedValueOnce(new Error("offline"));

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByTestId("bug-report-relay-send");

    fireEvent.click(screen.getByTestId("bug-report-relay-send"));

    expect(await screen.findByText("官方转发失败，请使用下面的手动方式发送。")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-copy-submitted-report")).toBeInTheDocument();
    expect(screen.getByText("用默认邮箱发送")).toHaveAttribute(
      "href",
      expect.stringContaining("mailto:"),
    );
    expect(screen.getByText("打开 QQ 邮箱")).toHaveAttribute("href", "https://mail.qq.com/");
  });

  it("invokes onClose only when the success Done button is clicked", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      emailed: false,
      email_status: "unconfigured",
      relay_available: false,
      dump_path: "feedback/abc12345.json",
    });
    const onClose = vi.fn();

    render(<BugReportModal open onClose={onClose} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await screen.findByTestId("bug-report-ticket-id");
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("copies the ticket id to the clipboard when the copy button is pressed", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      emailed: false,
      email_status: "unconfigured",
      relay_available: false,
      dump_path: "feedback/abc12345.json",
    });
    const writeText = vi.fn().mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByTestId("bug-report-ticket-id");

    fireEvent.click(screen.getByTestId("bug-report-copy-ticket"));

    expect(writeText).toHaveBeenCalledWith("abc12345");
    expect(await screen.findByText("已复制")).toBeInTheDocument();
  });

  it("falls back to selection copy when clipboard write fails", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      emailed: false,
      email_status: "unconfigured",
      relay_available: false,
      dump_path: "feedback/abc12345.json",
    });
    const writeText = vi.fn().mockRejectedValueOnce(new Error("not allowed"));
    const execCommand = vi.fn().mockReturnValueOnce(true);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByTestId("bug-report-ticket-id");

    fireEvent.click(screen.getByTestId("bug-report-copy-ticket"));

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("abc12345");
      expect(execCommand).toHaveBeenCalledWith("copy");
    });
    expect(await screen.findByText("已复制")).toBeInTheDocument();
  });

  it("shows a manual-copy warning when all copy strategies fail", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      emailed: false,
      email_status: "unconfigured",
      relay_available: false,
      dump_path: "feedback/abc12345.json",
    });
    const writeText = vi.fn().mockRejectedValueOnce(new Error("not allowed"));
    const execCommand = vi.fn().mockReturnValueOnce(false);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByTestId("bug-report-ticket-id");

    fireEvent.click(screen.getByTestId("bug-report-copy-ticket"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "自动复制失败，请手动选中工单号复制。",
    );
    expect(screen.getByTestId("bug-report-copy-ticket")).toHaveTextContent("复制");
  });

  it("resets the success view back to a fresh form when the modal is reopened", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      emailed: false,
      email_status: "unconfigured",
      relay_available: false,
      dump_path: "feedback/abc12345.json",
    });
    const onClose = vi.fn();

    const { rerender } = render(<BugReportModal open onClose={onClose} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByTestId("bug-report-ticket-id");

    rerender(<BugReportModal open={false} onClose={onClose} />);
    rerender(<BugReportModal open onClose={onClose} />);

    expect(screen.queryByTestId("bug-report-ticket-id")).not.toBeInTheDocument();
    expect(screen.getByLabelText("问题描述")).toBeInTheDocument();
    expect((screen.getByLabelText("问题描述") as HTMLTextAreaElement).value).toBe("");
  });

  it("keeps the modal open on submit failure and shows an error toast", async () => {
    vi.mocked(submitBugReport).mockRejectedValueOnce(new Error("boom"));
    const onClose = vi.fn();
    render(<BugReportModal open onClose={onClose} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("提交失败，请稍后再试。");
    expect(screen.getByText("如果多次失败，请复制下面的反馈内容，通过邮箱或即时通讯发给开发者。")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-fallback-text")).toHaveTextContent(
      '"description": "Preview failed"',
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("redacts client log internals from the failed-submit manual fallback", async () => {
    const sensitiveContext = createSensitiveBugReportContext();
    const userDescription = "I got Request failed with status code 500 after generate";
    vi.mocked(collectBugReportContext).mockReturnValue(sensitiveContext);
    vi.mocked(submitBugReport).mockRejectedValueOnce(new Error("boom"));
    const writeText = vi.fn().mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: userDescription },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    const fallbackText = await screen.findByTestId("bug-report-fallback-text");
    expectManualFallbackTextRedacted(fallbackText.textContent ?? "", userDescription);
    expectManualFallbackTextRedacted(
      decodeURIComponent(
        screen.getByText("用默认邮箱发送").getAttribute("href") ?? "",
      ),
      userDescription,
    );
    expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ context: sensitiveContext }),
    );

    fireEvent.click(screen.getByTestId("bug-report-copy-failed-report"));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expectManualFallbackTextRedacted(String(writeText.mock.calls[0]?.[0]), userDescription);
  });

  it("copies the failed report payload for manual fallback", async () => {
    vi.mocked(submitBugReport).mockRejectedValueOnce(new Error("boom"));
    const writeText = vi.fn().mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByTestId("bug-report-fallback-text");

    fireEvent.click(screen.getByTestId("bug-report-copy-failed-report"));

    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('"description": "Preview failed"'),
    );
    expect(await screen.findByText("反馈内容已复制")).toBeInTheDocument();
  });

  it("clears the failed report fallback when the description changes", async () => {
    vi.mocked(submitBugReport).mockRejectedValueOnce(new Error("boom"));
    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByTestId("bug-report-fallback-text");

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed again" },
    });

    expect(screen.queryByTestId("bug-report-fallback-text")).not.toBeInTheDocument();
  });

  it("shows inline validation when description is empty", async () => {
    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.blur(screen.getByLabelText("问题描述"));

    expect(await screen.findByText("请填写问题描述")).toBeInTheDocument();
    expect(submitBugReport).not.toHaveBeenCalled();
  });

  it("truncates overly long descriptions and shows a warning banner", async () => {
    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "x".repeat(10001) },
    });

    expect(
      (screen.getByLabelText("问题描述") as HTMLTextAreaElement).value,
    ).toHaveLength(10000);
    expect(await screen.findByRole("alert")).toHaveTextContent("问题描述已截断到 10000 个字符。");
  });

  it("expands the collected context disclosure", async () => {
    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.click(screen.getByText("已自动收集的信息（点击展开）"));

    // Full JSON is now serialized lazily on an idle callback; wait for the
    // text to appear.
    // JSON 现在通过 idle 回调按需序列化；等待文本出现。
    await screen.findByText(/"active_tab":\s*"converter"/, undefined, {
      timeout: 1500,
    });
  });

  it("redacts client log internals from the expanded context disclosure", async () => {
    vi.mocked(collectBugReportContext).mockReturnValue(
      createSensitiveBugReportContext(),
    );

    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.click(screen.getByText("已自动收集的信息（点击展开）"));

    await screen.findByText(/"active_tab":\s*"converter"/, undefined, {
      timeout: 1500,
    });
    expectManualFallbackTextRedacted(
      screen.getByTestId("bug-report-context-json").textContent ?? "",
    );
  });

  it("resets local form state when cancelled", () => {
    const onClose = vi.fn();
    const { rerender } = render(<BugReportModal open onClose={onClose} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(<BugReportModal open={false} onClose={onClose} />);
    rerender(<BugReportModal open onClose={onClose} />);
    expect((screen.getByLabelText("问题描述") as HTMLTextAreaElement).value).toBe("");
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<BugReportModal open onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps draft content when the backdrop is clicked", () => {
    const onClose = vi.fn();
    render(<BugReportModal open onClose={onClose} />);

    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    fireEvent.click(screen.getByTestId("bug-report-backdrop"));

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect((screen.getByLabelText("问题描述") as HTMLTextAreaElement).value).toBe(
      "Preview failed",
    );
  });
});
