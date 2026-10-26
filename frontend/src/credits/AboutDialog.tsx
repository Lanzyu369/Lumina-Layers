import { useCallback, useEffect, useRef, useState } from "react";
import { version as webVersion } from "../../package.json";
import { useI18n } from "../i18n/context";
import { useDialogFocusTrap } from "../hooks/useDialogFocusTrap";
import { electronAPI } from "../integrations/electron";
import Button from "../components/ui/Button";
import CloseButton from "../components/ui/CloseButton";
import CreditsGarden from "./CreditsGarden";
import { useCreditsCatalog } from "./useCreditsCatalog";

export type AboutPage = "about" | "credits";

export default function AboutDialog({ page, onNavigate, onClose }: {
  page: AboutPage;
  onNavigate: (page: AboutPage) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const rootRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const creditsRef = useRef<HTMLButtonElement>(null);
  const previousPage = useRef(page);
  const [version, setVersion] = useState(webVersion);
  const closePage = useCallback(() => {
    if (page === "credits") onNavigate("about");
    else onClose();
  }, [page, onNavigate, onClose]);
  useEffect(() => {
    let active = true;
    void electronAPI?.getAppVersion?.().then(value => {
      if (active && value) setVersion(value);
    }).catch(() => { /* Keep the web build version if the desktop host is unavailable. */ });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (page === previousPage.current) return;
    if (page === "about") creditsRef.current?.focus();
    else closeRef.current?.focus();
    previousPage.current = page;
  }, [page]);
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
        closePage();
      } else if (event.key === "/" && page === "credits") {
        event.preventDefault();
        root.querySelector<HTMLInputElement>('[role="combobox"]')?.focus();
      } else {
        root.focus({ preventScroll: true });
      }
    };
    document.addEventListener("keydown", guardOutsideKeys, true);
    return () => document.removeEventListener("keydown", guardOutsideKeys, true);
  }, [closePage, page]);

  return (
    <section ref={rootRef} role="dialog" aria-modal="true" aria-label={t(page === "credits" ? "credits_title" : "desktop_menu_about")} tabIndex={-1}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Escape" && !event.defaultPrevented) {
          event.preventDefault();
          closePage();
        }
      }}
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
          <h2 className="text-base font-semibold tracking-tight">{t(page === "credits" ? "credits_title" : "desktop_menu_about")}</h2>
        </div>
        <div className="desktop-titlebar-controls">
          <CloseButton ref={closeRef} label={t(page === "credits" ? "credits_close" : "about_close")} onClick={closePage} />
        </div>
      </header>
      {page === "credits" ? <CreditsPage /> : (
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto overscroll-y-contain p-6">
          <div className="flex max-w-lg flex-col items-center gap-5 text-center">
            <img src="/favicon.ico" alt="" draggable={false} className="h-20 w-20" />
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{t("about_name")}</h1>
              <p className="mt-2 text-sm text-[var(--surface-text-muted)]">{t("about_version").replace("{version}", () => version)}</p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-3">
              <a className="ghost-control rounded-lg px-3 py-2 text-sm" href="https://luminastudio.com.cn/" target="_blank" rel="noreferrer">{t("about_website")}</a>
              <a className="ghost-control rounded-lg px-3 py-2 text-sm" href="https://github.com/lumina-layer-studio/Lumina-studio" target="_blank" rel="noreferrer">{t("about_github")}</a>
              <button ref={creditsRef} type="button" className="ghost-control rounded-lg px-3 py-2 text-sm" onClick={() => onNavigate("credits")}>{t("credits_title")}</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function CreditsPage() {
  const { t } = useI18n();
  const { catalog, loading, error, reload } = useCreditsCatalog();
  return (
    <div className="flex min-h-0 flex-1 flex-col" data-credits-records={catalog?.records.length} data-credits-origin={catalog?.assetsBase}>
      {catalog?.stale && <p role="status" className="px-4 py-2 text-xs text-[var(--surface-text-muted)]">{t("credits_cached")}</p>}
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
    </div>
  );
}
