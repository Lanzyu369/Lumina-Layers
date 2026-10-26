import { useI18n } from "../i18n/context";
import { HeaderMenuItem } from "./ui/HeaderMenuItem";

interface BugReportButtonProps {
  onClick: () => void;
}

/**
 * Header menu row that opens the bug report dialog.
 * 顶栏菜单中的问题反馈项，点击后打开反馈对话框。
 */
export function BugReportButton({ onClick }: BugReportButtonProps) {
  const { t } = useI18n();

  return (
    <HeaderMenuItem
      testId="bug-report-button"
      label={t("bug_report_button_label")}
      onSelect={onClick}
      icon={
        <svg
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
      }
    />
  );
}
