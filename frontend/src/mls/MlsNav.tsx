/**
 * MlsNav — primary + secondary tab navigation for the standalone MLS app.
 * MLS 独立应用的一级 + 二级标签导航。
 *
 * Replicates the converter app's original TabNavBar (primary pill row) and
 * SubTabBar (secondary row) markup/styling verbatim, scoped to the two MLS
 * primary groups: ``material-management`` and ``lut-management``. Clicking a
 * primary tab selects the first secondary tab of that group; the secondary row
 * shows only the active group's sub-tabs — exactly like the original layout.
 *
 * 完整复刻转换器应用原版 TabNavBar（一级 pill 行）与 SubTabBar（二级行）的
 * 结构与样式，范围限定为 MLS 的两个一级分组：``material-management`` 与
 * ``lut-management``。点击一级标签切到该组首个二级标签；二级行只显示当前组的
 * 子标签——与原版布局一致。
 */
import { motion } from "framer-motion";
import { useI18n } from "../i18n/context";
import type { TabId } from "../types/widget";

type MlsPrimaryTabId = "material-management" | "lut-management";

export type MlsSubTabId =
  | "material-library"
  | "gradient-card-generate"
  | "gradient-card-extract"
  | "material-recipe"
  | "calibration"
  | "extractor"
  | "lut-manager"
  | "lut-details"
  | "lut-compare"
  | "five-color";

const MATERIAL_SUB_TABS: MlsSubTabId[] = [
  "material-library",
  "gradient-card-generate",
  "gradient-card-extract",
  "material-recipe",
];

const LUT_SUB_TABS: MlsSubTabId[] = [
  "calibration",
  "extractor",
  "lut-manager",
  "lut-details",
  "lut-compare",
  "five-color",
];

const PRIMARY_TAB_ICONS: Record<MlsPrimaryTabId, React.ReactNode> = {
  "material-management": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 7h10M7 12h10M7 17h6M5 4h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z" />
    </svg>
  ),
  "lut-management": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
    </svg>
  ),
};

const SECONDARY_TAB_ICONS: Record<MlsSubTabId, React.ReactNode> = {
  "calibration": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
    </svg>
  ),
  "extractor": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879M12 12L9.121 9.121m0 5.758a3 3 0 10-4.243-4.243 3 3 0 004.243 4.243z" />
    </svg>
  ),
  "lut-manager": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
    </svg>
  ),
  "lut-details": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M10 6h8m-8 6h8m-8 6h8M6 6h.01M6 12h.01M6 18h.01" />
    </svg>
  ),
  "lut-compare": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h8M8 17h8M5 7l-2 2m0 0l2 2m-2-2h10M19 17l2-2m0 0l-2-2m2 2H11" />
    </svg>
  ),
  "five-color": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
    </svg>
  ),
  "gradient-card-generate": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m6-6H6m12-7H6a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2z" />
    </svg>
  ),
  "gradient-card-extract": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 16V4m0 12l-4-4m4 4l4-4M6 20h12" />
    </svg>
  ),
  "material-library": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 7.5A2.5 2.5 0 015.5 5H9l1.5 2H18.5A2.5 2.5 0 0121 9.5v7A2.5 2.5 0 0118.5 19h-13A2.5 2.5 0 013 16.5v-9z" />
    </svg>
  ),
  "material-recipe": (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h10" />
      <circle cx="18" cy="18" r="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
};

const PRIMARY_TAB_LIST: { id: MlsPrimaryTabId; titleKey: string }[] = [
  { id: "material-management", titleKey: "tab.materialManagement" },
  { id: "lut-management", titleKey: "tab.lutManagement" },
];

const SECONDARY_TAB_TITLE: Record<MlsSubTabId, string> = {
  "material-library": "tab.materialLibrary",
  "gradient-card-generate": "tab.gradientCardGenerate",
  "gradient-card-extract": "tab.gradientCardExtract",
  "material-recipe": "tab.materialRecipe",
  "calibration": "tab.calibration",
  "extractor": "tab.extractor",
  "lut-manager": "tab.lutManager",
  "lut-details": "tab.lutDetails",
  "lut-compare": "tab.lutCompare",
  "five-color": "tab.fiveColor",
};

export function isMlsLutTab(tab: TabId): boolean {
  return (LUT_SUB_TABS as string[]).includes(tab);
}

export function isMlsMaterialTab(tab: TabId): boolean {
  return (MATERIAL_SUB_TABS as string[]).includes(tab);
}

function resolveMlsPrimary(activeTab: MlsSubTabId): MlsPrimaryTabId {
  return isMlsLutTab(activeTab) ? "lut-management" : "material-management";
}

interface MlsNavProps {
  activeTab: MlsSubTabId;
  onTabChange: (tab: MlsSubTabId) => void;
  compact?: boolean;
  /**
   * When ``true`` the secondary nav hides write-only tabs (calibration card
   * generation, ColorChecker extraction, gradient-card capture/extract). The
   * primary pill row still shows both groups so users can navigate.
   * 只读模式下二级导航隐藏纯写入用途的标签（校准卡生成、ColorChecker 提取、
   * 梯度卡拍摄/提取）；一级 pill 行仍显示两个分组以便切换。
   */
  readOnly?: boolean;
}

