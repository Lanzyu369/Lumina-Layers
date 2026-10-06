import { useEffect, useId, useRef, useState } from "react";
import {
  deleteCustom3mfTemplate,
  getCustom3mfTemplates,
  importCustom3mfTemplate,
  type Custom3mfTemplate,
} from "../../api/system";
import { apiErrorToVisibleMessage } from "../../api/client";
import { useI18n } from "../../i18n/context";
import { useSettingsStore } from "../../stores/settingsStore";
import Button from "../ui/Button";
import Dropdown from "../ui/Dropdown";
import { StatusBanner, workstationInputClass } from "../ui/panelPrimitives";

export default function Custom3mfTemplateSettings() {
  const { t } = useI18n();
  const nameId = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const selectedId = useSettingsStore((s) => s.custom3mfTemplateId);
  const slicer = useSettingsStore((s) => s.slicerSoftware);
  const select = useSettingsStore((s) => s.setCustom3mfTemplateId);
  const [templates, setTemplates] = useState<Custom3mfTemplate[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);

  useEffect(() => {
    let cancelled = false;
    mounted.current = true;
    getCustom3mfTemplates()
      .then((items) => {
        if (!cancelled) setTemplates(items);
      })
      .catch(() => {
        if (!cancelled) setError("settings.template_load_error");
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
      mounted.current = false;
    };
  }, []);

  const upload = async () => {
    if (!file) return;
    setErrorDetail(null);
    if (!file.name.toLowerCase().endsWith(".3mf")) {
      setError("settings.template_file_error");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const item = await importCustom3mfTemplate(file, name, slicer);
      if (!mounted.current) return;
      setTemplates((items) => [...items, item]);
      select(item.id);
      setName("");
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
    } catch (cause) {
      if (!mounted.current) return;
      setError("settings.template_import_error");
      setErrorDetail(apiErrorToVisibleMessage(cause));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const remove = async () => {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    setErrorDetail(null);
    try {
      await deleteCustom3mfTemplate(selectedId);
      if (!mounted.current) return;
      setTemplates((items) => items.filter((item) => item.id !== selectedId));
      if (useSettingsStore.getState().custom3mfTemplateId === selectedId) select(null);
    } catch (cause) {
      if (!mounted.current) return;
      setError("settings.template_delete_error");
      setErrorDetail(apiErrorToVisibleMessage(cause));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const selected = templates.find((item) => item.id === selectedId);
  const missing = !busy && !error && !!selectedId && !selected;
  const options = [
    { value: "", label: t("settings.template_builtin") },
    ...templates.map((item) => ({ value: item.id, label: item.name })),
    ...(missing ? [{ value: selectedId, label: t("settings.template_missing_option") }] : []),
  ];

  return (
    <div className="space-y-3 border-t panel-divider pt-5">
      <Dropdown
        label={t("settings.template_title")}
        tooltip={t("settings.template_hint")}
        value={selectedId ?? ""}
        disabled={busy}
        options={options}
        onChange={(id) => select(id || null)}
      />
      {selected && (
        <p className="text-xs text-slate-600 dark:text-slate-300">
          {t("settings.template_metadata")
            .replace("{printer}", selected.printer_model)
            .replace("{slicer}", selected.slicer)
            .replace("{nozzle}", selected.nozzle_diameter.join(" / "))
            .replace("{count}", String(selected.filament_count))}
        </p>
      )}
      {missing && <StatusBanner tone="warning">{t("settings.template_missing")}</StatusBanner>}
      <p className="text-xs leading-relaxed text-slate-500 dark:text-slate-400">
        {t("settings.template_summary")}
      </p>
      <p className="text-xs leading-relaxed text-slate-600 dark:text-slate-300">
        {t("settings.template_excluded")}
      </p>
      <input
        ref={fileInput}
        aria-label={t("settings.template_file")}
        type="file"
        accept=".3mf"
        hidden
        disabled={busy}
        onChange={(event) => {
          setFile(event.target.files?.[0] ?? null);
          setError(null);
          setErrorDetail(null);
        }}
      />
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <Button
          label={t(file ? "settings.template_change_file" : "settings.template_choose_file")}
          variant="secondary"
          disabled={busy}
          onClick={() => fileInput.current?.click()}
        />
        <span className="min-w-0 flex-1 break-all text-sm text-slate-600 dark:text-slate-300" aria-live="polite">
          {file?.name}
        </span>
        {selected && (
          <Button
            label={t("settings.template_delete")}
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() => void remove()}
          />
        )}
      </div>
      {file && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label htmlFor={nameId} className="block min-w-0 flex-1 space-y-1.5 text-sm">
            <span className="block">{t("settings.template_name")}</span>
            <input
              id={nameId}
              className={workstationInputClass}
              placeholder={file.name.replace(/\.3mf$/i, "")}
              value={name}
              maxLength={100}
              disabled={busy}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <Button label={t("settings.template_import")} loading={busy} onClick={() => void upload()} />
        </div>
      )}
      {error && <StatusBanner tone="error">{t(error)}{errorDetail ? ` ${errorDetail}` : ""}</StatusBanner>}
    </div>
  );
}
