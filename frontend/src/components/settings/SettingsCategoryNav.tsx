import { cx } from "../ui/panelPrimitives";

export type SettingsCategoryId =
  | "device"
  | "general"
  | "conversion"
  | "maintenance";

export interface SettingsCategory {
  id: SettingsCategoryId;
  label: string;
  description: string;
}

interface SettingsCategoryNavProps {
  ariaLabel: string;
  categories: SettingsCategory[];
  activeCategory: SettingsCategoryId;
  onChange: (category: SettingsCategoryId) => void;
}

/**
 * Responsive navigation for the settings information architecture.
 * 设置页信息架构的响应式分类导航。
 */
export default function SettingsCategoryNav({
  ariaLabel,
  categories,
  activeCategory,
  onChange,
}: SettingsCategoryNavProps) {
  return (
    <nav
      aria-label={ariaLabel}
      data-testid="settings-category-nav"
      className="dock-scrollbar flex min-w-0 gap-2 overflow-x-auto rounded-[24px] border border-slate-200/75 bg-slate-100/65 p-2 dark:border-slate-700/75 dark:bg-slate-900/55 lg:sticky lg:top-0 lg:flex-col lg:self-start lg:overflow-visible"
    >
      {categories.map((category) => {
        const active = category.id === activeCategory;
        return (
          <button
            key={category.id}
            id={`settings-category-${category.id}`}
            type="button"
            data-testid={`settings-category-${category.id}`}
            aria-current={active ? "page" : undefined}
            aria-controls={`settings-category-panel-${category.id}`}
            onClick={() => onChange(category.id)}
            className={cx(
              "min-h-11 shrink-0 rounded-[18px] border px-3.5 py-2.5 text-left outline-none transition-all duration-200 focus:ring-4 focus:ring-[var(--focus-ring)] lg:w-full",
              active
                ? "border-blue-300 bg-white text-slate-900 shadow-[var(--shadow-control)] dark:border-blue-500/55 dark:bg-slate-900 dark:text-slate-50"
                : "border-transparent text-slate-600 hover:border-slate-200/80 hover:bg-white/65 hover:text-slate-900 dark:text-slate-300 dark:hover:border-slate-700/80 dark:hover:bg-slate-900/75 dark:hover:text-slate-50",
            )}
          >
            <span className="block whitespace-nowrap text-sm font-semibold">
              {category.label}
            </span>
            <span className="mt-1 hidden text-xs leading-5 text-slate-500 dark:text-slate-400 lg:block">
              {category.description}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
