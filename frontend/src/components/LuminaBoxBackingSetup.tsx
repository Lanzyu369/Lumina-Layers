import { useState } from "react";
import type { LuminaBoxBackingMaterial, LuminaBoxBackingMaterialRequest } from "../api/luminaBoxMaterials";
import { useI18n } from "../i18n/context";
import { boxMaterialInputClass } from "./LuminaBoxMaterialCapture";
import Button from "./ui/Button";
import Dropdown from "./ui/Dropdown";
import { cardDividerClass, wellClass } from "./ui/panelPrimitives";

/** Create or resume a separately identified backing material.
 * 单独新建或继续采集一份背板耗材资料。 */
export default function LuminaBoxBackingSetup({ materials, initialMaterial, locked, busy, onStart, onOpen }: {
  materials: LuminaBoxBackingMaterial[];
  initialMaterial?: LuminaBoxBackingMaterial | null;
  locked: boolean;
  busy: boolean;
  onStart: (payload: LuminaBoxBackingMaterialRequest) => Promise<void>;
  onOpen: (material: LuminaBoxBackingMaterial) => void;
}) {
  const { t } = useI18n();
  const [selected, setSelected] = useState<LuminaBoxBackingMaterial | null>(initialMaterial ?? null);
  const [form, setForm] = useState({ name: initialMaterial?.name ?? "", brand: initialMaterial?.brand ?? "", material_type: initialMaterial?.material_type ?? "",
    role: initialMaterial?.role ?? "W", opposite: initialMaterial?.opposite_material_id ?? "", opposite_name: "" });
  const oppositeOptions = materials.filter((item) => item.role !== form.role);
  const needsName = form.opposite === "new" || !oppositeOptions.length;
  const label = (item: LuminaBoxBackingMaterial) => [item.name, item.brand, item.material_type].filter(Boolean).join(" · ");
  const begin = (material: LuminaBoxBackingMaterial | null) => {
    setSelected(material);
    setForm({ name: material?.name ?? "", brand: material?.brand ?? "", material_type: material?.material_type ?? "",
      role: material?.role ?? "W", opposite: material?.opposite_material_id ?? "", opposite_name: "" });
  };
  return <div className={`${cardDividerClass} space-y-4 pt-4`} data-testid="box-backing-setup">
    {materials.length ? <div className={`${wellClass} space-y-2 p-3`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t("lumina_box_backing_saved_materials")}</h3>
        <Button size="sm" variant="secondary" label={t("lumina_box_backing_new")} disabled={locked} onClick={() => begin(null)} />
      </div>
      {materials.map((item) => <button key={item.material_id} type="button" disabled={locked}
        className="flex min-h-11 w-full flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-blue-500/10 focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)]"
        onClick={() => item.active_dataset_id || item.dataset_id ? onOpen(item) : begin(item)}>
        <span>{label(item)}</span><span className="text-xs text-slate-500 dark:text-slate-400">{t(item.role === "W" ? "lumina_box_backing_white" : "lumina_box_backing_black")} · {t(`lumina_box_backing_status_${item.status}`)}</span>
      </button>)}
    </div> : null}
    <form className="space-y-4" data-testid="box-backing-create-form" onSubmit={(event) => {
      event.preventDefault();
      if (locked || !form.name.trim() || (needsName ? !form.opposite_name.trim() : !form.opposite)) return;
      void onStart({ name: form.name.trim(), brand: form.brand.trim(), material_type: form.material_type.trim(), role: form.role,
        ...(selected ? { material_id: selected.material_id } : {}),
        ...(needsName ? { opposite_name: form.opposite_name.trim() } : { opposite_material_id: form.opposite }) });
    }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Dropdown label={t("lumina_box_backing_role")} value={form.role} disabled={locked || !!selected}
          options={[{ value: "W", label: t("lumina_box_backing_white") }, { value: "K", label: t("lumina_box_backing_black") }]}
          onChange={(role) => setForm({ ...form, role: role as "W" | "K", opposite: "", opposite_name: "" })} />
        {(["name", "brand", "material_type"] as const).map((field) => <label key={field} className="space-y-1.5 text-sm font-medium">{t(`lumina_box_material_${field}`)}
          <input className={boxMaterialInputClass} required={field === "name"} maxLength={200} value={form[field]} disabled={locked}
            onChange={(event) => setForm({ ...form, [field]: event.target.value })} />
        </label>)}
      </div>
      <div className={`${wellClass} space-y-3 p-4`}>
        <p className="text-sm">{t(form.role === "W" ? "lumina_box_backing_white_samples" : "lumina_box_backing_black_samples")}</p>
        {oppositeOptions.length ? <Dropdown label={t("lumina_box_backing_sample_base")} value={form.opposite} disabled={locked}
          placeholder={t("lumina_box_backing_select")}
          options={[...oppositeOptions.map((item) => ({ value: item.material_id, label: label(item) })), { value: "new", label: t("lumina_box_backing_other") }]}
          onChange={(opposite) => setForm({ ...form, opposite })} /> : null}
        {needsName ? <label className="block space-y-1.5 text-sm font-medium">{t("lumina_box_backing_sample_base_name")}
          <input className={boxMaterialInputClass} required maxLength={200} disabled={locked} value={form.opposite_name}
            onChange={(event) => setForm({ ...form, opposite_name: event.target.value })} />
        </label> : null}
      </div>
      <Button type="submit" label={t("lumina_box_material_start_capture")} loading={busy}
        disabled={locked || !form.name.trim() || (needsName ? !form.opposite_name.trim() : !form.opposite)} />
    </form>
  </div>;
}
