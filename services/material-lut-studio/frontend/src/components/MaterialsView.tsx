import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n/useT";
import {
  materialDirName,
  materialDisplayName,
  useMaterialsStore,
} from "../stores/materialsStore";
import type { MaterialSummary } from "../api/types";
import { Button, Card, EmptyState, ErrorBanner, Spinner, Swatch, Toast } from "./ui";

function estimatedHex(m: MaterialSummary): string | null {
  const rgb = m.estimated_rgb;
  if (Array.isArray(rgb) && rgb.length >= 3) {
    const [r, g, b] = rgb;
    return `#${[r, g, b]
      .map((v) => Math.max(0, Math.min(255, Number(v))).toString(16).padStart(2, "0"))
      .join("")}`;
  }
  return null;
}

export function MaterialsView() {
  const t = useT();
  const {
    materials,
    loading,
    error,
    selected,
    load,
    toggleSelect,
    toggleSelectAll,
    remove,
    exportSelected,
    importArchives,
  } = useMaterialsStore();
  const [toast, setToast] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDelete = async (m: MaterialSummary) => {
    const name = materialDisplayName(m);
    if (!window.confirm(t("materials_delete_confirm", { name }))) return;
    setBusy(true);
    try {
      await remove(materialDirName(m));
      setToast(t("materials_deleted", { name }));
    } finally {
      setBusy(false);
    }
  };

  const handleExport = async () => {
    if (selected.size === 0) {
      setToast(t("materials_no_selection"));
      return;
    }
    setBusy(true);
    try {
      const url = await exportSelected();
      if (url) {
        window.open(url, "_blank");
        setToast(t("materials_exported", { count: selected.size }));
      }
    } finally {
      setBusy(false);
    }
  };

  const handleImport = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    try {
      const arr = Array.from(files);
      await importArchives(arr);
      setToast(t("materials_imported", { count: arr.length }));
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const allNames = materials.map(materialDirName).filter(Boolean);
  const allSelected = allNames.length > 0 && selected.size === allNames.length;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("materials_title")}</h2>
          <p className="text-sm text-[var(--text-muted)]">
            {t("materials_count", { count: materials.length })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={() => load()} disabled={loading || busy}>
            {t("common_refresh")}
          </Button>
          <Button variant="secondary" onClick={handleExport} disabled={busy || selected.size === 0}>
            {t("materials_export_selected")}
          </Button>
          <Button
            variant="primary"
            onClick={() => fileInputRef.current?.click()}
            disabled={busy}
          >
            {t("materials_import")}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip"
            multiple
            className="hidden"
            onChange={(e) => handleImport(e.target.files)}
          />
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => load()} retryLabel={t("common_retry")} />}

      <Card className="overflow-hidden">
        {loading ? (
          <div className="p-6">
            <Spinner label={t("common_loading")} />
          </div>
        ) : materials.length === 0 ? (
          <EmptyState text={t("common_empty")} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--surface-muted)] text-left text-[var(--text-muted)]">
                <th className="w-10 px-3 py-2">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => toggleSelectAll()}
                    aria-label={t("materials_select_all")}
                  />
                </th>
                <th className="px-3 py-2">{t("materials_col_color")}</th>
                <th className="px-3 py-2">{t("materials_col_name")}</th>
                <th className="px-3 py-2">{t("materials_col_brand")}</th>
                <th className="px-3 py-2 text-right">{t("materials_col_actions")}</th>
              </tr>
            </thead>
            <tbody>
              {materials.map((m) => {
                const dir = materialDirName(m);
                return (
                  <tr
                    key={dir}
                    className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--surface-muted)]"
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(dir)}
                        onChange={() => toggleSelect(dir)}
                        aria-label={dir}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <Swatch hex={estimatedHex(m)} />
                    </td>
                    <td className="px-3 py-2 font-medium">{materialDisplayName(m)}</td>
                    <td className="px-3 py-2 text-[var(--text-muted)]">
                      {String(m.brand ?? "—")}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button variant="danger" onClick={() => handleDelete(m)} disabled={busy}>
                        {t("common_delete")}
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>

      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
    </div>
  );
}
