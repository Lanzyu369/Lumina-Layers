import { useI18n } from "../i18n/context";

interface BugReportButtonProps {
  onClick: () => void;
}

export function BugReportButton({ onClick }: BugReportButtonProps) {
  const { t } = useI18n();

  return (
    <button
      type="button"
      data-testid="bug-report-button"
      aria-label={t("bug_report_button_label")}
      title={t("bug_report_button_tooltip")}
      onClick={onClick}
      className="panel-section-muted inline-flex h-9 w-9 items-center justify-center rounded-lg p-0 transition-opacity duration-200 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
      style={{ color: "var(--surface-text-muted)" }}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M9.5 6.5h5" />
        <path d="M8 10.5h8" />
        <path d="M10 14.5h4" />
        <path d="M7 4.5h10l2 3v5c0 3.866-3.134 7-7 7s-7-3.134-7-7v-5l2-3Z" />
        <path d="M9 4.5V3h6v1.5" />
      </svg>
    </button>
  );
}
