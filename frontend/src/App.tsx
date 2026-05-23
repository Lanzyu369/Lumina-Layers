import { useState, useEffect, useCallback, Suspense, Component } from "react";
import type { ReactNode } from "react";
import apiClient from "./api/client";
import type { HealthResponse } from "./api/types";
import { useAutoPreview } from "./hooks/useAutoPreview";
import { useAnnouncement } from "./hooks/useAnnouncement";
import { usePuzzleLayoutPreview } from "./hooks/usePuzzleLayoutPreview";
import { useSessionLease } from "./hooks/useSessionLease";
import { useColorcheckerArtifactLease } from "./hooks/useColorcheckerArtifactLease";
import { useActionHistoryBootstrap } from "./hooks/useActionHistoryBootstrap";
import { useReproMode } from "./hooks/useReproMode";
import { useWorkspaceMode } from "./hooks/useWorkspaceMode";
import { getSettings } from "./api/system";
import Scene3D from "./components/Scene3D";
import ExtractorCanvas from "./components/ExtractorCanvas";
import LoadingSpinner from "./components/LoadingSpinner";
import AnnouncementDialog from "./components/ui/AnnouncementDialog";
import { I18nProvider, useI18n } from "./i18n/context";
import { BugReportButton } from "./components/BugReportButton";
import { BugReportModal } from "./components/BugReportModal";
import { LanguageToggle } from "./components/LanguageToggle";
import { ThemeToggle } from "./components/ThemeToggle";
import { WidgetWorkspace } from "./components/widget/WidgetWorkspace";
import { useWidgetStore, WIDGET_REGISTRY, TAB_WIDGET_MAP, CONVERTER_SUB_TAB_WIDGET_MAP } from "./stores/widgetStore";
import TabNavBar, { hasSubTabs } from "./components/widget/TabNavBar";
import SubTabBar from "./components/widget/SubTabBar";
import CalibrationPanel from "./components/CalibrationPanel";
import ExtractorPanel from "./components/ExtractorPanel";
import ColorcheckerConfirmDialogExtractor from "./components/ColorcheckerConfirmDialog";
import GradientCardGeneratePanel from "./components/GradientCardGeneratePanel";
import GradientCardExtractPanel from "./components/GradientCardExtractPanel";
import MaterialLibraryPanel from "./components/MaterialLibraryPanel";
import MaterialRecipeQueryPanel from "./components/MaterialRecipeQueryPanel";
import LutComparePanel from "./components/LutComparePanel";
import LutManagerPanel from "./components/LutManagerPanel";
import FiveColorQueryPanel from "./components/FiveColorQueryPanel";
import SettingsPanel from "./components/SettingsPanel";
import VectorizerPanel from "./components/VectorizerPanel";
import { useSingleStageStore } from "./stores/singleStageStore";
import { useExtractorStore } from "./stores/extractorStore";
import { useConverterStore } from "./stores/converter";
import { useSettingsStore } from "./stores/settingsStore";
import { useShallow } from "zustand/react/shallow";
import { useElectronLanguageSync } from "./integrations/electron";

import LutDetailsPanel from "./components/LutDetailsPanel";

/* ---------- Error Boundary ---------- */

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

class SceneErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

/* ---------- Widget Toggle Buttons ---------- */

import { useRef } from "react";

function useOutsideClick(ref: React.RefObject<HTMLElement | null>, handler: () => void) {
  useEffect(() => {
    const listener = (event: MouseEvent | TouchEvent) => {
      if (!ref.current || ref.current.contains(event.target as Node)) {
        return;
      }
      handler();
    };
    document.addEventListener('mousedown', listener);
    document.addEventListener('touchstart', listener);
    return () => {
      document.removeEventListener('mousedown', listener);
      document.removeEventListener('touchstart', listener);
    };
  }, [ref, handler]);
}

import { AnimatePresence, motion } from "framer-motion";

