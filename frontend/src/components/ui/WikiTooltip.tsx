import {
  cloneElement,
  isValidElement,
  useState,
  type ReactElement,
  type MouseEvent,
  type ReactNode,
} from "react";
import type { Placement } from "@floating-ui/react";
import {
  useFloating,
  useHover,
  useFocus,
  useClick,
  useDismiss,
  useRole,
  useInteractions,
  offset,
  flip,
  shift,
  autoUpdate,
  FloatingPortal,
  FloatingFocusManager,
} from "@floating-ui/react";
import { AnimatePresence, motion } from "framer-motion";
import { useI18n } from "../../i18n/context";
import { buildWikiDocUrl, type WikiDocPath } from "../../utils/wikiDocs";

interface WikiTooltipProps {
  /** Trigger element to wrap */
  children: ReactNode;
  /** Tooltip title text */
  title: string;
  /** Tooltip description text */
  description: string;
  /** Optional wiki URL for external link */
  wikiUrl?: string;
  /** Locale-neutral path inside the public Lumina Wiki. */
  wikiPath?: WikiDocPath;
  /** Preferred placement direction, default "top" */
  placement?: Placement;
  /** Hover delay in ms before showing, default 600 */
  delay?: number;
  /** Optional className for the trigger wrapper. Use this when the tooltip
   *  must wrap a block-level / flex child without collapsing its width. */
  className?: string;
  /** Bind the tooltip directly to a single child element instead of adding a wrapper. */
  asChild?: boolean;
  /** Let an explicit help trigger open the tooltip on click or tap. */
  openOnClick?: boolean;
}

export default function WikiTooltip({
  children,
  title,
  description,
  wikiUrl,
  wikiPath,
  placement = "top",
  delay = 600,
  className,
  asChild = false,
  openOnClick = false,
}: WikiTooltipProps) {
  const { t, lang } = useI18n();
  const [isOpen, setIsOpen] = useState(false);
  const resolvedWikiUrl = wikiUrl ?? (wikiPath ? buildWikiDocUrl(wikiPath, lang) : undefined);
  const handleWikiClick = (event: MouseEvent<HTMLAnchorElement>) => {
    const openWiki = (
      window as Window & {
        electronAPI?: {
          openWiki?: (url: string) => Promise<unknown>;
        };
      }
    ).electronAPI?.openWiki;
    if (!openWiki || !resolvedWikiUrl) {
      return;
    }
    event.preventDefault();
    void openWiki(resolvedWikiUrl).catch(() => {
      // The main process intentionally rejects untrusted URLs. Do not fall
      // back to an unrestricted renderer navigation when that happens.
    });
  };

  // 1. useFloating — positioning engine + middleware
  const { refs, floatingStyles, context } = useFloating({
    open: isOpen,
    onOpenChange: setIsOpen,
    placement,
    middleware: [
      offset(8),
      flip(),
      shift({ padding: 8 }),
    ],
  });

  // 2. useHover — delay + safe hover bridge
  const hover = useHover(context, {
    delay: { open: delay, close: 150 },
    move: false,
  });

  // Keyboard users can reveal the same explanation by focusing the trigger.
  const focus = useFocus(context);

  // Click/tap opening is opt-in so action buttons keep their original behavior.
  const click = useClick(context, {
    enabled: openOnClick,
  });

  // 3. useDismiss — close on Escape
  const dismiss = useDismiss(context);

  // 4. useRole — aria role="tooltip"
  const role = useRole(context, { role: "tooltip" });

  // 5. merge interactions
  const { getReferenceProps, getFloatingProps } = useInteractions([
    hover,
    focus,
    click,
    dismiss,
    role,
  ]);

  const referenceElement =
    asChild && isValidElement(children) ? (
      cloneElement(
        children as ReactElement<Record<string, unknown>>,
        {
          ...getReferenceProps(
            (children as ReactElement<Record<string, unknown>>).props,
          ),
          ref: refs.setReference,
        } as Record<string, unknown>,
      )
    ) : (
      <span
        ref={refs.setReference}
        {...getReferenceProps()}
        className={className}
        style={className ? undefined : { display: "inline-block" }}
      >
        {children}
      </span>
    );

  const floatingElement = (
    <div
      ref={refs.setFloating}
      style={floatingStyles}
      {...getFloatingProps()}
      className={`z-[9999] ${resolvedWikiUrl ? "pointer-events-auto" : "pointer-events-none"}`}
    >
      <motion.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 4 }}
        transition={{ duration: 0.15 }}
        className="max-w-xs rounded-lg border border-slate-200 bg-slate-100 px-3 py-2.5 shadow-lg dark:border-slate-700 dark:bg-slate-800"
      >
        <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          {title}
        </div>
        {description && (
          <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 whitespace-pre-line">
            {description}
          </div>
        )}
        {resolvedWikiUrl && (
          <a
            href={resolvedWikiUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={handleWikiClick}
          >
            {t("wiki_tooltip_link")}
          </a>
        )}
      </motion.div>
    </div>
  );

  // 6. render
  return (
    <>
      {referenceElement}

      <FloatingPortal>
        <AnimatePresence>
          {isOpen &&
            (resolvedWikiUrl ? (
              <FloatingFocusManager
                context={context}
                modal={false}
                initialFocus={-1}
                returnFocus={false}
              >
                {floatingElement}
              </FloatingFocusManager>
            ) : (
              floatingElement
            ))}
        </AnimatePresence>
      </FloatingPortal>
    </>
  );
}
