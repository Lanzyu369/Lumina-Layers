
import { useI18n } from "../i18n/context";
import { CATALOG_FILTERS, catalogEntryKey } from "./materialCloud/catalogModel";
import {
  useMaterialCloudCatalog,
} from "./materialCloud/useMaterialCloudCatalog";
import Button from "./ui/Button";
import Pagination from "./ui/Pagination";
import {
  StatusBanner,
  wellClass,
} from "./ui/panelPrimitives";

const SKELETON_CARD_COUNT = 6;
const CATALOG_GRID_CLASS =
  "grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,17.5rem),1fr))]";

function CatalogSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className={CATALOG_GRID_CLASS}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: SKELETON_CARD_COUNT }, (_, index) => (
        <div key={index} aria-hidden="true" className={`${wellClass} flex animate-pulse flex-col gap-4 p-4`}>
          <div className="flex gap-3">
            <div className="h-14 w-14 rounded-lg bg-slate-300/50 dark:bg-slate-600/40" />
            <div className="flex-1 space-y-2 pt-1">
              <div className="h-3 w-3/4 rounded bg-slate-300/50 dark:bg-slate-600/40" />
              <div className="h-3 w-1/2 rounded bg-slate-300/40 dark:bg-slate-600/30" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {Array.from({ length: 4 }, (__, cell) => (
              <div key={cell} className="h-8 rounded bg-slate-300/40 dark:bg-slate-600/30" />
            ))}
          </div>
          <div className="h-11 rounded-[10px] bg-slate-300/40 dark:bg-slate-600/30" />
        </div>
      ))}
    </div>
  );
}

/**
 * Cloud material library page: browse the Registry catalog page by page,
 * install or update materials, and roll back local revisions.
 * 云端耗材库页面：分页浏览 Registry 目录，安装/更新耗材，回滚本地版本。
 */
export default function MaterialCloudSyncPanel() {
  const catalog = useMaterialCloudCatalog();
  const { dismissSuccess, success, view } = catalog;
  const handlePageChange = useCallback((nextPage: number) => {
    void catalog.goToPage(nextPage);
  }, [catalog]);

  const isListBusy = catalog.isLoading || catalog.isPageLoading || catalog.isSearchPending;
  const paginationDisabled = isListBusy || catalog.pendingInstall !== null;

  const renderCatalogBody = () => {
    if (view.kind === "loading") {
      return <CatalogSkeleton label={t("mat_gradient_library_loading")} />;
    }
    if (view.kind === "full_catalog_failed") {
      return (
        <StatusBanner
          data-testid="material-cloud-full-catalog-failed"
          tone="warning"
          action={(
            <Button
              label={t("mat_sync_full_catalog_retry_btn")}
              size="sm"
              onClick={catalog.retryFullCatalog}
            />
          )}
        >
          {t("mat_sync_full_catalog_failed")}
        </StatusBanner>
      );
    }
  };

        </div>
}
