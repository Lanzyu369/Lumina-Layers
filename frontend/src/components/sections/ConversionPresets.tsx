import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useShallow } from "zustand/react/shallow";
import { useSettingsStore } from "../../stores/settingsStore";
import { useConverterStore } from "../../stores/converter";
import { StructureMode } from "../../api/types";
import { useI18n } from "../../i18n/context";
import Dropdown from "../ui/Dropdown";
import Button from "../ui/Button";
import { workstationInputClass } from "../ui/panelPrimitives";

export default function ConversionPresets() {
  const { t } = useI18n();
  const current = useConverterStore(useShallow(captureConversionParameters));
  const preferences = useSettingsStore(state => state.conversionPreferences);
  const presets = preferences.presets;
  const context = useConverterStore(state => state.conversionParameterContext);
  const actions = useConverterStore(useShallow(state => ({
    apply: state.applyConversionPreset,
    save: state.saveConversionPreset,
    update: state.updateConversionPreset,
    rename: state.renameConversionPreset,
    delete: state.deleteConversionPreset,
  })));
  const selected = context === "project" ? "project" : preferences.selectedPresetId ?? "last";
  const [dialogMode, setDialogMode] = useState<"save" | "rename" | "delete" | null>(null);
  const open = dialogMode !== null;
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const saveRef = useRef<HTMLButtonElement>(null);
  const active = presets.find(p => p.id === selected);
  const summary = (p: ConversionParameters) => [
    t(p.source_version === "material" ? "conversion_preset_material" : "conversion_preset_lut"),
    t(p.structure_mode === StructureMode.SINGLE_SIDED ? "conversion_preset_single" : "conversion_preset_double"),
  ].join(" · ");

  const closeDialog = useCallback(() => { setDialogMode(null); saveRef.current?.focus(); }, []);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    dialog?.querySelector<HTMLElement>("input,button")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { closeDialog(); }
      if (event.key !== "Tab" || !dialog) return;
      const elements = Array.from(dialog.querySelectorAll<HTMLElement>("input,button:not(:disabled)"));
      if (event.shiftKey && document.activeElement === elements[0]) {
        event.preventDefault(); elements.at(-1)?.focus();
      } else if (!event.shiftKey && document.activeElement === elements.at(-1)) {
        event.preventDefault(); elements[0]?.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, [open, closeDialog]);

  const apply = (id: string) => {
    if (id === "rename" || id === "delete") {
      setDialogMode(id); setName(active?.name ?? ""); setError(""); return;
    }
    if (id !== "project") actions.apply(id === "last" ? null : id);
  };

  return <section className="flex min-w-0 flex-col gap-1">
    <div className="flex min-w-0 items-center justify-between gap-2">
    <div className="min-w-0 flex-1">
    <Dropdown label={t("conversion_preset_inline_label")} value={selected} variant="inline"
      options={[
        ...(context === "project" ? [{ value: "project", label: t("conversion_preset_project") }] : []),
        { value: "last", label: t("conversion_preset_last") },
        ...presets.map(p => ({ value: p.id,
          label: p.name, description: summary(p.parameters),
        })),
        ...(active ? [
          { value: "rename", label: t("conversion_preset_rename") },
          { value: "delete", label: t("conversion_preset_delete") },
        ] : []),
      ]}
      onChange={apply}
    />
    </div>
      <button type="button" ref={saveRef}
        className="shrink-0 rounded-md px-1 py-1.5 text-[11px] text-slate-500 transition-colors hover:text-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:text-slate-400 dark:hover:text-blue-400"
        {t("conversion_preset_save")}
      </button>
    </div>
    {dirty && <div className="flex items-center justify-between gap-2 px-1 text-[11px] leading-relaxed text-slate-400 dark:text-slate-500">
      <span title={t("conversion_preset_dirty_hint")}>{t("conversion_preset_modified")}</span>
      <button type="button" className="shrink-0 text-blue-600 dark:text-blue-400"
        onClick={() => { if (active) actions.update(active.id); }}>
        {t("conversion_preset_update")}
      </button>
    </div>}
    {open && createPortal(<div className="fixed inset-0 z-[10000] flex items-center justify-center p-4 backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }} onClick={e => { if (e.target === e.currentTarget) closeDialog(); }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="conversion-preset-title"
        style={{ background: "var(--surface-panel-strong)", borderColor: "var(--surface-outline)" }}>
          e.preventDefault();
          if (dialogMode === "delete") {
            if (active) actions.delete(active.id);
          } else {
            const result = dialogMode === "rename"
              ? actions.rename(active?.id ?? "", name)
            const failure = typeof result === "string" ? result : result && "error" in result ? result.error : null;
            if (failure) {
              setError(t(failure === "duplicate-name" ? "conversion_preset_duplicate"
                : failure === "missing-preset" ? "conversion_preset_missing" : "conversion_preset_invalid_name"));
              return;
            }
          }
          closeDialog();
        }}>
          {dialogMode !== "delete" && <>
          <input id="conversion-preset-name" className={workstationInputClass} value={name} required maxLength={40}
            placeholder={t("conversion_preset_name_hint")} aria-invalid={!!error}
            onChange={e => { setName(e.target.value); setError(""); }}/>
          {error && <p role="alert" className="mt-2 text-xs text-red-500">{error}</p>}
          </>}
          {dialogMode === "save" && <>
          </>}
            <Button variant="secondary" label={t("conversion_preset_cancel")} onClick={() => closeDialog()} />
            <Button type="submit" label={t(dialogMode === "save" ? "conversion_preset_confirm" : dialogMode === "rename" ? "conversion_preset_rename" : "conversion_preset_delete")} />
          </div>
        </form>
      </div>
    </div>, document.body)}
  </section>;
}
