import { useI18n } from "../i18n/context";

export default function LuminaBoxStepIndicator({ current, total, label }: {
  current: number;
  total: number;
  label: string;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-3" role="status" data-testid="lumina-box-step-indicator">
      <div className="flex items-center gap-2">
        {Array.from({ length: total }, (_, index) => {
          const step = index + 1;
          const isComplete = step < current;
          const isCurrent = step === current;
          return (
            <div
              key={step}
              className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium transition-colors ${
                isComplete
                  ? "bg-green-500 text-white"
                  : isCurrent
                    ? "bg-blue-500 text-white"
                    : "bg-slate-200 text-slate-500 dark:bg-slate-700 dark:text-slate-400"
              }`}
              aria-label={`${t("lumina_box_step_indicator").replace("{current}", String(step)).replace("{total}", String(total))}${isComplete ? ` - ${t("lumina_box_measurement_complete_indicator")}` : ""}`}
            >
              {step}
            </div>
          );
        })}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{label}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {t("lumina_box_step_indicator").replace("{current}", String(current)).replace("{total}", String(total))}
        </p>
      </div>
    </div>
  );
}
