import { useEffect } from "react";
import { useT } from "./i18n/useT";
import { useUiStore, type ViewKey } from "./stores/uiStore";
import { MaterialsView } from "./components/MaterialsView";
import { LutView } from "./components/LutView";
import { SolverCacheView } from "./components/SolverCacheView";

function NavTab({ view, label }: { view: ViewKey; label: string }) {
  const current = useUiStore((s) => s.view);
  const setView = useUiStore((s) => s.setView);
  const active = current === view;
  return (
    <button
      onClick={() => setView(view)}
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
        active
          ? "bg-[var(--accent)] text-[var(--accent-contrast)]"
          : "text-[var(--text-muted)] hover:bg-[var(--surface-muted)] hover:text-[var(--text)]"
      }`}
    >
      {label}
    </button>
  );
}

export default function App() {
  const t = useT();
  const view = useUiStore((s) => s.view);
  const theme = useUiStore((s) => s.theme);
  const language = useUiStore((s) => s.language);
  const toggleTheme = useUiStore((s) => s.toggleTheme);
  const toggleLanguage = useUiStore((s) => s.toggleLanguage);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 border-b border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div>
            <h1 className="text-base font-semibold">{t("app_title")}</h1>
            <p className="text-xs text-[var(--text-muted)]">{t("app_subtitle")}</p>
          </div>
          <nav className="flex items-center gap-1">
            <NavTab view="materials" label={t("nav_materials")} />
            <NavTab view="lut" label={t("nav_lut")} />
            <NavTab view="solver_cache" label={t("nav_solver_cache")} />
          </nav>
          <div className="flex items-center gap-2">
            <button
              onClick={toggleLanguage}
              className="rounded-md border border-[var(--border)] px-2 py-1 text-xs text-[var(--text-muted)] hover:text-[var(--text)]"
            >
              {language === "zh" ? "EN" : "中文"}
            </button>
            <button
              onClick={toggleTheme}
              className="rounded-md border border-[var(--border)] px-2 py-1 text-xs text-[var(--text-muted)] hover:text-[var(--text)]"
              aria-label="toggle theme"
            >
              {theme === "light" ? "🌙" : "☀️"}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">
        {view === "materials" && <MaterialsView />}
        {view === "lut" && <LutView />}
        {view === "solver_cache" && <SolverCacheView />}
      </main>
    </div>
  );
}
