import type { ReactNode } from "react";

import type { MaterialRegistryCatalogEntry } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { tRuntime } from "../../i18n/runtime";
import Button from "../ui/Button";
import { cx, wellClass } from "../ui/panelPrimitives";
import {
  FIT_ERROR_EXCELLENT_THRESHOLD,
  FIT_ERROR_HIGH_THRESHOLD,
  formatBytes,
  resolveCatalogChannel,
  resolveCatalogDisplay,
  resolveCatalogFitError,
  shortContentFingerprint,
  toHex,
  toRgbCss,
} from "./catalogModel";
import type {
  CatalogChannel,
  CatalogInstallState,
} from "./catalogModel";

interface MaterialCloudCatalogCardProps {
  entry: MaterialRegistryCatalogEntry;
  installState: CatalogInstallState;
  isInstalling: boolean;
  installDisabled: boolean;
  onInstall: (entry: MaterialRegistryCatalogEntry) => void;
}

const chipClass =
  "inline-flex max-w-full shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold leading-5";

const channelChipClass: Record<CatalogChannel, string> = {
  official: "bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-100",
  community: "bg-sky-100 text-sky-800 dark:bg-sky-400/15 dark:text-sky-100",
  team: "bg-violet-100 text-violet-800 dark:bg-violet-400/15 dark:text-violet-100",
  other: "bg-slate-200/70 text-slate-700 dark:bg-slate-700/60 dark:text-slate-200",
};

const channelDotClass: Record<CatalogChannel, string> = {
  official: "bg-amber-500",
  community: "bg-sky-500",
  team: "bg-violet-500",
  other: "bg-slate-400",
};

const installStateChipClass: Record<CatalogInstallState, string> = {
  installed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-400/15 dark:text-emerald-100",
  update_available: "bg-blue-100 text-blue-800 dark:bg-blue-400/15 dark:text-blue-100",
  local_available: "bg-slate-200/70 text-slate-700 dark:bg-slate-700/60 dark:text-slate-200",
  local_missing: "bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-100",
  not_installed: "bg-slate-200/70 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300",
};

function MetaItem({
  label,
  children,
  testId = "material-cloud-card-meta",
}: {
  label: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div data-testid={testId} className="min-w-0">
      <dt className="text-[11px] font-medium text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="mt-0.5 min-w-0 text-sm font-semibold text-slate-900 dark:text-slate-50">
        {children}
      </dd>
    </div>
  );
}

/**
 * One cloud catalog entry: identity, publish channel, fit error, and install action.
 * 单个云端耗材卡片：名称、发布频道、拟合误差与安装操作。
 */
