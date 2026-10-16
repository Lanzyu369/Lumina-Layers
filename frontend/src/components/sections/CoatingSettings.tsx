import { useEffect, useState } from "react";
import { listGradientCardMaterials } from "../../api/extractor";
import type { CoatingMaterialReference, SavedMaterialLibraryItem } from "../../api/types";
import { useConverterStore } from "../../stores/converter";
import { useI18n } from "../../i18n/context";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";
import Dropdown from "../ui/Dropdown";
import { StatusBanner } from "../ui/panelPrimitives";
import { WIKI_DOCS } from "../../utils/wikiDocs";

export default function CoatingSettings() {
  const { t } = useI18n();
  const enable_coating = useConverterStore((s) => s.enable_coating);
  const coating_height_mm = useConverterStore((s) => s.coating_height_mm);
  const setEnableCoating = useConverterStore((s) => s.setEnableCoating);
  const setCoatingHeightMm = useConverterStore((s) => s.setCoatingHeightMm);
  const coatingMaterial = useConverterStore((s) => s.coatingMaterial);
  const setCoatingMaterial = useConverterStore((s) => s.setCoatingMaterial);
  const sourceVersion = useConverterStore((s) => s.source_version);
  const selectedDirectories = useConverterStore((s) => s.selectedMaterialDirNames);
  const lutInfo = useConverterStore((s) => s.selectedLutInfo);
  const [library, setLibrary] = useState<SavedMaterialLibraryItem[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    if (!enable_coating) return;
    let cancelled = false;
    setLoadFailed(false);
    listGradientCardMaterials().then((result) => {
      if (!cancelled) setLibrary(result.materials ?? []);
    }).catch(() => { if (!cancelled) setLoadFailed(true); });
    return () => { cancelled = true; };
  }, [enable_coating, loadAttempt]);

  const palette = sourceVersion === "material"
    ? selectedDirectories.flatMap((directory) => {
      const item = library.find((material) => material.directory_name === directory);
      return item ? [{ name: item.material_name, type: item.material_type ?? "" }] : [];
    })
    : (lutInfo?.palette ?? []).map((item) => ({ name: item.color, type: item.material }));
  const paletteOptions = palette.map((item) => ({
    label: `${item.name} · ${item.type}`,
    value: JSON.stringify({ source: "palette", key: item.name } satisfies CoatingMaterialReference),
  }));
  const libraryOptions = library.map((item) => ({
    label: `${item.material_name} · ${item.material_type ?? ""}`,
    value: JSON.stringify({ source: "material_archive", key: item.directory_name } satisfies CoatingMaterialReference),
  }));
  const coatingType = coatingMaterial?.source === "palette"
    ? palette.find((item) => item.name === coatingMaterial.key)?.type
    : library.find((item) => item.directory_name === coatingMaterial?.key)?.material_type;
  const mixedTypes = coatingType && palette.some((item) => item.type && item.type !== coatingType);

  return (
    <div className="flex flex-col gap-4">
      <Checkbox
        label={t("coating_enable")}
        checked={enable_coating}
        onChange={setEnableCoating}
        tooltip={t("coating_enable_hint")}
        wikiPath={WIKI_DOCS.transparentCoating}
      />
      {enable_coating && (
        <>
        <Dropdown
          label={t("coating_material")}
          value={coatingMaterial ? JSON.stringify(coatingMaterial) : ""}
          placeholder={t("coating_material_choose")}
          groupedOptions={[
            { label: t("coating_material_palette"), options: paletteOptions },
            { label: t("coating_material_archive"), options: libraryOptions },
          ]}
          onChange={(value) => setCoatingMaterial(JSON.parse(value) as CoatingMaterialReference)}
        />
        {loadFailed && <StatusBanner tone="warning" action={
          <button type="button" className="underline" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>{t("coating_material_retry")}</button>
        }>{t("coating_material_load_failed")}</StatusBanner>}
        <StatusBanner tone={mixedTypes ? "warning" : "info"}>
          {mixedTypes ? t("coating_material_mixed") : t("coating_material_hint")}
        </StatusBanner>
        <Slider
          label={t("coating_height")}
          tooltip={t("coating_height_hint")}
          wikiPath={WIKI_DOCS.transparentCoating}
          value={coating_height_mm}
          min={0.04}
          max={0.12}
          step={0.04}
          unit="mm"
          onChange={setCoatingHeightMm}
        />
        </>
      )}
    </div>
  );
}
