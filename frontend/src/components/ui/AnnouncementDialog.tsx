import { useEffect } from "react";
import type { JSX } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../../i18n/context";
import type { AnnouncementEntry, LocalizedText } from "../../data/announcements";
import Button from "./Button";

export interface AnnouncementDialogProps {
  open: boolean;
  /**
   * 窗口内所有 entry（按 version 降序）。传入后会依次渲染多条；
   * 未传时回退到 `entry` 单条模式以兼容旧调用点/测试。
   */
  entries?: AnnouncementEntry[];
  /** 锚点 entry；用于版本徽章和 dismiss，也作为 entries 缺省时的单条数据源。 */
  entry: AnnouncementEntry | null;
  onClose: () => void;
  onDismissVersion: () => void;
}

export default function AnnouncementDialog({
  open,
  entries,
  entry,
  onClose,
  onDismissVersion,
}: AnnouncementDialogProps): JSX.Element | null {
  const { t, lang } = useI18n();
  const localize = (text: LocalizedText): string => (lang === "en" ? text.en : text.zh);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose]);

  const resolvedEntries: AnnouncementEntry[] =
    entries && entries.length > 0 ? entries : entry ? [entry] : [];

  if (!open || resolvedEntries.length === 0 || typeof document === "undefined") {
    return null;
  }

  // 徽章和 dismiss 语义永远绑定在锚点 entry 上；锚点优先取显式传入的 entry，
  // 再退回到 entries[0]（已按 version 降序）。
  const anchorEntry = entry ?? resolvedEntries[0];
  const versionLabel = `${t("announcement_version_label")}: ${anchorEntry.version}`;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("announcement_title")}
        className="relative mx-4 flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border shadow-2xl"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-700">
          <div className="flex min-w-0 items-center gap-3">
            <h2 className="truncate text-base font-semibold text-slate-800 dark:text-slate-100">
              {t("announcement_title")}
            </h2>
            <span
              className="inline-flex shrink-0 items-center rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-700 dark:bg-sky-950/40 dark:text-sky-300"
              aria-label={versionLabel}
              title={versionLabel}
            >
              {anchorEntry.version}
            </span>
          </div>
        </div>

          {resolvedEntries.map((currentEntry, entryIndex) => (
            <article
              key={currentEntry.version}
              className={entryIndex === 0 ? "mt-0" : "mt-6"}
              data-announcement-entry={currentEntry.version}
            >
              <div className="flex items-center gap-2">
                <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">
                  {localize(currentEntry.title)}
                </h3>
                {/* 多条时给每个子段也带版本小徽章，便于用户区分当天 / 昨天 / 前天 */}
                {resolvedEntries.length > 1 ? (
                  <span
                    className="inline-flex shrink-0 items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                    aria-label={`${t("announcement_version_label")}: ${currentEntry.version}`}
                  >
                    {currentEntry.version}
                  </span>
                ) : null}
              </div>

              {currentEntry.sections.map((section, sectionIndex) => {
                const categoryText = localize(section.category);
                return (
                  <section
                    key={`${currentEntry.version}-${categoryText}-${sectionIndex}`}
                    className={sectionIndex === 0 ? "mt-2" : "mt-4"}
                  >
                    <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                      {categoryText}
                    </p>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                      {section.items.map((item, itemIndex) => (
                        <li
                          key={`${currentEntry.version}-${categoryText}-${itemIndex}`}
                          className="text-sm leading-6 text-slate-600 dark:text-slate-300"
                        >
                          {localize(item)}
                        </li>
                      ))}
                    </ul>
                  </section>
                );
              })}
            </article>
          ))}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-700">
          <Button
            label={t("announcement_close_label")}
            variant="secondary"
            onClick={onClose}
            className="px-4"
          />
          <Button
            label={t("announcement_mark_read")}
            variant="secondary"
            onClick={onDismissVersion}
            className="px-4"
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}
