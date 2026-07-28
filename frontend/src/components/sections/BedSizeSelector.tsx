import { useConverterStore } from "../../stores/converter";
import { useWidgetStore } from "../../stores/widgetStore";
import { useI18n } from "../../i18n/context";
import HelpDot from "../ui/HelpDot";

export default function BedSizeSelector() {
  const { t } = useI18n();
  const bed_label = useConverterStore((s) => s.bed_label);
  const bedSizes = useConverterStore((s) => s.bedSizes);
  const setActiveTab = useWidgetStore((s) => s.setActiveTab);
  const selectedBed = bedSizes.find((bed) => bed.label === bed_label);
  const dimensions = selectedBed
    ? `${selectedBed.width_mm}×${selectedBed.height_mm} ${t('common_unit_mm')}`
    : null;
  const bedSummary =
    dimensions && selectedBed?.printer_id
      ? `${bed_label} · ${dimensions}`
      : bed_label;

  return (
    <div className="flex items-center justify-between rounded-2xl border border-slate-200/80 bg-slate-100/70 px-3 py-2 dark:border-slate-700/60 dark:bg-slate-900/50">
      <span className="flex shrink-0 items-center gap-1.5 text-[clamp(0.65rem,0.85vw,0.75rem)] font-medium text-slate-500 dark:text-slate-400">
        {t("bed_size_label")}
        <HelpDot
          title={t("bed_size_label")}
          description={t("bed_size_hint")}
          ariaLabel={t("bed_size_hint_aria")}
          placement="left"
        />
      </span>
      <span className="ml-3 flex min-w-0 items-center gap-2">
        <span className="truncate text-[clamp(0.65rem,0.85vw,0.75rem)] tabular-nums text-slate-700 dark:text-slate-200">
          {bedSummary}
        </span>
        <button
          type="button"
          onClick={() => setActiveTab("settings")}
          aria-label={t("bed_size_change_aria")}
          className="shrink-0 rounded-full px-2 py-1 text-[clamp(0.65rem,0.85vw,0.75rem)] font-medium text-blue-600 transition-colors hover:bg-slate-200/70 hover:text-blue-700 focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] dark:text-blue-400 dark:hover:bg-slate-800/70 dark:hover:text-blue-300"
        >
          {t("bed_size_change")}
        </button>
      </span>
    </div>
  );
}
