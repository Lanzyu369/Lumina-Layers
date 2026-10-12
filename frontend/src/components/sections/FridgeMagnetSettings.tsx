import { useMemo } from "react";
import { useConverterStore } from "../../stores/converter";
import { useI18n } from "../../i18n/context";
import Checkbox from "../ui/Checkbox";
import Dropdown from "../ui/Dropdown";
import Slider from "../ui/Slider";
import {
  cx,
  mutedSectionCardClass,
  workstationFieldLabelClass,
  workstationInputClass,
} from "../ui/panelPrimitives";
import type { FridgeMagnetItem, FridgeMagnetShape } from "../../api/types";
import {
  FRIDGE_MAGNET_CUSTOM_PRESET_KEY,
  getDefaultFridgeMagnetPresetKey,
  getFridgeMagnetPreset,
  getFridgeMagnetPresetsByShape,
} from "../../constants/fridgeMagnets";
import { WIKI_DOCS } from "../../utils/wikiDocs";

const NOOP = (): void => {};
const NOOP_BOOL: (value: boolean) => void = () => {};
const NOOP_ID: (id: string) => void = () => {};
const NOOP_UPDATE: (id: string, payload: unknown) => void = () => {};
const NOOP_CENTER: (id: string, x: number, y: number) => void = () => {};
const EMPTY_MAGNETS: FridgeMagnetItem[] = [];

interface NumberFieldProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  unit?: string;
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 0.1,
  disabled = false,
  unit,
}: NumberFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className={workstationFieldLabelClass}>{label}</label>
      <div className="flex items-center gap-2">
        <input
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(event) => {
            const nextValue = event.currentTarget.valueAsNumber;
            if (Number.isFinite(nextValue)) {
              onChange(nextValue);
            }
          }}
          className={cx(workstationInputClass, "tabular-nums")}
        />
        {unit ? (
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
            {unit}
          </span>
        ) : null}
      </div>
    </div>
  );
}

const actionButtonClass =
  "rounded-[18px] border border-slate-200/80 bg-white/80 px-3 py-2 text-sm font-medium text-slate-700 shadow-[var(--shadow-control)] transition-colors duration-150 hover:border-slate-300 hover:bg-white dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:bg-slate-900";

function getCustomFridgeMagnetLabel(
  t: (key: string) => string,
  magnet: FridgeMagnetItem,
): string {
  if (magnet.shape === "round") {
    return `${t("fridge_magnet_shape_round")} ${magnet.diameter_mm ?? 0}×${magnet.thickness_mm}`;
  }
  return `${t("fridge_magnet_shape_rect")} ${magnet.width_mm ?? 0}×${magnet.height_mm ?? 0}×${magnet.thickness_mm}`;
}

