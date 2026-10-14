import { useI18n } from "../i18n/context";

export default function LuminaBoxProgressBar({ current, total, label }: {
  current: number;
  total: number;
  label?: string;
}) {
  const { t } = useI18n();
  const percentage = total > 0 ? (current / total) * 100 : 0;

  return (
    <div className="space-y-2" data-testid="lumina-box-progress-bar">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-slate-700 dark:text-slate-300">
          {label || t("lumina_box_progress_bar_label")}
        </span>
        <span className="tabular-nums text-slate-600 dark:text-slate-400">
          {current} / {total}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <div
          className="h-full rounded-full bg-blue-500 transition-all duration-300 ease-out"
          style={{ width: `${percentage}%` }}
          role="progressbar"
          aria-valuenow={current}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-label={`${label || t("lumina_box_progress_bar_label")}: ${current} / ${total}`}
        />
      </div>
    </div>
  );
}
