/**
 * MlsApp — standalone Material-LUT Studio frontend (Route B, option A).
 * 独立的 Material-LUT Studio 前端（路线 B，选项 A）。
 *
 * Reuses the converter app's existing panels (calibration generate, LUT
 * extraction + ColorChecker, gradient-card generate/extract, five-color query,
 * material library/recipe, LUT manager/details/compare) verbatim, and the
 * original two-tier tab navigation (primary pill row + secondary row) so the
 * layout and styling match the converter app exactly. Built as a second Vite
 * entry inside ``frontend/`` so it shares the whole dependency + component tree
 * with zero duplication, yet ships independently on its own port (:5180).
 *
 * 直接复用转换器应用的既有面板，并采用原版两级标签导航（一级 pill 行 + 二级
 * 行），使布局与样式与转换器应用完全一致。作为 ``frontend/`` 内的第二个 Vite
 * 入口构建，零重复地共享整套依赖与组件树，独立运行在 :5180。
 */
import { useEffect, useState } from "react";
import { I18nProvider, useI18n } from "../i18n/context";
import { useSettingsStore } from "../stores/settingsStore";
import { useWidgetStore } from "../stores/widgetStore";
import { useMlsAuthStore } from "../stores/mlsAuthStore";
import { fetchMlsAuthStatus } from "../api/mlsAuth";
import { LanguageToggle } from "../components/LanguageToggle";
import { ThemeToggle } from "../components/ThemeToggle";
import { MlsPrimaryNav, MlsSecondaryNav, type MlsSubTabId } from "./MlsNav";
import MlsAuthGate from "./MlsAuthGate";

import CalibrationPanel from "../components/CalibrationPanel";
import GradientCardGeneratePanel from "../components/GradientCardGeneratePanel";
import GradientCardExtractPanel from "../components/GradientCardExtractPanel";
import ExtractorPanel from "../components/ExtractorPanel";
import ExtractorCanvas from "../components/ExtractorCanvas";
import ColorcheckerConfirmDialog from "../components/ColorcheckerConfirmDialog";
import MaterialLibraryPanel from "../components/MaterialLibraryPanel";
import MaterialRecipeQueryPanel from "../components/MaterialRecipeQueryPanel";
import LutManagerPanel from "../components/LutManagerPanel";
import LutDetailsPanel from "../components/LutDetailsPanel";
import LutComparePanel from "../components/LutComparePanel";
import FiveColorQueryPanel from "../components/FiveColorQueryPanel";

const MLS_TAB_IDS = new Set<string>([
  "material-library",
  "gradient-card-generate",
  "gradient-card-extract",
  "material-recipe",
  "calibration",
  "extractor",
  "lut-manager",
  "lut-details",
  "lut-compare",
  "five-color",
]);
const DEFAULT_MLS_TAB: MlsSubTabId = "material-library";

/**
 * Tabs that have no read-only purpose: every flow there creates new data.
 * The secondary nav already filters them out; this set lets the active-tab
 * sanity guard auto-bump if the user persisted an active tab that became
 * invisible after entering read-only mode.
 *
 * 只读模式下纯写入用途的标签：每个流程都用于创建新数据。二级导航已经过滤掉它们，
 * 此处的集合让活动标签守卫在用户从写入模式回到只读模式时自动跳到可见标签。
 */
const READ_ONLY_HIDDEN_SUB_TABS: ReadonlySet<MlsSubTabId> = new Set([
  "gradient-card-generate",
  "gradient-card-extract",
  "calibration",
  "extractor",
]);