export default function FridgeMagnetSettings() {
  const { t } = useI18n();
  const unitMm = t("common_unit_mm");
  const enableFridgeMagnet = useConverterStore((s) => s.enable_fridge_magnet ?? false);
  const fridgeMagnets = useConverterStore((s) => s.fridge_magnets ?? EMPTY_MAGNETS);
  const selectedFridgeMagnetId = useConverterStore(
    (s) => s.selectedFridgeMagnetId ?? null,
  );
  const structureMode = useConverterStore((s) => s.structure_mode ?? "Double-sided");
  const spacerThick = useConverterStore((s) => s.spacer_thick ?? 1.2);
  const setEnableFridgeMagnet = useConverterStore(
    (s) => s.setEnableFridgeMagnet ?? NOOP_BOOL,
  );
  const resetFridgeMagnetLayout = useConverterStore(
    (s) => s.resetFridgeMagnetLayout ?? NOOP,
  );
  const addFridgeMagnet = useConverterStore((s) => s.addFridgeMagnet ?? NOOP);
  const removeFridgeMagnet = useConverterStore((s) => s.removeFridgeMagnet ?? NOOP_ID);
  const updateFridgeMagnet = useConverterStore((s) => s.updateFridgeMagnet ?? NOOP_UPDATE);
  const updateFridgeMagnetCenter = useConverterStore(
    (s) => s.updateFridgeMagnetCenter ?? NOOP_CENTER,
  );
  const selectFridgeMagnet = useConverterStore((s) => s.selectFridgeMagnet ?? NOOP_ID);
  const clearSelectedFridgeMagnet = useConverterStore(
    (s) => s.clearSelectedFridgeMagnet ?? NOOP,
  );

  const selectedMagnet =
    fridgeMagnets.find((item) => item.id === selectedFridgeMagnetId) ?? null;

  const shapeOptions = useMemo(
    () => [
      { label: t("fridge_magnet_shape_round"), value: "round" },
      { label: t("fridge_magnet_shape_rect"), value: "rect" },
    ],
    [t],
  );

  const presetOptions = useMemo(() => {
    const shape: FridgeMagnetShape = selectedMagnet?.shape ?? "round";
    const officialOptions = getFridgeMagnetPresetsByShape(shape).map((preset) => ({
      label: t(preset.labelKey),
      value: preset.key,
    }));
    return [
      ...officialOptions,
      {
        label: t("fridge_magnet_preset_custom"),
        value: FRIDGE_MAGNET_CUSTOM_PRESET_KEY,
      },
    ];
  }, [selectedMagnet?.shape, t]);

  const handleShapeChange = (value: string) => {
    if (!selectedMagnet) return;
    const shape = value as FridgeMagnetShape;
    const defaultPreset = getFridgeMagnetPreset(
      getDefaultFridgeMagnetPresetKey(shape),
    );
    if (!defaultPreset) return;

    updateFridgeMagnet(selectedMagnet.id, {
      shape,
      preset_key: defaultPreset.key,
      diameter_mm: defaultPreset.diameter_mm,
      width_mm: defaultPreset.width_mm,
      height_mm: defaultPreset.height_mm,
      thickness_mm: defaultPreset.thickness_mm,
    });
  };

  const handlePresetChange = (value: string) => {
    if (!selectedMagnet) return;
    if (value === FRIDGE_MAGNET_CUSTOM_PRESET_KEY) {
      updateFridgeMagnet(selectedMagnet.id, { preset_key: value });
      return;
    }

    const preset = getFridgeMagnetPreset(value);
    if (!preset) return;

    updateFridgeMagnet(selectedMagnet.id, {
      shape: preset.shape,
      preset_key: preset.key,
      diameter_mm: preset.diameter_mm,
      width_mm: preset.width_mm,
      height_mm: preset.height_mm,
      thickness_mm: preset.thickness_mm,
    });
  };

  const updateCustomMagnet = (
    updates: Partial<Omit<FridgeMagnetItem, "id">>,
  ) => {
    if (!selectedMagnet) return;
    updateFridgeMagnet(selectedMagnet.id, {
      ...updates,
      preset_key: FRIDGE_MAGNET_CUSTOM_PRESET_KEY,
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <Checkbox
        label={t("fridge_magnet_enable")}
        checked={enableFridgeMagnet}
        onChange={setEnableFridgeMagnet}
        tooltip={t("fridge_magnet_mode_hint")}
        wikiPath={WIKI_DOCS.fridgeMagnet}
      />

      {enableFridgeMagnet ? (
        <div className={mutedSectionCardClass}>
          <p className="text-xs text-slate-600 dark:text-slate-300">
            {t("fridge_magnet_mode_active_status")}
          </p>
          <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-slate-500 dark:text-slate-400">
            <div className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-700/80">
              <p className="font-medium text-slate-700 dark:text-slate-200">
                {t("fridge_magnet_summary_structure")}
              </p>
              <p>{t(`structure_mode.${structureMode}`)}</p>
            </div>
            <div className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-700/80">
              <p className="font-medium text-slate-700 dark:text-slate-200">
                {t("fridge_magnet_summary_spacer")}
              </p>
              <p>{spacerThick.toFixed(1)} {t("common_unit_mm")}</p>
            </div>
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={actionButtonClass}
          onClick={addFridgeMagnet}
          disabled={!enableFridgeMagnet}
        >
          {t("fridge_magnet_add")}
        </button>
        <button
          type="button"
          className={actionButtonClass}
          onClick={resetFridgeMagnetLayout}
          disabled={!enableFridgeMagnet || fridgeMagnets.length === 0}
        >
          {t("fridge_magnet_reset_layout")}
        </button>
        <button
          type="button"
          className={actionButtonClass}
          onClick={() => selectedMagnet && removeFridgeMagnet(selectedMagnet.id)}
          disabled={!enableFridgeMagnet || !selectedMagnet}
        >
          {t("fridge_magnet_remove_selected")}
        </button>
      </div>

      {fridgeMagnets.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            {t("fridge_magnet_list_title")}
          </p>
          <div className="flex flex-col gap-2">
            {fridgeMagnets.map((magnet, index) => {
              const preset = getFridgeMagnetPreset(magnet.preset_key);
              const isSelected = magnet.id === selectedFridgeMagnetId;
              return (
                <button
                  key={magnet.id}
                  type="button"
                  onClick={() => selectFridgeMagnet(magnet.id)}
                  className={cx(
                    "rounded-[22px] border px-3.5 py-3 text-left shadow-[var(--shadow-control)] transition-colors duration-150",
                    isSelected
                      ? "border-blue-400 bg-blue-50/80 dark:border-blue-400/80 dark:bg-blue-500/10"
                      : "border-slate-200/80 bg-white/65 hover:border-slate-300 hover:bg-white dark:border-slate-700/80 dark:bg-slate-900/60 dark:hover:border-slate-600",
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
                      {t("fridge_magnet_item_label").replace("{index}", String(index + 1))}
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {t(
                        magnet.shape === "round"
                          ? "fridge_magnet_shape_round"
                          : "fridge_magnet_shape_rect",
                      )}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {preset ? t(preset.labelKey) : getCustomFridgeMagnetLabel(t, magnet)}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      ) : enableFridgeMagnet ? (
        <div className={mutedSectionCardClass}>
          <p className="text-xs text-slate-600 dark:text-slate-300">
            {t("fridge_magnet_empty_state")}
          </p>
        </div>
      ) : null}

      {selectedMagnet ? (
        <div className="flex flex-col gap-4">
          <Dropdown
            label={t("fridge_magnet_shape")}
            value={selectedMagnet.shape}
            options={shapeOptions}
            onChange={handleShapeChange}
          />

          <Dropdown
            label={t("fridge_magnet_preset")}
            value={selectedMagnet.preset_key}
            options={presetOptions}
            onChange={handlePresetChange}
          />

          {selectedMagnet.shape === "round" ? (
            <NumberField
              label={t("fridge_magnet_diameter")}
              value={selectedMagnet.diameter_mm ?? 0}
              min={1}
              max={50}
              step={0.1}
              unit={unitMm}
              onChange={(value) => updateCustomMagnet({ diameter_mm: value })}
            />
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <NumberField
                label={t("fridge_magnet_width")}
                value={selectedMagnet.width_mm ?? 0}
                min={1}
                max={80}
                step={0.1}
                unit={unitMm}
                onChange={(value) => updateCustomMagnet({ width_mm: value })}
              />
              <NumberField
                label={t("fridge_magnet_height")}
                value={selectedMagnet.height_mm ?? 0}
                min={1}
                max={80}
                step={0.1}
                unit={unitMm}
                onChange={(value) => updateCustomMagnet({ height_mm: value })}
              />
            </div>
          )}

          <Slider
            label={t("fridge_magnet_thickness")}
            value={selectedMagnet.thickness_mm}
            min={0.5}
            max={3.1}
            step={0.1}
            unit={unitMm}
            onChange={(value) => updateCustomMagnet({ thickness_mm: value })}
            displayDecimals={1}
          />

          <div className="grid grid-cols-2 gap-3">
            <NumberField
              label={t("fridge_magnet_center_x")}
              value={selectedMagnet.center_x_mm}
              min={-999}
              max={999}
              step={0.1}
              unit={unitMm}
              onChange={(value) =>
                updateFridgeMagnetCenter(
                  selectedMagnet.id,
                  value,
                  selectedMagnet.center_y_mm,
                )
              }
            />
            <NumberField
              label={t("fridge_magnet_center_y")}
              value={selectedMagnet.center_y_mm}
              min={-999}
              max={999}
              step={0.1}
              unit={unitMm}
              onChange={(value) =>
                updateFridgeMagnetCenter(
                  selectedMagnet.id,
                  selectedMagnet.center_x_mm,
                  value,
                )
              }
            />
          </div>

          <button
            type="button"
            className={actionButtonClass}
            onClick={clearSelectedFridgeMagnet}
          >
            {t("fridge_magnet_clear_selection")}
          </button>
        </div>
      ) : fridgeMagnets.length > 0 ? (
        <div className={mutedSectionCardClass}>
          <p className="text-xs text-slate-600 dark:text-slate-300">
            {t("fridge_magnet_select_hint")}
          </p>
        </div>
      ) : null}
    </div>
  );
}
