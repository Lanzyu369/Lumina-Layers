/**
 * TabNavBar - Top navigation bar for switching between TAB pages.
 * 顶部导航栏，用于切换不同 TAB 页面。
 */
import { useI18n } from '../../i18n/context';
import type { TabId } from '../../types/widget';
import { useWidgetStore } from '../../stores/widgetStore';
import { motion } from 'framer-motion';

interface TabNavBarProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  compact?: boolean;
}

type PrimaryTabId = 'converter' | 'lut-management' | 'material-management' | 'vectorizer' | 'settings';
type LutSubTabId = 'calibration' | 'extractor' | 'lut-manager' | 'lut-details' | 'lut-compare' | 'five-color';
type MaterialSubTabId = 'gradient-card-generate' | 'gradient-card-extract' | 'material-library';

const LUT_SUB_TAB_IDS: LutSubTabId[] = ['calibration', 'extractor', 'lut-manager', 'lut-details', 'lut-compare', 'five-color'];
const MATERIAL_SUB_TAB_IDS: MaterialSubTabId[] = ['material-library', 'gradient-card-generate', 'gradient-card-extract'];

const PRIMARY_TAB_ICONS: Record<PrimaryTabId, React.ReactNode> = {
  'converter': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  ),
  'lut-management': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
    </svg>
  ),
  'material-management': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 7h10M7 12h10M7 17h6M5 4h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z" />
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
  )
};

const COLOR_EDITOR_ACTION_ICON = (
  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" d="M4 21h4l11-11a2.828 2.828 0 10-4-4L4 17v4z" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M14 7l3 3" />
  </svg>
);

const SECONDARY_TAB_ICONS: Record<LutSubTabId | MaterialSubTabId, React.ReactNode> = {
  'calibration': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
    </svg>
  ),
  'extractor': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879M12 12L9.121 9.121m0 5.758a3 3 0 10-4.243-4.243 3 3 0 004.243 4.243z" />
    </svg>
  ),
  'lut-manager': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
    </svg>
  ),
  'lut-details': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M10 6h8m-8 6h8m-8 6h8M6 6h.01M6 12h.01M6 18h.01" />
    </svg>
  ),
  'lut-compare': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h8M8 17h8M5 7l-2 2m0 0l2 2m-2-2h10M19 17l2-2m0 0l-2-2m2 2H11" />
    </svg>
  ),
  'five-color': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
    </svg>
  ),
  'gradient-card-generate': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m6-6H6m12-7H6a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2z" />
    </svg>
  ),
  'gradient-card-extract': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 16V4m0 12l-4-4m4 4l4-4M6 20h12" />
    </svg>
  ),
  'material-library': (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 7.5A2.5 2.5 0 015.5 5H9l1.5 2H18.5A2.5 2.5 0 0121 9.5v7A2.5 2.5 0 0118.5 19h-13A2.5 2.5 0 013 16.5v-9z" />
    </svg>
  ),
};

const PRIMARY_TAB_LIST: { id: PrimaryTabId; titleKey: string }[] = [
  { id: 'converter', titleKey: 'tab.converter' },
  { id: 'lut-management', titleKey: 'tab.lutManagement' },
  { id: 'material-management', titleKey: 'tab.materialManagement' },
  { id: 'vectorizer', titleKey: 'tab.vectorizer' },
  { id: 'settings', titleKey: 'tab.settings' },
];

const LUT_SECONDARY_TAB_LIST: { id: LutSubTabId; titleKey: string }[] = [
  { id: 'calibration', titleKey: 'tab.calibration' },
  { id: 'extractor', titleKey: 'tab.extractor' },
  { id: 'lut-manager', titleKey: 'tab.lutManager' },
  { id: 'lut-details', titleKey: 'tab.lutDetails' },
  { id: 'lut-compare', titleKey: 'tab.lutCompare' },
  { id: 'five-color', titleKey: 'tab.fiveColor' },
];

const MATERIAL_SECONDARY_TAB_LIST: { id: MaterialSubTabId; titleKey: string }[] = [
  { id: 'material-library', titleKey: 'tab.materialLibrary' },
  { id: 'gradient-card-generate', titleKey: 'tab.gradientCardGenerate' },
  { id: 'gradient-card-extract', titleKey: 'tab.gradientCardExtract' },
];

function isLutSubTab(tab: TabId): tab is LutSubTabId {
  return LUT_SUB_TAB_IDS.includes(tab as LutSubTabId);
}

function isMaterialSubTab(tab: TabId): tab is MaterialSubTabId {
  return MATERIAL_SUB_TAB_IDS.includes(tab as MaterialSubTabId);
}

