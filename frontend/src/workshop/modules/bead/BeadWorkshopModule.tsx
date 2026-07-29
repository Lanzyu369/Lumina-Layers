import { useState } from "react";

import Button from "../../../components/ui/Button";
import {
  PanelIntro,
  StatusBanner,
  mutedSectionCardClass,
} from "../../../components/ui/panelPrimitives";
import type { WorkshopModuleProps } from "../../types";

export function BeadWorkshopModule({
  manifest,
  host,
}: WorkshopModuleProps) {
  const t = host.ui.translate;
  const locale = host.ui.getLocale();
  const [isPicking, setIsPicking] = useState(false);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(
    null,
  );
  const [visibleError, setVisibleError] = useState<string | null>(null);

  const handlePickImage = async () => {
    setIsPicking(true);
    setVisibleError(null);
    host.status.reportProgress({
      phase: "pick-image",
      completed: 0,
      total: 1,
    });
    try {
      const picked = await host.files.pickImage();
      if (picked) {
        setSelectedFileName(picked.file.name);
      }
      host.status.reportProgress(null);
    } catch {
      const message = t("workshop.bead.pickerError");
      setVisibleError(message);
      host.status.reportError({
        code: "image-pick-failed",
        message,
        retryable: true,
      });
      host.status.reportProgress(null);
    } finally {
      setIsPicking(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
      <PanelIntro
        eyebrow={t("workshop.official")}
        title={manifest.name[locale]}
        description={t("workshop.bead.intro")}
      />

      {visibleError && (
        <StatusBanner tone="error">{visibleError}</StatusBanner>
      )}

      <section className={`${mutedSectionCardClass} flex flex-col gap-4`}>
        <div className="flex flex-col gap-1">
          <p className="text-sm font-medium text-slate-800 dark:text-slate-100">
            {t("workshop.bead.supportedInputs")}
          </p>
          <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
            {t("workshop.bead.localPrivacy")}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            label={t("workshop.bead.choosePattern")}
            loading={isPicking}
            onClick={handlePickImage}
          />
          {selectedFileName && (
            <p
              className="min-w-0 truncate text-sm text-slate-600 dark:text-slate-300"
              title={selectedFileName}
            >
              {t("workshop.bead.selectedFile").replace(
                "{filename}",
                selectedFileName,
              )}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
