import { cx } from "../ui/panelPrimitives";
import { primaryNavTabClass } from "../widget/navTabStyles";
import { AdjustmentsHorizontalIcon, Cog6ToothIcon, PrinterIcon, CircleStackIcon } from "@heroicons/react/24/outline";

const categoryIcons = {
  device: PrinterIcon,
  general: Cog6ToothIcon,
  conversion: AdjustmentsHorizontalIcon,
  maintenance: CircleStackIcon,
};

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
      className="settings-sidebar dock-scrollbar flex min-h-0 min-w-0 gap-1 overflow-x-auto border-b panel-divider p-3 sm:flex-col sm:overflow-x-hidden sm:overflow-y-auto sm:overscroll-y-contain sm:border-b-0 sm:border-r sm:py-6"
    >
      {categories.map((category) => {
        const active = category.id === activeCategory;
        const Icon = categoryIcons[category.id];
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
              "flex min-h-11 items-center gap-3 text-left sm:w-full",
              active && "bg-[var(--nav-tab-selected-bg)]",
            )}
          >
            <Icon aria-hidden="true" className="h-5 w-5 shrink-0" />
            <span className="block whitespace-nowrap text-sm font-medium">
              {category.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
