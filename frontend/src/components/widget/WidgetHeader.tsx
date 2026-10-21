/**
 * Widget header component with drag handle, collapse toggle, and ARIA support.
 * Widget 标题栏组件，支持拖拽手柄、折叠切换和 ARIA 无障碍。
 */

import type { DraggableSyntheticListeners, DraggableAttributes } from '@dnd-kit/core';
import { useI18n } from '../../i18n/context';
import type { WidgetId } from '../../types/widget';

interface WidgetHeaderProps {
  widgetId: WidgetId;
  titleKey: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
  dragListeners?: DraggableSyntheticListeners;
  dragAttributes?: DraggableAttributes;
}

export function WidgetHeader({
  titleKey,
  collapsed,
  onToggleCollapse,
  dragListeners,
  dragAttributes,
}: WidgetHeaderProps) {
  const { t } = useI18n();

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      onToggleCollapse();
    }
  };

  return (
    <div
      role="heading"
      aria-level={2}
      aria-expanded={!collapsed}
      aria-label={t(titleKey)}
      tabIndex={0}
      className="flex items-center justify-between bg-[#f7f7f8] px-3 py-1.5 cursor-grab active:cursor-grabbing select-none touch-none dark:bg-[var(--surface-well)]"
      onDoubleClick={onToggleCollapse}
      onKeyDown={handleKeyDown}
      {...dragListeners}
      {...dragAttributes}
    >
      {/* A subtle gray surface separates the header while the title stays light. */}
      <span className="truncate text-sm font-normal tracking-tight text-slate-800 dark:text-slate-50">
        {t(titleKey)}
      </span>
      <button
        type="button"
        aria-label={collapsed ? t('widget_expand') : t('widget_collapse')}
        onClick={(e) => {
          e.stopPropagation();
          onToggleCollapse();
        }}
        onPointerDown={(e) => e.stopPropagation()}
        className="ghost-control ml-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg text-slate-500 dark:text-slate-400"
      >
        <span className="text-xs">{collapsed ? '\u25B6' : '\u25BC'}</span>
      </button>
    </div>
  );
}
