import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../../api/feedback", () => ({
  submitBugReport: vi.fn(),
}));

vi.mock("../../utils/bugReportContext", () => ({
  collectBugReportContext: vi.fn(),
}));

import { submitBugReport } from "../../api/feedback";
import { collectBugReportContext } from "../../utils/bugReportContext";
import { BugReportModal } from "../BugReportModal";

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
    vi.mocked(collectBugReportContext).mockReturnValue({
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
    });
  });

  it("disables submit until description has content", () => {
    render(<BugReportModal open onClose={() => {}} />);

    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed" },
    });
    expect(screen.getByRole("button", { name: "发送" })).not.toBeDisabled();
  });

  it("submits the built payload and shows a success toast", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      emailed: false,
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

  it("renders a persistent success view with ticket id, dump path, and a manual close button when not emailed", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      emailed: false,
      dump_path: "feedback/20260429T162531Z_abc.json",
    });
    const onClose = vi.fn();

    render(<BugReportModal open onClose={onClose} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Preview failed after generate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByTestId("bug-report-ticket-id")).toHaveTextContent("abc12345");
    expect(screen.getByTestId("bug-report-dump-path")).toHaveTextContent(
      "feedback/20260429T162531Z_abc.json",
    );
    expect(
      screen.getByText(
        "邮件未配置，报告已保存到本地。请把工单号告知开发者，便于查找原始记录。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "完成" })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("问题描述")).not.toBeInTheDocument();
  });

  it("hides the dump path and shows the emailed message when the report was emailed", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "deadbeef",
      emailed: true,
      dump_path: "feedback/20260429T162531Z_deadbeef.json",
    });

    render(<BugReportModal open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("问题描述"), {
      target: { value: "Crash after generate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByTestId("bug-report-ticket-id")).toHaveTextContent("deadbeef");
    expect(screen.getByText("邮件投递已配置，报告已保存并加入发送队列。")).toBeInTheDocument();
    expect(screen.queryByTestId("bug-report-dump-path")).not.toBeInTheDocument();
  });

  it("invokes onClose only when the success Done button is clicked", async () => {
    vi.mocked(submitBugReport).mockResolvedValueOnce({
      ticket_id: "abc12345",
      emailed: false,
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
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
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

  it("expands the collected context disclosure", () => {
    render(<BugReportModal open onClose={() => {}} />);

    fireEvent.click(screen.getByText("已自动收集的信息（点击展开）"));

    expect(screen.getByTestId("bug-report-context-json")).toHaveTextContent(
      '"active_tab": "converter"',
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

  it("closes on Escape and backdrop click", () => {
    const onClose = vi.fn();
    render(<BugReportModal open onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByTestId("bug-report-backdrop"));

    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
