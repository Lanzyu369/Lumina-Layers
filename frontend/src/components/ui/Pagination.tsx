import { useState } from "react";
import type { KeyboardEvent } from "react";

import { useI18n } from "../../i18n/context";
import { tRuntime } from "../../i18n/runtime";
import { ChevronLeft, ChevronRight } from "./icons";
import { cx } from "./panelPrimitives";
import { buildPaginationItems, clampPage } from "./paginationModel";

interface PaginationProps {
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  disabled?: boolean;
  /** Show the "go to page" input; useful once there are many pages. */
  showJump?: boolean;
  className?: string;
  "data-testid"?: string;
}

const pageButtonClass =
  "inline-flex h-9 min-w-9 items-center justify-center rounded-lg border px-2.5 text-sm font-medium tabular-nums transition focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45";
const idlePageButtonClass =
  "border-slate-200/80 bg-[var(--surface-panel)] text-slate-600 hover:border-slate-300 hover:text-slate-900 dark:border-slate-700/80 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-slate-50";
const activePageButtonClass =
  "border-blue-400 bg-blue-50 text-blue-700 dark:border-blue-400/70 dark:bg-blue-500/15 dark:text-blue-200";

/**
 * Page navigation: previous/next, compact page numbers, optional jump input.
 * 分页导航：上一页/下一页、紧凑页码、可选跳页输入。
 */
export default function Pagination({
  page,
  pageCount,
  onPageChange,
  disabled = false,
  showJump = false,
  className,
  "data-testid": testId,
}: PaginationProps) {
  const { t } = useI18n();
  const [jumpDraft, setJumpDraft] = useState("");
  const current = clampPage(page, pageCount);

  const goTo = (target: number) => {
    const next = clampPage(target, pageCount);
    if (!disabled && next !== current) {
      onPageChange(next);
    }
  };

  const commitJump = () => {
    const parsed = Number.parseInt(jumpDraft, 10);
    setJumpDraft("");
    if (Number.isFinite(parsed)) {
      goTo(parsed);
    }
  };

  const handleJumpKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commitJump();
    }
  };

  return (
    <nav
      aria-label={t("common_pagination_label")}
      data-testid={testId}
      className={cx("flex flex-wrap items-center justify-center gap-1.5", className)}
    >
      <button
        type="button"
        className={cx(pageButtonClass, idlePageButtonClass, "gap-1 px-3")}
        onClick={() => goTo(current - 1)}
        disabled={disabled || current <= 1}
      >
        <ChevronLeft />
        <span>{t("common_pagination_prev")}</span>
      </button>
      {buildPaginationItems(current, pageCount).map((item) => (
        typeof item === "number" ? (
          <button
            key={item}
            type="button"
            aria-label={tRuntime("common_pagination_page", { page: item })}
            aria-current={item === current ? "page" : undefined}
            className={cx(
              pageButtonClass,
              item === current ? activePageButtonClass : idlePageButtonClass,
            )}
            onClick={() => goTo(item)}
            disabled={disabled}
          >
            {item}
          </button>
        ) : (
          <span
            key={item}
            aria-hidden="true"
            className="inline-flex h-9 min-w-6 items-center justify-center text-sm text-slate-400 dark:text-slate-500"
          >
            …
          </span>
        )
      ))}
      <button
        type="button"
        className={cx(pageButtonClass, idlePageButtonClass, "gap-1 px-3")}
        onClick={() => goTo(current + 1)}
        disabled={disabled || current >= pageCount}
      >
        <span>{t("common_pagination_next")}</span>
        <ChevronRight />
      </button>
      {showJump ? (
        <label className="ml-1 inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
          <span>{t("common_pagination_jump")}</span>
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={pageCount}
            value={jumpDraft}
            disabled={disabled}
            onChange={(event) => setJumpDraft(event.target.value)}
            onKeyDown={handleJumpKeyDown}
            onBlur={commitJump}
            placeholder={String(current)}
            className="h-9 w-16 rounded-lg border border-slate-200/80 bg-[var(--surface-panel)] px-2 text-center text-sm tabular-nums text-slate-800 outline-none focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] disabled:opacity-45 dark:border-slate-700/80 dark:text-slate-100"
          />
          <span>{tRuntime("common_pagination_total_pages", { count: pageCount })}</span>
        </label>
      ) : null}
    </nav>
  );
}
