import { useId, useState } from "react";

import type { MaterialSyncInstalledEntry } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { tRuntime } from "../../i18n/runtime";
import Button from "../ui/Button";
import { ChevronDown, HistoryIcon } from "../ui/icons";
import { cardClass, cardDividerClass, cx } from "../ui/panelPrimitives";
import { resolveRollbackRevisions, shortRevisionLabel } from "./catalogModel";

interface MaterialCloudLocalRevisionsProps {
  entries: MaterialSyncInstalledEntry[];
  pendingRollback: string | null;
  formatDate: (value: string | null | undefined) => string;
  onRollback: (entry: MaterialSyncInstalledEntry, revisionId: string) => void;
}

/**
 * Collapsible notice listing updated local materials that keep older revisions.
 * 可折叠的本地版本记录提示：列出已更新且保留旧版本、可回滚的耗材。
 */
export default function MaterialCloudLocalRevisions({
  entries,
  pendingRollback,
  formatDate,
  onRollback,
}: MaterialCloudLocalRevisionsProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const listId = useId();

  if (entries.length === 0) {
    return null;
  }

  return (
    <section
      data-testid="material-cloud-local-installed-section"
      className={`${cardClass} px-4 py-3`}
    >
      <button
        type="button"
        data-testid="material-cloud-local-toggle"
        aria-expanded={expanded}
        aria-controls={listId}
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full min-w-0 items-center gap-3 rounded-[10px] text-left focus:outline-none focus-visible:ring-4 focus-visible:ring-[var(--focus-ring)]"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-50 text-blue-600 dark:bg-blue-500/15 dark:text-blue-300">
          <HistoryIcon />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_sync_local_section_title")}
            <span className="rounded-full bg-blue-100 px-2 text-[11px] font-semibold leading-5 text-blue-700 dark:bg-blue-400/15 dark:text-blue-200">
              {entries.length}
            </span>
          </span>
          <span className="mt-0.5 block truncate text-xs text-slate-500 dark:text-slate-400">
            {t("mat_sync_local_section_hint")}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-slate-500 dark:text-slate-400">
          <span className="hidden sm:inline">
            {t(expanded ? "mat_sync_local_section_collapse" : "mat_sync_local_section_expand")}
          </span>
          <ChevronDown className={cx("h-4 w-4 transition-transform", expanded && "rotate-180")} />
        </span>
      </button>

      {expanded ? (
        <ul id={listId} className={`${cardDividerClass} mt-3 grid divide-y divide-[var(--surface-divider)]`}>
          {entries.map((installed) => {
            const displayName = installed.display_name || installed.local_directory || installed.material_id;
            const updatedAt = installed.updated_at ?? installed.installed_at;
            return (
              <li
                key={installed.material_id}
                data-testid="material-cloud-local-installed-card"
                className="grid gap-2 py-2.5 last:pb-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
              >
                <div className="min-w-0">
                  <p className="flex min-w-0 items-baseline gap-2">
                    <span className="truncate text-sm font-medium text-slate-900 dark:text-slate-50">
                      {displayName}
                    </span>
                    {installed.display_brand ? (
                      <span className="shrink-0 text-xs text-slate-500 dark:text-slate-400">
                        {installed.display_brand}
                      </span>
                    ) : null}
                  </p>
                  <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                    {tRuntime("mat_sync_local_current_revision", {
                      revision: shortRevisionLabel(installed.revision_id),
                      time: formatDate(updatedAt),
                    })}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 sm:justify-end">
                  {resolveRollbackRevisions(installed).map((revisionId) => (
                    <Button
                      key={revisionId}
                      size="sm"
                      variant="primary"
                      title={revisionId}
                      label={tRuntime("mat_sync_rollback_btn", {
                        revisionId: shortRevisionLabel(revisionId),
                      })}
                      onClick={() => onRollback(installed, revisionId)}
                      disabled={pendingRollback !== null}
                      loading={pendingRollback === `${installed.material_id}:${revisionId}`}
                    />
                  ))}
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
