import { useEffect, useRef } from "react";
import { useI18n } from "../i18n/context";
import { useDialogFocusTrap } from "../hooks/useDialogFocusTrap";
import { electronAPI } from "../integrations/electron";
import Button from "../components/ui/Button";
import CloseButton from "../components/ui/CloseButton";
import CreditsGarden from "./CreditsGarden";
import { useCreditsCatalog } from "./useCreditsCatalog";

export default function CreditsDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const rootRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const { catalog, loading, error, reload } = useCreditsCatalog();
  const mergedTitlebar = electronAPI?.platform === "darwin" || electronAPI?.platform === "win32";
  useDialogFocusTrap(rootRef, true, { initialFocus: () => closeRef.current });
  useEffect(() => {
    const guardOutsideKeys = (event: KeyboardEvent) => {
      const root = rootRef.current;
      if (!root || (event.target instanceof Node && root.contains(event.target))) return;
      // A canvas click or input blur can leave the browser's body focused.
      // Keep those events away from the retained workspace's global shortcuts.
      event.stopPropagation();
      if (event.defaultPrevented) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      } else if (event.key === "/") {
        event.preventDefault();
        root.querySelector<HTMLInputElement>('[role="combobox"]')?.focus();
      } else {
        root.focus({ preventScroll: true });
      }
    };
    document.addEventListener("keydown", guardOutsideKeys, true);
    return () => document.removeEventListener("keydown", guardOutsideKeys, true);
  }, [onClose]);

  return (
    <section ref={rootRef} role="dialog" aria-modal="true" aria-label={t("credits_title")} tabIndex={-1}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Escape" && !event.defaultPrevented) {
          event.preventDefault();
          onClose();
        }
      }}
      data-credits-records={catalog?.records.length} data-credits-origin={catalog?.assetsBase}
      className="fixed inset-0 z-[90] flex min-h-0 flex-col overflow-hidden bg-[var(--surface-panel-strong)] text-[var(--button-text)]">
      <header
        style={electronAPI?.platform === "darwin" ? {
          paddingLeft: "calc(env(titlebar-area-x, 80px) + 12px)",
        } : electronAPI?.platform === "win32" ? {
          paddingRight: "calc(100% - env(titlebar-area-x, 0px) - env(titlebar-area-width, calc(100% - 180px)) + 12px)",
          minHeight: "max(4rem, env(titlebar-area-height, 40px))",
        } : undefined}
        className={`${mergedTitlebar ? "desktop-titlebar" : ""} relative z-10 flex min-h-16 shrink-0 items-center justify-between gap-4 border-b panel-divider bg-[var(--surface-card)] px-4 lg:px-6`}>
        <div className="flex min-w-0 items-center gap-3">
          <img src="/favicon.ico" alt={t("app_logo_alt")} draggable={false} className="h-8 w-8 shrink-0 rounded" />
          <h2 className="text-base font-semibold tracking-tight">{t("credits_title")}</h2>
          {catalog?.stale && <span role="status" className="text-xs text-[var(--surface-text-muted)]">{t("credits_cached")}</span>}
        </div>
        <div className="desktop-titlebar-controls">
          <CloseButton ref={closeRef} label={t("credits_close")} onClick={onClose} />
        </div>
      </header>
      {catalog ? <CreditsGarden catalog={catalog} /> : (
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          {loading ? <p role="status" className="text-sm text-[var(--surface-text-muted)]">{t("credits_loading")}</p> : error && (
            <div role="alert" className="flex flex-col items-center gap-4">
              <p className="text-sm text-[var(--surface-text-muted)]">{t("credits_load_error")}</p>
              <Button label={t("credits_retry")} onClick={reload} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}
