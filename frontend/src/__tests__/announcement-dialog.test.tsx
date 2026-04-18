import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { I18nProvider } from "../i18n/context";
import AnnouncementDialog from "../components/ui/AnnouncementDialog";
import type { AnnouncementEntry } from "../data/announcements";

function createEntry(): AnnouncementEntry {
  return {
    version: "2026-04-19",
    title: "t1",
    sections: [
      {
        category: "🆕 新",
        items: ["a", "b"],
      },
    ],
  };
}

function renderDialog(
  props: Partial<ComponentProps<typeof AnnouncementDialog>> = {},
) {
  const onClose = vi.fn();
  const onDismissVersion = vi.fn();

  render(
    <I18nProvider>
      <AnnouncementDialog
        open
        entry={createEntry()}
        onClose={onClose}
        onDismissVersion={onDismissVersion}
        {...props}
      />
    </I18nProvider>,
  );

  return { onClose, onDismissVersion };
}

describe("AnnouncementDialog", () => {
  it("open=false 时返回 null", () => {
    renderDialog({ open: false });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("open=true 时渲染标题、版本徽章和列表项", () => {
    renderDialog();

    expect(screen.getByText("版本更新")).toBeInTheDocument();
    expect(screen.getByText("t1")).toBeInTheDocument();
    expect(screen.getByText("2026-04-19")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("点击 scrim 调用 onClose 且不调用 onDismissVersion", () => {
    const { onClose, onDismissVersion } = renderDialog();

    const dialog = screen.getByRole("dialog");
    const scrim = dialog.parentElement;
    if (!scrim) {
      throw new Error("Expected dialog scrim container");
    }

    fireEvent.click(scrim);

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onDismissVersion).not.toHaveBeenCalled();
  });

  it("按 Escape 调用 onClose", () => {
    const { onClose } = renderDialog();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("按钮分别调用 onDismissVersion 与 onClose", () => {
    const { onClose, onDismissVersion } = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "知道了" }));
    fireEvent.click(screen.getByRole("button", { name: "稍后再看" }));

    expect(onDismissVersion).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