/** Tabs that have no read-only purpose: every flow there creates new data. */
/** 只读模式下隐藏的标签：每个流程都用于创建新数据。 */
const READ_ONLY_HIDDEN_SUB_TABS: ReadonlySet<MlsSubTabId> = new Set([
  "gradient-card-generate",
  "gradient-card-extract",
  "calibration",
  "extractor",
]);

/**
 * Resolve the first secondary tab visible under the given primary group,
 * honouring the read-only filter so navigation never lands on a hidden tab.
 * 在只读过滤下找到给定一级分组中第一个可见的二级标签，避免导航跳到被隐藏的标签。
 */
function firstVisibleSubTab(
  primary: MlsPrimaryTabId,
  readOnly: boolean,
): MlsSubTabId {
  const list = primary === "lut-management" ? LUT_SUB_TABS : MATERIAL_SUB_TABS;
  if (!readOnly) {
    return list[0];
  }
  return list.find((id) => !READ_ONLY_HIDDEN_SUB_TABS.has(id)) ?? list[0];
}

/** Primary pill row — same markup/styling as the original TabNavBar. */
export function MlsPrimaryNav({ activeTab, onTabChange, compact = false, readOnly = false }: MlsNavProps) {
  const { t } = useI18n();
  const activePrimary = resolveMlsPrimary(activeTab);

  return (
    <nav className={`dock-scrollbar flex max-w-full items-center overflow-x-auto border border-slate-200/80 bg-slate-100/90 dark:border-slate-800/80 dark:bg-slate-900/90 ${compact ? "rounded-[20px] p-1" : "rounded-2xl p-1.5"}`}>
      <div className="flex min-w-max items-center gap-1">
        {PRIMARY_TAB_LIST.map(({ id, titleKey }) => {
          const isActive = id === activePrimary;
          return (
            <button
              key={id}
              data-testid={`mls-tab-${id}`}
              onClick={() => {
                if (id === "lut-management") {
                  onTabChange(isMlsLutTab(activeTab) ? activeTab : firstVisibleSubTab("lut-management", readOnly));
                } else {
                  onTabChange(isMlsMaterialTab(activeTab) ? activeTab : firstVisibleSubTab("material-management", readOnly));
                }
              }}
              className={`
                relative z-10 shrink-0 rounded-xl font-semibold tracking-wide transition-colors duration-300 outline-none
                ${compact ? "px-2.5 py-2 text-xs sm:px-3" : "px-3 py-2 text-sm sm:px-4"}
                ${isActive ? "text-blue-700 dark:text-blue-400" : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"}
              `}
              style={{ WebkitTapHighlightColor: "transparent" }}
            >
              {isActive && (
                <motion.div
                  layoutId="mls-active-primary-tab-indicator"
                  className="absolute inset-0 rounded-xl border border-slate-200/80 bg-slate-100/95 dark:border-slate-700/80 dark:bg-slate-900/85"
                  transition={{ type: "spring", bounce: 0.2, duration: 0.5 }}
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
  );
}

/** Secondary row — same markup/styling as the original SubTabBar. */
export function MlsSecondaryNav({ activeTab, onTabChange, compact = false, readOnly = false }: MlsNavProps) {
  const { t } = useI18n();
  const activePrimary = resolveMlsPrimary(activeTab);
  const baseList = activePrimary === "lut-management" ? LUT_SUB_TABS : MATERIAL_SUB_TABS;
  const list = readOnly ? baseList.filter((id) => !READ_ONLY_HIDDEN_SUB_TABS.has(id)) : baseList;

  return (
    <nav
      role="tablist"
      className={`dock-scrollbar flex max-w-full items-center overflow-x-auto border border-slate-200/80 bg-slate-100/90 dark:border-slate-800/80 dark:bg-slate-900/90 ${compact ? "rounded-[20px] p-1" : "rounded-2xl p-1.5"}`}
    >
      <div className="flex min-w-max items-center gap-1">
        {list.map((id) => {
          const isActive = id === activeTab;
          return (
            <button
              key={id}
              role="tab"
              aria-selected={isActive}
              data-testid={`mls-subtab-${id}`}
              onClick={() => onTabChange(id)}
              className={`
                relative z-10 shrink-0 rounded-xl font-semibold tracking-wide transition-colors duration-300 outline-none
                ${compact ? "px-2.5 py-2 text-xs sm:px-3" : "px-3 py-2 text-sm sm:px-4"}
                ${isActive ? "text-blue-700 dark:text-blue-400" : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"}
              `}
              style={{ WebkitTapHighlightColor: "transparent" }}
            >
              {isActive && (
                <motion.div
                  layoutId="mls-active-secondary-tab-indicator"
                  className="absolute inset-0 rounded-xl border border-slate-200/80 bg-slate-100/95 dark:border-slate-700/80 dark:bg-slate-900/85"
                  transition={{ type: "spring", bounce: 0.2, duration: 0.5 }}
                  style={{ zIndex: -1 }}
                />
              )}
              <span className="relative z-10 flex items-center gap-2">
                <span className="flex items-center justify-center">{SECONDARY_TAB_ICONS[id]}</span>
                <span className={`whitespace-nowrap ${compact ? "hidden sm:inline" : ""}`}>{t(SECONDARY_TAB_TITLE[id])}</span>
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