function WidgetToggles() {
  const { t } = useI18n();
  const toggleVisible = useWidgetStore((s) => s.toggleVisible);
  const resetLayout = useWidgetStore((s) => s.resetLayout);
  const activeTab = useWidgetStore((s) => s.activeTab);
  const activeConverterSubTab = useWidgetStore((s) => s.activeConverterSubTab);
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useOutsideClick(dropdownRef, () => setIsOpen(false));

  // Filter to only show widgets belonging to the current TAB page.
  // For the converter, narrow further by the active sub-tab so users cannot
  // toggle on a widget that the current sub-tab will not render — that was
  // confusing ("why doesn't this panel appear after I enabled it?").
  // 对于「图像转换」主 tab，再按当前二级 sub-tab 收窄；否则用户能开启一个
  // 实际不会渲染的 widget，造成「我开了为什么看不到」的困惑。
  const activeWidgetIds =
    activeTab === "converter"
      ? (CONVERTER_SUB_TAB_WIDGET_MAP[activeConverterSubTab] as readonly import("./types/widget").WidgetId[])
      : TAB_WIDGET_MAP[activeTab];
  const visibleWidgetIds = useWidgetStore(
    useShallow((s) => activeWidgetIds.filter((id) => s.widgets[id].visible))
  );
  const filteredRegistry = WIDGET_REGISTRY.filter((c) => activeWidgetIds.includes(c.id));

  const hasWidgets = filteredRegistry.length > 0;

  return (
    <div className={`relative${hasWidgets ? '' : ' invisible pointer-events-none'}`} ref={dropdownRef}>
      <button
        data-testid="panel-controls-toggle"
        className={`flex items-center gap-2 border px-4 py-2 text-sm font-semibold transition-colors duration-300 rounded-xl outline-none
          ${isOpen ? 'border-transparent bg-blue-600 shadow-[var(--shadow-control-hover)] text-white' : 'border-slate-200/80 bg-slate-100 dark:border-slate-800/80 dark:bg-slate-900 text-slate-700 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-800'}
        `}
        style={{ WebkitTapHighlightColor: 'transparent' }}
        onClick={() => setIsOpen(!isOpen)}
        title={t("app_panel_controls")}
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
        </svg>
        <span className="hidden sm:inline">{t("app_panel_controls")}</span>
        <svg
          className={`w-4 h-4 transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {hasWidgets && (
        <AnimatePresence>
          {isOpen && (
            <motion.div
              initial={{ opacity: 0, y: -10, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -10, scale: 0.95 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              className="absolute right-0 top-full mt-2 z-50 flex w-56 flex-col gap-1 overflow-hidden rounded-2xl border border-slate-200/80 bg-slate-100/98 p-2 shadow-[var(--shadow-control-hover)] dark:border-slate-800/80 dark:bg-slate-900/98 origin-top-right"
            >
              {filteredRegistry.map((config) => {
                const isActive = visibleWidgetIds.includes(config.id);
                return (
                  <button
                    key={config.id}
                    data-testid={`widget-toggle-${config.id}`}
                    className={`
                      flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-semibold tracking-wide transition-all duration-200 outline-none
                      ${
                        isActive
                          ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400"
                          : "bg-transparent text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100/80 dark:hover:bg-slate-700/50"
                      }
                    `}
                    onClick={() => toggleVisible(config.id)}
                  >
                    <span
                      className={`w-2 h-2 rounded-full transition-colors duration-300 ${isActive ? 'bg-blue-500 shadow-[0_0_6px_rgba(59,130,246,0.6)]' : 'bg-slate-300 dark:bg-slate-600'}`}
                    />
                    {t(config.titleKey)}
                  </button>
                );
              })}

              <div className="h-px bg-slate-200 dark:bg-slate-700/80 my-1 mx-2" />

              <button
                data-testid="widget-reset-layout"
                className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-semibold tracking-wide transition-all duration-200 outline-none
                  bg-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100/80 dark:hover:bg-slate-700/50"
                onClick={() => {
                  resetLayout();
                  setIsOpen(false);
                }}
              >
                <svg className="w-4 h-4 ml-0.5 text-slate-400" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                {t("app_reset_layout")}
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      )}
    </div>
  );
}

/* ---------- App Content (inside I18nProvider) ---------- */

function AppContent() {
  const { t } = useI18n();
  const announcement = useAnnouncement();
  const converterSessionId = useConverterStore((s) => s.sessionId);
  const singleStageSessionId = useSingleStageStore((s) => s.sessionId);
  const hydrateDeviceSettingsFromBackend = useSettingsStore(
    (s) => s.hydrateDeviceSettingsFromBackend,
  );

  useSessionLease(converterSessionId);
  useSessionLease(singleStageSessionId, "single_stage");
  useActionHistoryBootstrap();
  useAutoPreview();
  usePuzzleLayoutPreview();
  useElectronLanguageSync();
  const workspace = useWorkspaceMode();
  const reproMode = useReproMode();

  const [connected, setConnected] = useState<boolean | null>(null);
  const [announcementReady, setAnnouncementReady] = useState(false);
  const [bugReportOpen, setBugReportOpen] = useState(false);
  const activeTab = useWidgetStore((s) => s.activeTab);
  const setActiveTab = useWidgetStore((s) => s.setActiveTab);
  const extractorColorcheckerActive = useExtractorStore(
    (s) =>
      s.colorchecker_enabled &&
      s.colorchecker_phase !== "done" &&
      s.imageFile !== null,
  );
  const extractorColorcheckerFullId = useExtractorStore((s) =>
    s.colorchecker_phase === "done" ? s.calibratedFullFileId : null,
  );
  const gradientColorcheckerFullIds = useSingleStageStore(
    useShallow((s) => [s.whiteColorcheckerFileId, s.blackColorcheckerFileId]),
  );
  useColorcheckerArtifactLease([
    extractorColorcheckerFullId,
    ...gradientColorcheckerFullIds,
  ]);
  const clearMaterialVerification = useSingleStageStore(
    (s) => s.clearMaterialVerification,
  );

  // When the user explicitly clicks the “提取耗材” (gradient-card-extract)
  // sub-tab via the nav bar, treat it as “start a fresh extraction” and
  // drop any leftover material-verification state. The re-verification
  // entry from MaterialLibraryPanel sets verification state and calls
  // setActiveTab directly via the widgetStore, bypassing this handler, so
  // that flow is unaffected.
  // 用户从导航栏主动点击「提取耗材」子页时视为「全新提取」，清除遗留的再次
  // 校验状态；从耗材库「再次校验」进入的路径直接调 store 的 setActiveTab，不走
  // 这里，所以验证模式不会被错误清除。
  const handleTabChange = useCallback(
    (tab: typeof activeTab) => {
      if (tab === "gradient-card-extract") {
        clearMaterialVerification();
      }
      setActiveTab(tab);
    },
    [setActiveTab, clearMaterialVerification],
  );

  useEffect(() => {
    apiClient
      .get<HealthResponse>("/health")
      .then((res) => setConnected(res.data.status === "ok"))
      .catch(() => setConnected(false));
  }, []);

  useEffect(() => {
    let cancelled = false;

    getSettings()
      .then((response) => {
        if (!cancelled && response?.settings) {
          hydrateDeviceSettingsFromBackend(response.settings);
        }
      })
      .catch(() => {
        /* best effort */
      });

    return () => {
      cancelled = true;
    };
  }, [hydrateDeviceSettingsFromBackend]);

  useEffect(() => {
    const timer = window.setTimeout(() => setAnnouncementReady(true), 600);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-white">
      <header
        className={`relative z-50 border-b border-slate-200 dark:border-slate-800 ${
          workspace.isCompact
            ? "grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 px-3 py-2.5 sm:px-4"
            : "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-3 py-3 sm:px-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] lg:px-6 lg:py-4"
        }`}
      >
        <div className="flex min-w-0 items-center gap-3">
          <img src="/favicon.ico" alt={t("app_logo_alt")} className="h-8 w-8 shrink-0 rounded" />
          <h1 className={`min-w-0 truncate font-semibold tracking-tight ${workspace.isCompact ? "hidden text-lg md:block" : "hidden text-xl sm:block"}`}>
            {t("app_header_title")}
          </h1>
        </div>

        {/* Right Side: Controls */}
        <div className={`flex min-w-0 items-center justify-end gap-2 ${workspace.isCompact ? "" : "lg:col-start-3 lg:row-start-1"}`}>
          <WidgetToggles />
          <LanguageToggle />
          <ThemeToggle />
          <BugReportButton onClick={() => setBugReportOpen(true)} />
          {reproMode.enabled && (
            <span
              data-testid="repro-mode-badge"
              className={`inline-flex items-center gap-1.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200 ${workspace.isCompact ? "px-2.5 py-1 text-xs" : "px-3 py-1 text-sm"}`}
              title={`复现模式 / Reproduction mode: ${reproMode.ticketId}`}
            >
              <span className="h-2 w-2 rounded-full bg-amber-400" />
              <span className={workspace.isCompact ? "hidden" : "hidden sm:inline"}>
                {reproMode.ticketId}
              </span>
            </span>
          )}
          {connected === null ? (
            <span className="text-sm text-slate-500 dark:text-slate-400">{t("app_checking_backend")}</span>
          ) : connected ? (
            <span
              data-testid="health-badge-ok"
              className={`inline-flex items-center gap-1.5 rounded-full bg-green-100 text-green-700 dark:bg-green-900/60 dark:text-green-300 ${workspace.isCompact ? "px-2.5 py-1 text-xs" : "px-3 py-1 text-sm"}`}
            >
              <span className="h-2 w-2 rounded-full bg-green-400" />
              <span className={workspace.isCompact ? "hidden" : "hidden sm:inline"}>{t("app_backend_connected")}</span>
            </span>
          ) : (
            <span
              data-testid="health-badge-fail"
              className={`inline-flex items-center gap-1.5 rounded-full bg-red-100 text-red-700 dark:bg-red-900/60 dark:text-red-300 ${workspace.isCompact ? "px-2.5 py-1 text-xs" : "px-3 py-1 text-sm"}`}
            >
              <span className="h-2 w-2 rounded-full bg-red-400" />
              <span className={workspace.isCompact ? "hidden" : "hidden sm:inline"}>{t("app_backend_unreachable")}</span>
            </span>
          )}
        </div>

        {/* Center: Tabs */}
        <div className={`min-w-0 w-full ${workspace.isCompact ? "col-span-3 row-start-2" : "col-span-2 lg:col-span-1 lg:col-start-2 lg:row-start-1"}`}>
          <TabNavBar
            activeTab={activeTab}
            onTabChange={handleTabChange}
            compact={workspace.isCompact}
          />
        </div>
      </header>

      <main className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-50 dark:bg-slate-950">
        {hasSubTabs(activeTab) && (
          <div className="shrink-0 border-b border-slate-200/80 bg-slate-100/50 px-3 py-2 dark:border-slate-800/80 dark:bg-slate-900/50 sm:px-4 lg:px-6">
            <SubTabBar
              activeTab={activeTab}
              onTabChange={handleTabChange}
              compact={workspace.isCompact}
            />
          </div>
        )}

        <div className="relative min-h-0 flex-1">
        {/* Converter: WidgetWorkspace + Scene3D */}
        {activeTab === 'converter' && (
          <div className="h-full min-h-0">
            <WidgetWorkspace>
              <SceneErrorBoundary
                fallback={
                  <div className="absolute inset-0 flex items-center justify-center bg-slate-100 dark:bg-slate-950">
                    <p className="text-red-400 text-sm">{t("app_3d_scene_error")}</p>
                  </div>
                }
              >
                <Suspense fallback={<LoadingSpinner />}>
                  <Scene3D />
                </Suspense>
              </SceneErrorBoundary>
            </WidgetWorkspace>
          </div>
        )}

        {activeTab === 'calibration' && <CalibrationPanel />}
        {activeTab === 'gradient-card-generate' && <GradientCardGeneratePanel />}
        {activeTab === 'gradient-card-extract' && <GradientCardExtractPanel />}
        {activeTab === 'material-library' && <MaterialLibraryPanel />}
        {activeTab === 'material-recipe' && <MaterialRecipeQueryPanel />}

        {activeTab === 'extractor' && (
          <div className="flex h-full min-h-0 flex-col xl:flex-row">
            <ExtractorPanel />
            <div className="relative min-h-[min(54vh,40rem)] flex-1 overflow-hidden border-t border-slate-200/70 dark:border-slate-800/80 xl:min-h-0 xl:border-l xl:border-t-0">
              {extractorColorcheckerActive ? (
                <div className="h-full min-h-0 overflow-auto p-3 sm:p-5 xl:p-7">
                  <ColorcheckerConfirmDialogExtractor />
                </div>
              ) : (
                <ExtractorCanvas />
              )}
            </div>
          </div>
        )}

        {activeTab === 'lut-manager' && <LutManagerPanel />}
        {activeTab === 'lut-details' && <LutDetailsPanel />}
        {activeTab === 'lut-compare' && <LutComparePanel />}
        {activeTab === 'five-color' && (
          <div className="flex h-full min-h-0">
            <FiveColorQueryPanel />
          </div>
        )}
        {activeTab === 'vectorizer' && <VectorizerPanel />}
        {activeTab === 'settings' && <SettingsPanel />}
        </div>
      </main>
      <AnnouncementDialog
        open={announcementReady && announcement.visible}
        entries={announcement.entries}
        entry={announcement.entry}
        onClose={announcement.close}
        onDismissVersion={announcement.dismissThisVersion}
      />
      <BugReportModal
        open={bugReportOpen}
        onClose={() => setBugReportOpen(false)}
      />
    </div>
  );
}

/* ---------- App ---------- */

function App() {
  return (
    <I18nProvider>
      <AppContent />
    </I18nProvider>
  );
}

export default App;
