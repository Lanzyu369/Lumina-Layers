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
              active && "bg-[var(--nav-tab-selected-bg)]",
            )}
          >
              {category.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
