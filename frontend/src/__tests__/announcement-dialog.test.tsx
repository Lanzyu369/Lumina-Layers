import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { I18nProvider } from "../i18n/context";
import AnnouncementDialog from "../components/ui/AnnouncementDialog";
import type { AnnouncementEntry } from "../data/announcements";

function createEntry(
  overrides: Partial<AnnouncementEntry> = {},
): AnnouncementEntry {
  return {
    version: "2026-04-19",
    title: { zh: "t1", en: "t1-en" },
    sections: [
      {
        category: { zh: "新", en: "New" },
        items: [
          { zh: "a", en: "a-en" },
          { zh: "b", en: "b-en" },
        ],
      },
    ],
    ...overrides,
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

  it("传入多条 entries 时应渲染每一条的标题、段落和条目", () => {
    const entries: AnnouncementEntry[] = [
      createEntry({ version: "2026-05-10", title: { zh: "新标题", en: "New Title" } }),
      createEntry({
        version: "2026-05-09",
        title: { zh: "昨日标题", en: "Yesterday" },
        sections: [
          {
            category: { zh: "稳定性", en: "Stability" },
            items: [{ zh: "昨日条目", en: "Yesterday item" }],
          },
        ],
      }),
    ];

    renderDialog({ entries, entry: entries[0] });

    expect(screen.getByText("新标题")).toBeInTheDocument();
    expect(screen.getByText("昨日标题")).toBeInTheDocument();
    // 版本徽章里依然显示锚点（最新）version；此外 5-09 会作为子段内副徽章出现
    expect(screen.getAllByText("2026-05-10").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("2026-05-09")).toBeInTheDocument();
    // 两条 entry 一共 2 个 section 各 1 个 item + 第一条主 section 还有 a/b 两项
    expect(screen.getAllByRole("listitem").length).toBeGreaterThanOrEqual(3);
  });

  it("entries 空数组且 entry 为 null 时返回 null", () => {
    render(
      <I18nProvider>
        <AnnouncementDialog
          open
          entries={[]}
          entry={null}
          onClose={vi.fn()}
          onDismissVersion={vi.fn()}
        />
      </I18nProvider>,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
