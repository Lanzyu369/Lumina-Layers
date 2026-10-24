import { cx } from "../ui/panelPrimitives";
import { primaryNavTabClass } from "../widget/navTabStyles";

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
      className="dock-scrollbar flex min-h-0 min-w-0 gap-2 overflow-x-auto p-1 lg:max-h-full lg:flex-col lg:self-start lg:overflow-y-auto"
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
              primaryNavTabClass(active, false),
              "min-h-11 text-left lg:w-full",
              active && "bg-[var(--nav-tab-selected-bg)]",
            )}
          >
            <span className="block whitespace-nowrap text-sm font-semibold">
              {category.label}
            </span>
            <span className={cx(
              "mt-1 hidden text-xs leading-5 lg:block",
              active ? "text-white/90" : "text-slate-500 dark:text-slate-400",
            )}>
              {category.description}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