export default function MaterialCloudCatalogCard({
  entry,
  installState,
  isInstalling,
  installDisabled,
  onInstall,
}: MaterialCloudCatalogCardProps) {
  const { t } = useI18n();
  const display = resolveCatalogDisplay(entry);
  const channel = resolveCatalogChannel(entry);
  const fitError = resolveCatalogFitError(entry);
  const channelLabel = channel === "other"
    ? entry.channel || t("mat_sync_state_unknown")
    : t(`mat_sync_channel_${channel}`);
  const subtitle = [
    display.brand || t("mat_gradient_library_brand_unassigned"),
    display.materialType,
    display.rgb ? toHex(display.rgb) : "",
  ].filter(Boolean);
  const fitErrorDetail = [
    fitError.verificationCount !== null
      ? tRuntime("mat_sync_fit_error_verifications", { count: fitError.verificationCount })
      : "",
    fitError.layerHeightMm !== null ? `${fitError.layerHeightMm} mm` : "",
  ].filter(Boolean).join(" · ");

  const renderAction = () => {
    if (installState === "installed" || installState === "local_available") {
      return (
        <Button
          label={t(installState === "installed" ? "mat_sync_installed_btn" : "mat_sync_local_available_btn")}
          variant="secondary"
          disabled
          className="w-full"
        />
      );
    }
    const label = installState === "update_available"
      ? tRuntime("mat_sync_update_btn", { revisionId: shortContentFingerprint(entry) })
      : t("mat_sync_install_btn");
    return (
      <Button
        label={label}
        onClick={() => onInstall(entry)}
        disabled={installDisabled}
        loading={isInstalling}
        className="w-full"
      />
    );
  };

  return (
    <article
      data-testid="material-cloud-catalog-card"
      data-channel={channel}
      className={`${wellClass} flex min-w-0 flex-col gap-4 p-4`}
    >
      <header className="flex min-w-0 items-start gap-3">
        <div
          data-testid="material-cloud-catalog-swatch"
          className={cx(
            "flex h-14 w-14 shrink-0 items-center justify-center rounded-lg text-lg font-semibold text-slate-500 ring-1 ring-inset ring-slate-900/10 dark:text-slate-300 dark:ring-white/10",
            display.rgb ? "" : "bg-slate-200/70 dark:bg-slate-700/60",
          )}
          style={display.rgb ? { backgroundColor: toRgbCss(display.rgb) } : undefined}
          aria-hidden="true"
        >
          {display.rgb ? null : display.name.trim().slice(0, 1).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-start justify-between gap-2">
            <h3
              className="line-clamp-2 min-w-0 break-words text-sm font-semibold leading-5 text-slate-900 dark:text-slate-50"
              title={display.name}
            >
              {display.name}
            </h3>
            <span
              data-testid="material-cloud-channel-badge"
              title={`${t("mat_sync_channel_label")}: ${channelLabel}`}
              className={cx(chipClass, channelChipClass[channel])}
            >
              <span aria-hidden="true" className={cx("h-1.5 w-1.5 rounded-full", channelDotClass[channel])} />
              <span className="truncate">{channelLabel}</span>
            </span>
          </div>
          <p className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-1.5 text-xs text-slate-500 dark:text-slate-400">
            <span data-testid="material-cloud-brand-tag" className="truncate font-medium text-slate-600 dark:text-slate-300">
              {subtitle[0]}
            </span>
            {subtitle.slice(1).map((part, index) => (
              <span key={index} className="truncate">· {part}</span>
            ))}
          </p>
          <p
            className="mt-1 truncate font-mono text-[11px] text-slate-400 dark:text-slate-500"
            title={entry.local_directory}
          >
            {entry.local_directory}
          </p>
        </div>
      </header>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        <MetaItem label={t("mat_sync_fit_error_label")}>
          <span
            data-testid="material-cloud-fit-error"
            data-grade={fitError.grade}
            title={tRuntime("mat_sync_fit_error_hint", {
              excellent: FIT_ERROR_EXCELLENT_THRESHOLD.toFixed(1),
              high: FIT_ERROR_HIGH_THRESHOLD.toFixed(1),
            })}
            className="flex items-baseline gap-1.5 font-normal text-slate-700 dark:text-slate-200"
          >
            {fitError.meanDeltaE !== null ? (
              <>
                <span className="tabular-nums">
                  {tRuntime("mat_sync_fit_error_value", { value: fitError.meanDeltaE.toFixed(2) })}
                </span>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                  {t(`mat_sync_fit_error_grade_${fitError.grade}`)}
                </span>
              </>
            ) : (
              <span className="text-xs text-slate-500 dark:text-slate-400">{t("mat_sync_fit_error_missing")}</span>
            )}
          </span>
          {fitErrorDetail ? (
            <span className="mt-0.5 block truncate text-[11px] font-normal text-slate-500 dark:text-slate-400">
              {fitErrorDetail}
            </span>
          ) : null}
        </MetaItem>
        <MetaItem label={t("mat_sync_catalog_state_label")}>
          <span
            data-testid={`material-cloud-state-${entry.material_id}`}
            className={cx(chipClass, installStateChipClass[installState])}
          >
            {t(`mat_sync_catalog_state_${installState}`)}
          </span>
        </MetaItem>
        <MetaItem label={t("mat_sync_package_size_label")}>
          <span className="tabular-nums">{formatBytes(entry.package_bytes)}</span>
        </MetaItem>
        <MetaItem label={t("mat_sync_content_fingerprint_label")}>
          <span className="block truncate font-mono text-xs" title={entry.content_hash}>
            {shortContentFingerprint(entry)}
          </span>
        </MetaItem>
      </dl>

      <div className="mt-auto">{renderAction()}</div>
    </article>
  );
}