export default function TabNavBar({ activeTab, onTabChange, compact = false }: TabNavBarProps) {
  const { t } = useI18n();
  const activePrimaryTab: PrimaryTabId = isLutSubTab(activeTab)
    ? 'lut-management'
    : isMaterialSubTab(activeTab)
      ? 'material-management'
      : activeTab;
  const showLutSubTabs = activePrimaryTab === 'lut-management';
  const showMaterialSubTabs = activePrimaryTab === 'material-management';
  const showConverterSecondary = activePrimaryTab === 'converter';
  const secondaryTabList = showLutSubTabs
    ? LUT_SECONDARY_TAB_LIST
    : showMaterialSubTabs
      ? MATERIAL_SECONDARY_TAB_LIST
      : null;
  const openColor2DOverlay = useWidgetStore((s) => s.openColor2DOverlay);

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <nav className={`dock-scrollbar flex max-w-full items-center overflow-x-auto border border-slate-200/80 bg-slate-100/90 dark:border-slate-800/80 dark:bg-slate-900/90 ${compact ? "rounded-[20px] p-1" : "rounded-2xl p-1.5"}`}>
        <div className="flex min-w-max items-center gap-1">
          {PRIMARY_TAB_LIST.map(({ id, titleKey }) => {
            const isActive = id === activePrimaryTab;
            return (
              <button
                key={id}
                data-testid={`tab-${id}`}
                onClick={() => {
                  if (id === 'lut-management') {
                    onTabChange(isLutSubTab(activeTab) ? activeTab : 'calibration');
                    return;
                  }
                  if (id === 'material-management') {
                    onTabChange(isMaterialSubTab(activeTab) ? activeTab : 'material-library');
                    return;
                  }
                  onTabChange(id);
                }}
                className={`
                  relative z-10 shrink-0 rounded-xl font-semibold tracking-wide transition-colors duration-300 outline-none
                  ${compact ? "px-2.5 py-2 text-xs sm:px-3" : "px-3 py-2 text-sm sm:px-4"}
                  ${isActive ? 'text-blue-700 dark:text-blue-400' : 'text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200'}
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
        </div>
      </nav>

      {showConverterSecondary && (
        <nav className={`dock-scrollbar flex max-w-full items-center overflow-x-auto border border-slate-200/80 bg-slate-100/90 dark:border-slate-800/80 dark:bg-slate-900/90 ${compact ? "rounded-[20px] p-1" : "rounded-2xl p-1.5"}`}>
          <div className="flex min-w-max items-center gap-1">
            <button
              data-testid="subtab-color-editor"
              onClick={openColor2DOverlay}
              className={`
                relative z-10 shrink-0 rounded-xl font-semibold tracking-wide transition-colors duration-300 outline-none
                ${compact ? "px-2.5 py-2 text-xs sm:px-3" : "px-3 py-2 text-sm sm:px-4"}
                text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200
              `}
              style={{ WebkitTapHighlightColor: 'transparent' }}
              aria-label={t('tab.colorEditor')}
            >
              <span className="relative z-10 flex items-center gap-2">
                <span className="flex items-center justify-center">{COLOR_EDITOR_ACTION_ICON}</span>
                <span className={`whitespace-nowrap ${compact ? "hidden sm:inline" : ""}`}>{t('tab.colorEditor')}</span>
              </span>
            </button>
          </div>
        </nav>
      )}

      {secondaryTabList && (
        <nav className={`dock-scrollbar flex max-w-full items-center overflow-x-auto border border-slate-200/80 bg-slate-100/90 dark:border-slate-800/80 dark:bg-slate-900/90 ${compact ? "rounded-[20px] p-1" : "rounded-2xl p-1.5"}`}>
          <div className="flex min-w-max items-center gap-1">
            {secondaryTabList.map(({ id, titleKey }) => {
              const isActive = id === activeTab;
              return (
                <button
                  key={id}
                  data-testid={`subtab-${id}`}
                  onClick={() => onTabChange(id)}
                  className={`
                    relative z-10 shrink-0 rounded-xl font-semibold tracking-wide transition-colors duration-300 outline-none
                    ${compact ? "px-2.5 py-2 text-xs sm:px-3" : "px-3 py-2 text-sm sm:px-4"}
                    ${isActive ? 'text-blue-700 dark:text-blue-400' : 'text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200'}
                  `}
                  style={{ WebkitTapHighlightColor: 'transparent' }}
                >
                  {isActive && (
                    <motion.div
                      layoutId="active-secondary-tab-indicator"
                      className="absolute inset-0 rounded-xl border border-slate-200/80 bg-slate-100/95 dark:border-slate-700/80 dark:bg-slate-900/85"
                      transition={{ type: 'spring', bounce: 0.2, duration: 0.5 }}
                      style={{ zIndex: -1 }}
                    />
                  )}
                  <span className="relative z-10 flex items-center gap-2">
                    <span className="flex items-center justify-center">{SECONDARY_TAB_ICONS[id]}</span>
                    <span className={`whitespace-nowrap ${compact ? "hidden sm:inline" : ""}`}>{t(titleKey)}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </nav>
      )}
    </div>
  );
}
