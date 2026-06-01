/**
 * SubTabBar - Secondary tab bar rendered inside the main content area.
 * 二级标签栏，在主内容区内部渲染。
 *
 * Placed below the header so its height changes never affect the header,
 * eliminating layout shifts / bouncing at the top of the viewport.
 * 放在顶栏下方，其高度变化不影响顶栏，消除画面抖动。
 *
 * Only the converter tab keeps an in-app secondary tab row. The LUT / material
 * secondary tabs were removed when those workflows moved to the standalone
 * Material-LUT Studio (MLS) service (Route B).
 * 现在只有转换器标签保留应用内二级标签行；LUT/耗材二级标签随相关流程迁移到
 * 独立的 Material-LUT Studio (MLS) 服务而移除。
 */
import { useI18n } from '../../i18n/context';
import type { TabId, ConverterSubTabId } from '../../types/widget';
import { resolvePrimaryTab } from './TabNavBar';
import { useWidgetStore } from '../../stores/widgetStore';
import { motion } from 'framer-motion';

const CONVERTER_SUB_TAB_ICONS: Record<ConverterSubTabId, React.ReactNode> = {
  core: (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
  color: (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
    </svg>
  ),
  advanced: (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
    </svg>
  ),
};

const CONVERTER_SUB_TAB_LIST: { id: ConverterSubTabId; titleKey: string }[] = [
  { id: 'core', titleKey: 'tab.converterCore' },
  { id: 'color', titleKey: 'tab.converterColor' },
  { id: 'advanced', titleKey: 'tab.converterAdvanced' },
];

interface SubTabBarProps {
  activeTab: TabId;
  compact?: boolean;
}

export default function SubTabBar({ activeTab, compact = false }: SubTabBarProps) {
  const { t } = useI18n();
  const primaryTab = resolvePrimaryTab(activeTab);
  const activeConverterSubTab = useWidgetStore((s) => s.activeConverterSubTab);
  const setActiveConverterSubTab = useWidgetStore((s) => s.setActiveConverterSubTab);

  if (primaryTab !== 'converter') {
    return null;
  }

  return (
    <nav
      role="tablist"
      className={`dock-scrollbar flex max-w-full items-center overflow-x-auto border border-slate-200/80 bg-slate-100/90 dark:border-slate-800/80 dark:bg-slate-900/90 ${compact ? "rounded-[20px] p-1" : "rounded-2xl p-1.5"}`}
    >
      <div className="flex min-w-max items-center gap-1">
        {CONVERTER_SUB_TAB_LIST.map(({ id, titleKey }) => {
          const isActive = id === activeConverterSubTab;
          return (
            <button
              key={id}
              role="tab"
              aria-selected={isActive}
              data-testid={`subtab-converter-${id}`}
              onClick={() => setActiveConverterSubTab(id)}
              className={`
                relative z-10 shrink-0 rounded-xl font-semibold tracking-wide transition-colors duration-300 outline-none
                ${compact ? "px-2.5 py-2 text-xs sm:px-3" : "px-3 py-2 text-sm sm:px-4"}
                ${isActive ? 'text-blue-700 dark:text-blue-400' : 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200'}
              `}
              style={{ WebkitTapHighlightColor: 'transparent' }}
            >
              {isActive && (
                <motion.div
                  layoutId="active-converter-sub-tab-indicator"
                  className="absolute inset-0 rounded-xl border border-slate-200/80 bg-slate-100/95 dark:border-slate-700/80 dark:bg-slate-900/85"
                  transition={{ type: 'spring', bounce: 0.2, duration: 0.5 }}
                  style={{ zIndex: -1 }}
                />
              )}
              <span className="relative z-10 flex items-center gap-2">
                <span className="flex items-center justify-center">{CONVERTER_SUB_TAB_ICONS[id]}</span>
                <span className={`whitespace-nowrap ${compact ? "hidden sm:inline" : ""}`}>{t(titleKey)}</span>
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
