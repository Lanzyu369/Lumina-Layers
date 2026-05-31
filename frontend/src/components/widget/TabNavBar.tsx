/**
 * TabNavBar - Top navigation bar for switching between TAB pages.
 * 顶部导航栏，用于切换不同 TAB 页面。
 *
 * Renders the primary tab row plus a jump entry that opens the standalone
 * Material-LUT Studio (MLS) service. The material/LUT extract / generate /
 * query / compare / manage workflows moved to MLS (Route B), so the main app
 * exposes only converter / vectorizer / settings as in-app tabs and links out
 * to MLS for everything material/LUT.
 * 渲染一级标签行，并提供一个跳转入口打开独立的 Material-LUT Studio (MLS) 服务。
 * 耗材/LUT 的提取/生成/查询/对比/管理已迁移到 MLS，主应用仅保留转换器/矢量化/
 * 设置作为应用内标签，其余耗材/LUT 功能通过跳转入口前往 MLS。
 */
import { useI18n } from '../../i18n/context';
import type { TabId } from '../../types/widget';
import { useSettingsStore, MLS_DEFAULT_BASE_URL } from '../../stores/settingsStore';
import { motion } from 'framer-motion';

// The main converter app only navigates these three top-level tabs. Other
// TabId values exist for the standalone MLS frontend's router and are never
// shown here.
// 主转换器应用只导航这三个顶级标签；其余 TabId 供 MLS 前端路由使用，此处不展示。
type PrimaryTabId = 'converter' | 'vectorizer' | 'settings';

const PRIMARY_TAB_ICONS: Record<PrimaryTabId, React.ReactNode> = {
  'converter': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  ),
  'vectorizer': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 20C4 20 8 4 12 4C16 4 20 20 20 20" />
      <circle cx="4" cy="20" r="1.5" fill="currentColor" />
      <circle cx="20" cy="20" r="1.5" fill="currentColor" />
      <circle cx="12" cy="4" r="1.5" fill="currentColor" />
    </svg>
  ),
  'settings': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
};

const MLS_ICON = (
  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" />
  </svg>
);

const PRIMARY_TAB_LIST: { id: PrimaryTabId; titleKey: string }[] = [
  { id: 'converter', titleKey: 'tab.converter' },
  { id: 'vectorizer', titleKey: 'tab.vectorizer' },
  { id: 'settings', titleKey: 'tab.settings' },
];

export function resolvePrimaryTab(activeTab: TabId): PrimaryTabId {
  if (activeTab === 'vectorizer' || activeTab === 'settings') {
    return activeTab;
  }
  // All other tabs (including the MLS-only material/LUT tabs) resolve to the
  // converter primary tab in the main app's nav.
  // 其余标签（含 MLS 专用的耗材/LUT 标签）在主应用导航中归到 converter。
  return 'converter';
}

export function hasSubTabs(activeTab: TabId): boolean {
  // Only the converter tab keeps an in-app secondary tab row now.
  // 现在只有转换器标签保留应用内二级标签行。
  return resolvePrimaryTab(activeTab) === 'converter';
}

interface TabNavBarProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  compact?: boolean;
}

export default function TabNavBar({ activeTab, onTabChange, compact = false }: TabNavBarProps) {
  const { t } = useI18n();
  const activePrimaryTab = resolvePrimaryTab(activeTab);
  const mlsBaseUrl = useSettingsStore((s) => s.mlsBaseUrl);

  const openMls = () => {
    const target = (mlsBaseUrl || MLS_DEFAULT_BASE_URL).replace(/\/+$/, '');
    window.open(target, '_blank', 'noopener,noreferrer');
  };

  return (
    <nav className={`dock-scrollbar flex max-w-full items-center overflow-x-auto border border-slate-200/80 bg-slate-100/90 dark:border-slate-800/80 dark:bg-slate-900/90 ${compact ? "rounded-[20px] p-1" : "rounded-2xl p-1.5"}`}>
      <div className="flex min-w-max items-center gap-1">
        {PRIMARY_TAB_LIST.map(({ id, titleKey }) => {
          const isActive = id === activePrimaryTab;
          return (
            <button
              key={id}
              data-testid={`tab-${id}`}
              onClick={() => onTabChange(id)}
              className={`
                relative z-10 shrink-0 rounded-xl font-semibold tracking-wide transition-colors duration-300 outline-none
                ${compact ? "px-2.5 py-2 text-xs sm:px-3" : "px-3 py-2 text-sm sm:px-4"}
                ${isActive ? 'text-blue-700 dark:text-blue-400' : 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200'}
              `}
              style={{ WebkitTapHighlightColor: 'transparent' }}
            >
              {isActive && (
                <motion.div
                  layoutId="active-primary-tab-indicator"
                  className="absolute inset-0 rounded-xl border border-slate-200/80 bg-slate-100/95 dark:border-slate-700/80 dark:bg-slate-900/85"
                  transition={{ type: 'spring', bounce: 0.2, duration: 0.5 }}
                  style={{ zIndex: -1 }}
                />
              )}
              <span className="relative z-10 flex items-center gap-2">
                <span className="flex items-center justify-center">{PRIMARY_TAB_ICONS[id]}</span>
                <span className={`whitespace-nowrap ${compact ? "hidden sm:inline" : ""}`}>{t(titleKey)}</span>
              </span>
            </button>
          );
        })}

        {/* Jump entry to the standalone Material-LUT Studio (MLS) service. */}
        {/* 跳转到独立 Material-LUT Studio (MLS) 服务的入口。 */}
        <button
          data-testid="tab-open-mls"
          onClick={openMls}
          title={t('tab.openMlsHint')}
          className={`
            relative z-10 shrink-0 rounded-xl font-semibold tracking-wide outline-none
            text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200
            ${compact ? "px-2.5 py-2 text-xs sm:px-3" : "px-3 py-2 text-sm sm:px-4"}
          `}
          style={{ WebkitTapHighlightColor: 'transparent' }}
        >
          <span className="relative z-10 flex items-center gap-2">
            <span className="flex items-center justify-center">{MLS_ICON}</span>
            <span className={`whitespace-nowrap ${compact ? "hidden sm:inline" : ""}`}>{t('tab.openMls')}</span>
          </span>
        </button>
      </div>
    </nav>
  );
}
