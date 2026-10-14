import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useIsPresent } from "framer-motion";
import { useI18n } from "../i18n/context";
import { useOutsideInteraction } from "../hooks/useOutsideInteraction";
import { BugReportButton } from "./BugReportButton";
import { LanguageToggle } from "./LanguageToggle";
import { ThemeToggle } from "./ThemeToggle";
import { TutorialLauncherButton } from "./tutorial/TutorialLauncherButton";
import { HeaderTooltip } from "./ui/HeaderTooltip";
import {
  HEADER_ICON_BUTTON_CLASS,
  HEADER_MENU_DIVIDER_CLASS,
  HEADER_MENU_PANEL_CLASS,
} from "./ui/headerControls";

export type BackendStatus = "checking" | "ok" | "fail";

interface HeaderMenuProps {
  backendStatus: BackendStatus;
  /** Ticket being reproduced; null outside reproduction mode. */
  reproTicketId: string | null;
  onReportBug: () => void;
}

interface StatusView {
  testId: string;
  labelKey: string;
  dotClass: string;
  textClass: string;
}

const BACKEND_STATUS_VIEWS: Record<BackendStatus, StatusView> = {
  checking: {
    testId: "health-badge-checking",
    labelKey: "app_checking_backend",
    dotClass: "animate-pulse bg-slate-400",
    textClass: "text-slate-500 dark:text-slate-400",
  },
  ok: {
    testId: "health-badge-ok",
    labelKey: "app_backend_connected",
    dotClass: "bg-green-500",
    textClass: "text-green-700 dark:text-green-300",
  },
  fail: {
    testId: "health-badge-fail",
    labelKey: "app_backend_unreachable",
    dotClass: "bg-red-500",
    textClass: "text-red-600 dark:text-red-300",
  },
};

interface TriggerAlert {
  dotClass: string;
  labelKey: string;
}

function resolveTriggerAlert(
  backendStatus: BackendStatus,
  reproTicketId: string | null,
): TriggerAlert | null {
  if (backendStatus === "fail") {
    return { dotClass: "bg-red-500", labelKey: "app_backend_unreachable" };
  }
  if (reproTicketId) {
    return { dotClass: "bg-amber-600 dark:bg-amber-400", labelKey: "header_menu_repro_mode" };
  }
  return null;
}

/**
 * Collapsible header menu for infrequent controls and status indicators.
 * 顶栏“更多选项”菜单，收纳不常用的功能和状态标识。
 *
 * The trigger shows a dot only when something needs attention (backend
 * unreachable or reproduction mode), so problems stay visible while closed.
 * 只有后端不可达或处于复现模式时，菜单按钮才显示提示点，菜单收起时问题依然可见。
 */
export function HeaderMenu({ backendStatus, reproTicketId, onReportBug }: HeaderMenuProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const alertId = useId();

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) {
      triggerRef.current?.focus();
    }
  }, []);
  const closeWithoutFocus = useCallback(() => close(false), [close]);

  useOutsideInteraction(rootRef, closeWithoutFocus, open);

  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) {
        return;
      }
      close(rootRef.current?.contains(document.activeElement) ?? false);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, close]);

  const alert = resolveTriggerAlert(backendStatus, reproTicketId);

  return (
    <div ref={rootRef} className="relative">
      <HeaderTooltip label={t("header_menu_label")} suppressed={open}>
        <button
          ref={triggerRef}
          type="button"
          data-testid="header-menu-button"
          data-tutorial="tutorial-launcher"
          data-backend-status={backendStatus}
          aria-label={t("header_menu_label")}
          aria-describedby={alert ? alertId : undefined}
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          onClick={() => setOpen((value) => !value)}
          className={`${HEADER_ICON_BUTTON_CLASS} relative`}
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          >
            <path d="M4 7h16M4 12h16M4 17h16" />
          </svg>
          {alert && (
            <>
              <span
                data-testid="header-menu-alert"
                aria-hidden="true"
                className={`absolute right-1.5 top-1.5 h-2 w-2 rounded-full ring-2 ring-slate-100 dark:ring-slate-900 ${alert.dotClass}`}
              />
              {/* aria-label names the button, so the alert is exposed as its description. */}
              <span id={alertId} className="sr-only">
                {t(alert.labelKey)}
              </span>
            </>
          )}
        </button>
      </HeaderTooltip>

      <AnimatePresence>
        {open && (
          <HeaderMenuPanel id={panelId} onItemSelected={() => close(true)}>
            <LanguageToggle />
            <ThemeToggle />
            <TutorialLauncherButton />
            <BugReportButton onClick={onReportBug} />
            <div className={HEADER_MENU_DIVIDER_CLASS} />
            <div role="status" className="flex flex-col gap-1.5 px-3 py-1.5">
              <BackendStatusLine status={backendStatus} />
              {reproTicketId && <ReproModeLine ticketId={reproTicketId} />}
            </div>
          </HeaderMenuPanel>
        )}
      </AnimatePresence>
    </div>
  );
}

interface HeaderMenuPanelProps {
  id: string;
  /** Called after any menu row (a button) is activated. 任一菜单项按钮被触发后调用。 */
  onItemSelected: () => void;
  children: ReactNode;
}

function HeaderMenuPanel({ id, onItemSelected, children }: HeaderMenuPanelProps) {
  // While fading out the panel must not take a second click, which would
  // toggle the language or theme straight back.
  const isPresent = useIsPresent();

  return (
    <motion.div
      id={id}
      inert={!isPresent}
      initial={{ opacity: 0, y: -10, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -10, scale: 0.95 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className={`${HEADER_MENU_PANEL_CLASS} w-60`}
      onClick={(event) => {
        if ((event.target as Element).closest("button")) {
          onItemSelected();
        }
      }}
    >
      {children}
    </motion.div>
  );
}

function BackendStatusLine({ status }: { status: BackendStatus }) {
  const { t } = useI18n();
  const view = BACKEND_STATUS_VIEWS[status];

  return (
    <span
      data-testid={view.testId}
      className={`flex items-center gap-2 text-xs font-medium ${view.textClass}`}
    >
      <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${view.dotClass}`} />
      {t(view.labelKey)}
    </span>
  );
}

function ReproModeLine({ ticketId }: { ticketId: string }) {
  const { t } = useI18n();

  return (
    <span
      data-testid="repro-mode-badge"
      className="flex min-w-0 items-center gap-2 text-xs font-medium text-amber-700 dark:text-amber-300"
    >
      <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full bg-amber-400" />
      <span className="truncate">
        {t("header_menu_repro_mode_ticket").replace("{{ticket}}", ticketId)}
      </span>
    </span>
  );
}
