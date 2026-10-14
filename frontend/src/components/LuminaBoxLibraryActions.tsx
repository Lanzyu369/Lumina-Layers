import { useEffect, useState } from "react";
import { listLuminaBoxBackingMaterials, type LuminaBoxBackingMaterial } from "../api/luminaBoxMaterials";
import { useI18n } from "../i18n/context";
import { useLuminaBoxMaterialNavigation } from "../stores/luminaBoxMaterialNavigation";
import Button from "./ui/Button";
import { cardClass, StatusBanner } from "./ui/panelPrimitives";

export default function LuminaBoxLibraryActions() {
  const { t } = useI18n();
  const navigation = useLuminaBoxMaterialNavigation();
  const [pending, setPending] = useState<LuminaBoxBackingMaterial[]>([]);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void listLuminaBoxBackingMaterials().then((items) => {
      if (active) { setPending(items.filter((item) => item.status !== "ready")); setError(false); }
    }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [attempt]);
  return <div className="space-y-4">
    <div className="flex flex-wrap gap-3">
      <Button label={t("lumina_box_backing_collect")} onClick={() => navigation.createProfile("backing")} />
      <Button variant="secondary" label={t("lumina_box_material_new")} onClick={() => navigation.createProfile("material")} />
    </div>
    {error ? <StatusBanner tone="error" action={<Button label={t("lumina_box_material_retry")} onClick={() => setAttempt((value) => value + 1)} />}>
      {t("lumina_box_material_load_failed")}
    </StatusBanner> : null}
    {pending.length ? <section className={`${cardClass} space-y-4 p-5`}>
      <h3 className="font-semibold">{t("lumina_box_pending_profiles")}</h3>
      {pending.map((item) => <div key={item.material_id} className="flex flex-wrap items-center justify-between gap-3">
        <span>{[item.name, item.brand, item.material_type].filter(Boolean).join(" · ")}</span>
        <Button variant="secondary" label={t(item.status === "measured" ? "lumina_box_view_capture" : "lumina_box_continue_capture")}
          disabled={!item.active_dataset_id && !item.dataset_id}
          onClick={() => navigation.resumeCapture((item.active_dataset_id ?? item.dataset_id)!, item.role)} />
      </div>)}
    </section> : null}
  </div>;
}
