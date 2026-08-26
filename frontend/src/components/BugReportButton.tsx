import { useI18n } from "../i18n/context";
import { HEADER_ICON_BUTTON_CLASS } from "./ui/headerControls";
import { HeaderTooltip } from "./ui/HeaderTooltip";

interface BugReportButtonProps {
  onClick: () => void;
}

export function BugReportButton({ onClick }: BugReportButtonProps) {
  const { t } = useI18n();

  return (
    <HeaderTooltip label={t("bug_report_button_tooltip")}>
      <button
        type="button"
        data-testid="bug-report-button"
        aria-label={t("bug_report_button_label")}
        onClick={onClick}
        className={HEADER_ICON_BUTTON_CLASS}
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
    </HeaderTooltip>
  );
}
