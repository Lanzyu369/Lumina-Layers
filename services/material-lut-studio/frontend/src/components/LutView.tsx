import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n/useT";
import { useLutStore } from "../stores/lutStore";
import { Button, Card, EmptyState, ErrorBanner, Spinner, Swatch, Toast } from "./ui";

function LutList() {
  const t = useT();
  const { list, listLoading, error, selectedName, loadList, selectLut, upload } =
    useLutStore();
  const [query, setQuery] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const filtered = list.filter((l) =>
    l.name.toLowerCase().includes(query.trim().toLowerCase()),
  );

  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b border-[var(--border)] p-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("common_search")}
          className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-sm outline-none focus:border-[var(--accent)]"
        />
        <Button variant="primary" onClick={() => fileInputRef.current?.click()}>
          {t("lut_upload")}
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".npy,.json,.npz,.msgpack"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
            if (fileInputRef.current) fileInputRef.current.value = "";
          }}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {listLoading ? (
          <div className="p-4">
            <Spinner label={t("common_loading")} />
          </div>
        ) : error ? (
          <div className="p-3">
            <ErrorBanner message={error} onRetry={() => loadList()} retryLabel={t("common_retry")} />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState text={t("common_empty")} />
        ) : (
          <ul>
            {filtered.map((l) => (
              <li key={l.name}>
                <button
                  onClick={() => selectLut(l.name)}
                  className={`flex w-full items-center justify-between gap-2 border-b border-[var(--border)] px-3 py-2 text-left text-sm hover:bg-[var(--surface-muted)] ${
                    selectedName === l.name ? "bg-[var(--surface-muted)]" : ""
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate">{l.name}</span>
                  <span className="shrink-0 rounded bg-[var(--bg)] px-1.5 py-0.5 text-xs text-[var(--text-muted)]">
                    {l.color_mode}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

function LutDetail() {
  const t = useT();
  const { selectedName, selectedInfo, infoLoading } = useLutStore();

  if (!selectedName) {
    return (
      <Card className="flex h-full items-center justify-center">
        <p className="px-6 text-center text-sm text-[var(--text-muted)]">
          {t("lut_select_hint")}
        </p>
      </Card>
    );
  }

  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <div className="border-b border-[var(--border)] p-3">
        <h3 className="truncate font-semibold">{selectedName}</h3>
        {selectedInfo && (
          <p className="text-sm text-[var(--text-muted)]">
            {selectedInfo.color_mode} · {t("lut_col_count")}: {selectedInfo.color_count}
          </p>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {infoLoading ? (
          <Spinner label={t("common_loading")} />
        ) : !selectedInfo ? (
          <EmptyState text={t("common_empty")} />
        ) : (
          <div>
            <h4 className="mb-2 text-sm font-medium text-[var(--text-muted)]">
              {t("lut_detail_title")}
            </h4>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {selectedInfo.palette.map((entry, idx) => (
                <div
                  key={`${entry.color}-${idx}`}
                  className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
                >
                  <Swatch hex={entry.hex_color} size={24} />
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">
                      {entry.color_name || entry.color}
                    </div>
                    <div className="truncate text-xs text-[var(--text-muted)]">
                      {t("lut_palette_channel")} {idx} · {entry.material}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

function ComparePanel() {
  const t = useT();
  const {
    list,
    compareA,
    compareB,
    comparing,
    compareResult,
    compareError,
    setCompareA,
    setCompareB,
    runCompare,
  } = useLutStore();

  return (
    <Card className="p-3">
      <h3 className="mb-3 font-semibold">{t("lut_compare_title")}</h3>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          {t("lut_compare_a")}
          <select
            value={compareA}
            onChange={(e) => setCompareA(e.target.value)}
            className="min-w-48 rounded-md border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-sm text-[var(--text)]"
          >
            <option value="">—</option>
            {list.map((l) => (
              <option key={l.name} value={l.name}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          {t("lut_compare_b")}
          <select
            value={compareB}
            onChange={(e) => setCompareB(e.target.value)}
            className="min-w-48 rounded-md border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-sm text-[var(--text)]"
          >
            <option value="">—</option>
            {list.map((l) => (
              <option key={l.name} value={l.name}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="primary"
          onClick={() => runCompare()}
          disabled={comparing || !compareA || !compareB}
        >
          {t("lut_compare_run")}
        </Button>
      </div>

      {compareError && (
        <div className="mt-3">
          <ErrorBanner message={compareError} />
        </div>
      )}

      {comparing && (
        <div className="mt-3">
          <Spinner label={t("common_loading")} />
        </div>
      )}

      {compareResult && !comparing && (
        <div className="mt-4 grid grid-cols-3 gap-3">
          <Metric label={t("lut_compare_matched")} value={compareResult.stats.matched_recipe_count} />
          <Metric
            label={t("lut_compare_mean_de")}
            value={compareResult.stats.mean_delta_e00.toFixed(2)}
          />
          <Metric
            label={t("lut_compare_max_de")}
            value={compareResult.stats.max_delta_e00.toFixed(2)}
          />
        </div>
      )}
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg)] p-3 text-center">
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-xs text-[var(--text-muted)]">{label}</div>
    </div>
  );
}

export function LutView() {
  const t = useT();
  const { list, notice, clearNotice } = useLutStore();

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold">{t("lut_title")}</h2>
        <p className="text-sm text-[var(--text-muted)]">
          {t("lut_count", { count: list.length })}
        </p>
      </div>
      <div className="grid h-[420px] grid-cols-1 gap-4 lg:grid-cols-2">
        <LutList />
        <LutDetail />
      </div>
      <ComparePanel />
      {notice && <Toast message={t("lut_uploaded", { name: notice })} onClose={clearNotice} />}
    </div>
  );
}
