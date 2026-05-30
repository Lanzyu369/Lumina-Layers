import { useEffect, useState } from "react";
import { useT } from "../i18n/useT";
import { useSolverCacheStore } from "../stores/solverCacheStore";
import type { SolverCacheEntry } from "../api/types";
import { Button, Card, EmptyState, ErrorBanner, Spinner, Toast } from "./ui";

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function SolverCacheView() {
  const t = useT();
  const { entries, loading, error, load, remove } = useSolverCacheStore();
  const [toast, setToast] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDelete = async (entry: SolverCacheEntry) => {
    if (!window.confirm(t("solver_cache_delete_confirm"))) return;
    setBusy(true);
    try {
      await remove(entry);
      setToast(t("solver_cache_deleted"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("solver_cache_title")}</h2>
          <p className="text-sm text-[var(--text-muted)]">
            {t("solver_cache_count", { count: entries.length })}
          </p>
        </div>
        <Button onClick={() => load()} disabled={loading || busy}>
          {t("common_refresh")}
        </Button>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => load()} retryLabel={t("common_retry")} />}

      <Card className="overflow-x-auto">
        {loading ? (
          <div className="p-6">
            <Spinner label={t("common_loading")} />
          </div>
        ) : entries.length === 0 ? (
          <EmptyState text={t("common_empty")} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--surface-muted)] text-left text-[var(--text-muted)]">
                <th className="px-3 py-2">{t("solver_cache_col_palette")}</th>
                <th className="px-3 py-2">{t("solver_cache_col_materials")}</th>
                <th className="px-3 py-2">{t("solver_cache_col_layers")}</th>
                <th className="px-3 py-2">{t("solver_cache_col_height")}</th>
                <th className="px-3 py-2">{t("solver_cache_col_substrate")}</th>
                <th className="px-3 py-2">{t("solver_cache_col_grid")}</th>
                <th className="px-3 py-2">{t("solver_cache_col_cells")}</th>
                <th className="px-3 py-2">{t("solver_cache_col_de")}</th>
                <th className="px-3 py-2">{t("solver_cache_col_size")}</th>
                <th className="px-3 py-2 text-right">{t("materials_col_actions")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e, idx) => (
                <tr
                  key={`${e.palette_hash}-${e.layer_count}-${e.substrate}-${e.grid_resolution}-${idx}`}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--surface-muted)]"
                >
                  <td className="px-3 py-2 font-mono text-xs">{e.palette_hash.slice(0, 12)}</td>
                  <td className="px-3 py-2">{e.material_directory_names.length}</td>
                  <td className="px-3 py-2">{e.layer_count}</td>
                  <td className="px-3 py-2">{e.layer_height_mm}</td>
                  <td className="px-3 py-2">{e.substrate}</td>
                  <td className="px-3 py-2">{e.grid_resolution}</td>
                  <td className="px-3 py-2">
                    {e.valid_cell_count}/{e.total_cell_count}
                  </td>
                  <td className="px-3 py-2">{e.mean_delta_e.toFixed(2)}</td>
                  <td className="px-3 py-2">{formatBytes(e.cache_file_size_bytes)}</td>
                  <td className="px-3 py-2 text-right">
                    <Button variant="danger" onClick={() => handleDelete(e)} disabled={busy}>
                      {t("common_delete")}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
    </div>
  );
}
