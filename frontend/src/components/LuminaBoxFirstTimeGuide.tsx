import { useI18n } from "../i18n/context";
import Button from "./ui/Button";
import { StatusBanner } from "./ui/panelPrimitives";

export default function LuminaBoxFirstTimeGuide({ onStartBacking, onDismiss }: {
  onStartBacking: () => void;
  onDismiss?: () => void;
}) {
  const { t } = useI18n();

  return (
    <StatusBanner tone="info" data-testid="lumina-box-first-time-guide">
      <div className="space-y-3">
        <div>
          <h3 className="font-semibold">{t("lumina_box_workflow_guide_title")}</h3>
          <p className="mt-1 text-sm">{t("lumina_box_workflow_guide_message")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            label={t("lumina_box_backing_collect")}
            size="sm"
            onClick={onStartBacking}
          />
          {onDismiss && (
            <Button
              label={t("lumina_box_material_cancel")}
              size="sm"
              variant="secondary"
              onClick={onDismiss}
            />
          )}
        </div>
      </div>
    </StatusBanner>
  );
}
