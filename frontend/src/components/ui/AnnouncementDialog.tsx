import { useEffect } from "react";
import type { JSX } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../../i18n/context";
import type { AnnouncementEntry, LocalizedText } from "../../data/announcements";
import Button from "./Button";

export interface AnnouncementDialogProps {
  open: boolean;
  entry: AnnouncementEntry | null;
  onClose: () => void;
  onDismissVersion: () => void;
}

export default function AnnouncementDialog({
  open,
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

  if (!open || !entry || typeof document === "undefined") {
    return null;
  }

  const versionLabel = `${t("announcement_version_label")}: ${entry.version}`;

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
              {entry.version}
            </span>
          </div>
          <button
            type="button"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
            onClick={onClose}
            aria-label={t("announcement_close")}
          >
            ✕
          </button>
        </div>

        <div className="max-h-[70vh] flex-1 overflow-y-auto px-5 py-4">
          <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">
            {localize(entry.title)}
          </h3>

          {entry.sections.map((section, index) => {
            const categoryText = localize(section.category);
            return (
              <section
                key={`${categoryText}-${index}`}
                className={index === 0 ? "mt-0" : "mt-4"}
              >
                <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                  {categoryText}
                </p>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {section.items.map((item, itemIndex) => (
                    <li
                      key={`${categoryText}-${itemIndex}`}
                      className="text-sm leading-6 text-slate-600 dark:text-slate-300"
                    >
                      {localize(item)}
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
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
            variant="primary"
            onClick={onDismissVersion}
            className="px-4"
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}
