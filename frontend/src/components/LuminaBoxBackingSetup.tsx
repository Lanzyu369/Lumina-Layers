import { useState } from "react";
import type { LuminaBoxBackingMaterial, LuminaBoxBackingMaterialRequest, LuminaBoxBlackWhitePairRequest } from "../api/luminaBoxMaterials";
import { useI18n } from "../i18n/context";
import { boxMaterialInputClass } from "./LuminaBoxMaterialCapture";
import Button from "./ui/Button";
import Dropdown from "./ui/Dropdown";
import { cardDividerClass, wellClass } from "./ui/panelPrimitives";

const emptyIdentity = { name: "", brand: "", material_type: "" };

export default function LuminaBoxBackingSetup({ materials, locked, busy, onStart, onStartPair }: {
  materials: LuminaBoxBackingMaterial[];
  locked: boolean;
  busy: boolean;
  onStart: (payload: LuminaBoxBackingMaterialRequest) => Promise<void>;
  onStartPair: (payload: LuminaBoxBlackWhitePairRequest) => Promise<void>;
}) {
  const { t } = useI18n();
  const ready = materials.filter((item) => item.status === "ready");
  const [creationMode, setCreationMode] = useState<"pair" | "single">(ready.length ? "single" : "pair");
  const paired = !ready.length || creationMode === "pair";
  const [white, setWhite] = useState(emptyIdentity);
  const [black, setBlack] = useState(emptyIdentity);
  const [role, setRole] = useState<"W" | "K">(ready.some((item) => item.role === "K") || !ready.length ? "W" : "K");
  const [opposite, setOpposite] = useState("");
  const identity = role === "W" ? white : black;
  const fields = (value: typeof emptyIdentity, change: (value: typeof emptyIdentity) => void) =>
    <div className="grid gap-4 sm:grid-cols-3">
      {(["name", "brand", "material_type"] as const).map((field) => <label key={field} className="space-y-1.5 text-sm font-medium">
        {t(`lumina_box_material_${field}`)}
        <input className={boxMaterialInputClass} required={field === "name"} maxLength={200} value={value[field]} disabled={locked}
          onChange={(event) => change({ ...value, [field]: event.target.value })} />
      </label>)}
    </div>;
  return <form className={`${cardDividerClass} space-y-5 pt-4`} data-testid="box-backing-create-form" onSubmit={(event) => {
    event.preventDefault();
    if (locked || busy) return;
    if (paired) {
      if (white.name.trim() && black.name.trim()) void onStartPair({ white, black });
    } else if (identity.name.trim() && opposite) void onStart({ ...identity, role, opposite_material_id: opposite });
  }}>
    <h3 className="text-base font-semibold">{t(paired ? "lumina_box_pair_create" : "lumina_box_backing_collect")}</h3>
    {ready.length > 0 ? <Dropdown label={t("lumina_box_bw_creation_mode")} value={creationMode} disabled={locked || busy}
      options={[{ value: "pair", label: t("lumina_box_bw_create_pair") }, { value: "single", label: t("lumina_box_bw_create_single") }]}
      onChange={(value) => setCreationMode(value as "pair" | "single")} /> : null}
    {paired ? <>
      <div role="group" aria-label={t("lumina_box_white_material")} className={`${wellClass} space-y-3 p-4`}>
        <h4 className="font-medium">{t("lumina_box_white_material")}</h4>
        {fields(white, setWhite)}
      </div>
      <div role="group" aria-label={t("lumina_box_black_material")} className={`${wellClass} space-y-3 p-4`}>
        <h4 className="font-medium">{t("lumina_box_black_material")}</h4>
        {fields(black, setBlack)}
      </div>
    </> : <>
      <Dropdown label={t("lumina_box_backing_role")} value={role} disabled={locked}
        options={[{ value: "W", label: t("lumina_box_white_material") }, { value: "K", label: t("lumina_box_black_material") }]}
        onChange={(value) => { setRole(value as "W" | "K"); setOpposite(""); }} />
      {fields(identity, role === "W" ? setWhite : setBlack)}
      <Dropdown label={t(role === "W" ? "lumina_box_sample_black_material" : "lumina_box_sample_white_material")}
        value={opposite} disabled={locked} placeholder={t("lumina_box_backing_select")}
        options={ready.filter((item) => item.role !== role).map((item) => ({ value: item.material_id,
          label: [item.name, item.brand, item.material_type].filter(Boolean).join(" · ") }))}
        onChange={setOpposite} />
    </>}
    <div className={`${wellClass} space-y-2 p-4`}>
      <h4 className="font-medium">{t("lumina_box_required_samples")}</h4>
      {(paired || role === "W") && <p>{t("lumina_box_backing_white_samples")}</p>}
      {(paired || role === "K") && <p>{t("lumina_box_backing_black_samples")}</p>}
    </div>
    <Button type="submit" label={t(paired ? "lumina_box_pair_start_white" : "lumina_box_material_start_capture")} loading={busy}
      disabled={locked || (paired ? !white.name.trim() || !black.name.trim() : !identity.name.trim() || !opposite)} />
  </form>;
}