function MlsContent() {
  const { t } = useI18n();

  // Drive navigation through the shared widget store so the restored panels'
  // own cross-navigation (e.g. Material Library → gradient-card-extract via
  // ``setActiveTab``) keeps working unchanged.
  // 通过共享 widget store 驱动导航，使恢复面板自身的跨页跳转无需改动即可生效。
  const activeTab = useWidgetStore((s) => s.activeTab);
  const setActiveTab = useWidgetStore((s) => s.setActiveTab);

  // Auth gate state: server reports whether a write password is configured
  // and whether the cached one currently unlocks writes.
  // 鉴权门禁状态：从服务端获取是否需要密码以及缓存密码是否当前解锁写入。
  const passwordRequired = useMlsAuthStore((s) => s.passwordRequired);
  const writeEnabled = useMlsAuthStore((s) => s.writeEnabled);
  const ready = useMlsAuthStore((s) => s.ready);
  const setStatus = useMlsAuthStore((s) => s.setStatus);
  const markReady = useMlsAuthStore((s) => s.markReady);
  const clearPassword = useMlsAuthStore((s) => s.clearPassword);
  const [gateOpen, setGateOpen] = useState(false);

  useEffect(() => {
    if (!MLS_TAB_IDS.has(activeTab)) {
      setActiveTab(DEFAULT_MLS_TAB);
    }
  }, [activeTab, setActiveTab]);

  // Bootstrap: ask the MLS backend whether a password is configured. If yes
  // and the cached password (if any) doesn't unlock writes, prompt at boot.
  // When the server reports no password is configured (open mode), the user
  // is treated as already authenticated — no dialog is ever shown, and any
  // stale cached password from a previous protected configuration is
  // dropped so it can't accidentally re-enable a non-existent gate.
  // 启动：向 MLS 后端询问是否配置密码；若已配置且缓存密码无法解锁写入，则启动时
  // 弹窗。当服务端报告未配置密码（开放模式）时，用户视同已通过认证——绝不弹窗，
  // 同时丢弃来自上一次受保护配置的过期密码缓存，防止它意外触发已不存在的门禁。
  useEffect(() => {
    let cancelled = false;
    fetchMlsAuthStatus()
      .then((status) => {
        if (cancelled) return;
        setStatus(status.password_required, status.write_enabled);
        if (!status.password_required) {
          // Open mode: forget any password the user typed previously when
          // a different config was active. Closes the gate as a no-op.
          // 开放模式：丢弃用户在上一份受保护配置下输入过的密码；同时确保门禁关闭。
          clearPassword();
          setGateOpen(false);
          return;
        }
        if (!status.write_enabled) {
          setGateOpen(true);
        }
      })
      .catch(() => {
        if (cancelled) return;
        // Treat reachability failure as "unknown gating"; default to read-only
        // and let the user retry via the lock button. Showing the dialog here
        // would block the UI behind a transient network error.
        // 服务不可达时按"未知"处理，默认进入只读，用户可点锁按钮重试。这里不弹窗
        // 以免临时网络错误把界面卡住。
        setStatus(true, false);
      })
      .finally(() => {
        if (!cancelled) markReady();
      });
    return () => {
      cancelled = true;
    };
  }, [setStatus, markReady]);

  // Apply the persisted theme (shared settingsStore drives the ``dark`` class).
  // 应用持久化主题（共享 settingsStore 驱动 ``dark`` class）。
  const theme = useSettingsStore((s) => s.theme);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  const currentTab: MlsSubTabId = MLS_TAB_IDS.has(activeTab)
    ? (activeTab as MlsSubTabId)
    : DEFAULT_MLS_TAB;

  const handleTabChange = (tab: MlsSubTabId) => setActiveTab(tab);

  // Read-only mode is in effect when the server requires a password but the
  // current request would not be granted write access.
  // 服务端要求密码但当前未解锁时，进入只读模式。
  const readOnlyMode = ready && passwordRequired && !writeEnabled;

  // Tabs whose entire purpose is creating new data become unreachable in
  // read-only mode; bump the active tab off them onto the first visible
  // sibling so the empty content area never renders a "you cannot do
  // anything here" panel.
  // 只读模式下纯写入用途的标签不可达；若当前正落在这些标签上，自动跳到同组首个
  // 可见标签，避免内容区显示"什么也做不了"的空面板。
  useEffect(() => {
    if (!readOnlyMode) return;
    if (READ_ONLY_HIDDEN_SUB_TABS.has(currentTab)) {
      // material-library and lut-manager are the safest landing tabs for
      // each primary group; pick by group of the original active tab.
      // 选取所属一级分组的安全落点。
      const fallback: MlsSubTabId = currentTab === "calibration" || currentTab === "extractor"
        ? "lut-manager"
        : "material-library";
      setActiveTab(fallback);
    }
  }, [readOnlyMode, currentTab, setActiveTab]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-white">
      <header
        className="relative z-50 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-slate-200 px-3 py-3 dark:border-slate-800 sm:px-4 lg:px-6 lg:py-4"
      >
        <div className="flex min-w-0 items-center gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-base font-semibold">{t("mls.appTitle")}</h1>
            <p className="truncate text-xs text-slate-500 dark:text-slate-400">{t("mls.appSubtitle")}</p>
          </div>
          <div className="min-w-0 flex-1">
            <MlsPrimaryNav activeTab={currentTab} onTabChange={handleTabChange} readOnly={readOnlyMode} />
          </div>
        </div>
        <div className="flex items-center gap-2">
          {ready && passwordRequired && (
            <button
              type="button"
              onClick={() => setGateOpen(true)}
              data-testid="mls-auth-pill"
              data-write-enabled={writeEnabled}
              title={
                writeEnabled
                  ? t("mls.auth.pill_write_enabled_tooltip")
                  : t("mls.auth.pill_read_only_tooltip")
              }
              className={
                writeEnabled
                  ? "rounded-full border border-emerald-300/80 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100 dark:border-emerald-700/80 dark:bg-emerald-950/60 dark:text-emerald-200 dark:hover:bg-emerald-900/60"
                  : "rounded-full border border-amber-300/80 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100 dark:border-amber-700/80 dark:bg-amber-950/60 dark:text-amber-200 dark:hover:bg-amber-900/60"
              }
            >
              {writeEnabled
                ? t("mls.auth.pill_write_enabled")
                : t("mls.auth.pill_read_only")}
            </button>
          )}
          {ready && passwordRequired && writeEnabled && (
            <button
              type="button"
              onClick={() => {
                // ``clearPassword`` already drops ``writeEnabled`` to false
                // (passwordRequired is guaranteed true at this point because
                // the button only renders inside that condition); no extra
                // ``setStatus`` is needed.
                // ``clearPassword`` 已经把 ``writeEnabled`` 置 false（按钮仅在
                // passwordRequired 为 true 的分支渲染），无需额外 setStatus。
                clearPassword();
              }}
              data-testid="mls-auth-lock"
              title={t("mls.auth.lock_tooltip")}
              className="rounded-full border border-slate-300 bg-transparent px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {t("mls.auth.lock")}
            </button>
          )}
          <LanguageToggle />
          <ThemeToggle />
        </div>
      </header>

      <main className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-50 dark:bg-slate-950">
        {readOnlyMode && (
          <div
            data-testid="mls-read-only-banner"
            className="shrink-0 border-b border-amber-300/80 bg-amber-50 px-3 py-1.5 text-center text-xs font-medium text-amber-800 dark:border-amber-700/80 dark:bg-amber-950/60 dark:text-amber-200"
          >
            {t("mls.auth.read_only_banner")}
          </div>
        )}
        {/* Secondary tab row — same placement/strip as the converter app. */}
        {/* 二级标签行——与转换器应用相同的位置与条带样式。 */}
        <div className="shrink-0 border-b border-slate-200/80 bg-slate-100/50 px-3 py-2 dark:border-slate-800/80 dark:bg-slate-900/50 sm:px-4 lg:px-6">
          <MlsSecondaryNav activeTab={currentTab} onTabChange={handleTabChange} readOnly={readOnlyMode} />
        </div>

        <div className="relative min-h-0 flex-1">
          {currentTab === "material-library" && <MaterialLibraryPanel />}
          {currentTab === "gradient-card-generate" && <GradientCardGeneratePanel />}
          {currentTab === "gradient-card-extract" && <GradientCardExtractPanel />}
          {currentTab === "material-recipe" && <MaterialRecipeQueryPanel />}
          {currentTab === "calibration" && <CalibrationPanel />}
          {currentTab === "extractor" && (
            <div className="flex h-full min-h-0 flex-col xl:flex-row">
              <ExtractorPanel />
              <div className="relative min-h-[min(54vh,40rem)] flex-1 overflow-hidden border-t border-slate-200/70 dark:border-slate-800/80 xl:min-h-0 xl:border-l xl:border-t-0">
                <ExtractorCanvas />
              </div>
            </div>
          )}
          {currentTab === "lut-manager" && <LutManagerPanel />}
          {currentTab === "lut-details" && <LutDetailsPanel />}
          {currentTab === "lut-compare" && <LutComparePanel />}
          {currentTab === "five-color" && (
            <div className="flex h-full min-h-0">
              <FiveColorQueryPanel />
            </div>
          )}
        </div>
      </main>

      {/* ColorChecker calibration dialog, mounted at root like the main app. */}
      {/* ColorChecker 校色弹窗，与主应用一样挂在根部。 */}
      <ColorcheckerConfirmDialog />

      {/* Write-access password gate. Shown at boot whenever the server
          requires a password and the cached one (if any) doesn't unlock
          writes; can also be re-opened from the header pill. */}
      {/* 写入权限密码门禁。启动时若服务端要求密码且缓存密码无法解锁则弹出，
          也可通过 header 上的状态药丸再次打开。 */}
      <MlsAuthGate open={gateOpen} onClose={() => setGateOpen(false)} />
    </div>
  );
}

export default function MlsApp() {
  return (
    <I18nProvider>
      <MlsContent />
    </I18nProvider>
  );
}
