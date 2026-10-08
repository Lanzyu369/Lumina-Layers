import type { SavedMaterialLibraryItem } from "../api/types";
import { useI18n } from "../i18n/context";
import { useLuminaBoxMaterialNavigation } from "../stores/luminaBoxMaterialNavigation";
import Button from "./ui/Button";
import { cardClass, cardDividerClass } from "./ui/panelPrimitives";

export default function LuminaBoxLibraryCard({ item, selected, busy, onSelect, onEdit, onDelete }: {
  item: SavedMaterialLibraryItem; selected: boolean; busy: boolean;
  onSelect: () => void; onEdit: () => void; onDelete: () => void;
}) {
  const { t, lang } = useI18n();
  const navigation = useLuminaBoxMaterialNavigation();
  const rgb = item.estimated_rgb.map((value) => Math.max(0, Math.min(255, Math.round(value))));
  return <section className={`${cardClass} flex flex-col gap-4 p-5`} data-testid="material-library-item">
    <div className="flex items-start gap-3">
      <input type="checkbox" checked={selected} onChange={onSelect} className="mt-1 h-4 w-4 accent-blue-500"
        aria-label={`${t("lumina_box_material_select")} ${item.material_name}`} data-testid={`material-library-select-${item.directory_name}`} />
      <div className="h-16 w-16 shrink-0 rounded-[10px]" aria-hidden="true" style={{ backgroundColor: `rgb(${rgb.join(",")})` }} />
      <div className="min-w-0"><h3 className="truncate text-base font-semibold">{item.material_name}</h3>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{[item.brand, item.material_type].filter(Boolean).join(" · ")}</p>
      </div>
    </div>
    <div className="flex flex-wrap gap-2">
      <Button label={t("lumina_box_material_use_conversion")} onClick={() => navigation.useForConversion(item.directory_name, item.material_symbol ?? undefined)} />
      <Button variant="secondary" label={t("lumina_box_material_remeasure")} disabled={busy || !item.capture_dataset_id || !item.material_symbol}
        onClick={() => navigation.resumeCapture(item.capture_dataset_id!, item.material_symbol!, {
          name: item.material_name, brand: item.brand ?? "", material_type: item.material_type ?? "", directoryName: item.directory_name,
        })} />
    </div>
    <div className={`${cardDividerClass} flex flex-wrap items-center justify-between gap-2 pt-3`}>
      <span className="text-xs text-slate-500 dark:text-slate-400">{item.updated_at || item.created_at
        ? new Date(item.updated_at || item.created_at!).toLocaleDateString(lang === "zh" ? "zh-CN" : "en-US") : ""}</span>
      <div className="flex gap-2"><Button size="sm" variant="secondary" label={t("mat_gradient_library_edit_btn")} disabled={busy} onClick={onEdit} />
        <Button size="sm" variant="secondary" label={t("mat_gradient_library_delete_btn")} disabled={busy} onClick={onDelete} /></div>
    </div>
  </section>;
}
