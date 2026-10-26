import { useI18n } from "../i18n/context";
import { StatusBanner } from "../components/ui/panelPrimitives";
import type {
  WorkshopColorLibrary,
  WorkshopRecipeSource,
} from "./contracts";
import { hasWorkshopHandoffColorLibraryChanged } from "./handoffMetadata";

interface WorkshopSourceBannerProps {
  source: WorkshopRecipeSource;
  colorLibrary: WorkshopColorLibrary | null;
  colorLibrarySelectionKey?: string;
}

export default function WorkshopSourceBanner({
  source,
  colorLibrary,
  colorLibrarySelectionKey,
}: WorkshopSourceBannerProps) {
  const { t } = useI18n();
  const moduleLabel = t("workshop_source_banner_module_value")
    .replace("{id}", source.moduleId)
    .replace("{version}", source.moduleVersion);
  const colorLibraryChanged =
    hasWorkshopHandoffColorLibraryChanged(
      source,
      colorLibrary,
      colorLibrarySelectionKey,
    );

  return (
    <StatusBanner
      tone="info"
      aria-label={t("workshop_source_banner_title")}
    >
      <div className="text-xs font-semibold text-slate-800 dark:text-slate-100">
        {t("workshop_source_banner_title")}
      </div>
      <div className="mt-2 grid gap-1 text-xs text-slate-600 dark:text-slate-300">
        <div className="flex min-w-0 justify-between gap-3">
          <span className="shrink-0 text-slate-500 dark:text-slate-400">
            {t("workshop_source_banner_module")}
          </span>
          <span className="min-w-0 truncate text-right font-medium">
            {moduleLabel}
          </span>
        </div>
        <div className="flex min-w-0 justify-between gap-3">
          <span className="shrink-0 text-slate-500 dark:text-slate-400">
            {t("workshop_source_banner_print_library")}
          </span>
          <span className="min-w-0 truncate text-right font-medium">
            {colorLibrary?.label ?? (
              <span className="text-amber-700 dark:text-amber-300">
                {t("workshop_source_banner_library_unavailable")}
              </span>
            )}
          </span>
        </div>
      </div>
      {colorLibraryChanged ? (
        <p
          role="status"
          className="mt-2 text-xs leading-5 text-amber-700 dark:text-amber-300"
        >
          {t("workshop_source_banner_library_changed")}
        </p>
      ) : null}
      <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
        {t("workshop_source_banner_guidance")}
      </p>
    </StatusBanner>
  );
}
