import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { JSX } from "react";
import { createPortal } from "react-dom";
import { motion, useReducedMotion } from "framer-motion";
import { useI18n } from "../../i18n/context";
import { TUTORIAL_STEPS } from "../../data/tutorialSteps";
import type { TutorialStep } from "../../data/tutorialSteps";
import { useTutorialAnchor } from "../../hooks/useTutorialAnchor";
import { useTutorialStore } from "../../stores/tutorialStore";
import Button from "../ui/Button";
import { computeTutorialCardPosition } from "./tutorialPlacement";
import type { TutorialSize } from "./tutorialPlacement";

/** Extra room drawn around the spotlighted element. 高亮框相对目标的外扩距离。 */
const SPOTLIGHT_PADDING_PX = 6;
const SPOTLIGHT_RADIUS_PX = 14;
const DEFAULT_CARD_SIZE: TutorialSize = { width: 380, height: 280 };

function readViewport(): TutorialSize {
  return { width: window.innerWidth, height: window.innerHeight };
}

function useViewportSize(): TutorialSize {
  const [viewport, setViewport] = useState<TutorialSize>(readViewport);
  useEffect(() => {
    const handleResize = () => setViewport(readViewport());
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);
  return viewport;
}

function TutorialStepDetails({ step }: { step: TutorialStep }) {
  const { t } = useI18n();
  return (
    <>
      {step.flowKeys && step.flowKeys.length > 0 ? (
        <ol
          className="mt-3 flex flex-wrap items-center gap-1.5"
          aria-label={t("tutorial_flow_label")}
          data-testid="tutorial-flow"
        >
          {/* Numbered chips instead of arrows so the order stays readable
              however the row wraps. */}
          {step.flowKeys.map((key, index) => (
            <li
              key={key}
              className="flex items-center gap-1.5 rounded-full bg-blue-50 py-1 pl-1 pr-2.5 text-xs font-medium text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
            >
              <span
                aria-hidden="true"
                className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[10px] font-semibold text-white dark:bg-blue-500"
              >
                {index + 1}
              </span>
              {t(key)}
            </li>
          ))}
        </ol>
      ) : null}
      {step.needKey || step.fitKey ? (
        <dl className="mt-3 flex flex-col gap-1.5 rounded-xl border border-slate-200/80 bg-slate-100/60 px-3 py-2 text-xs leading-5 dark:border-slate-700/60 dark:bg-slate-900/50">
          {step.needKey ? (
            <div>
              <dt className="inline font-semibold text-slate-700 dark:text-slate-200">
                {t("tutorial_need_label")}
              </dt>
              <dd className="inline text-slate-600 dark:text-slate-300">{t(step.needKey)}</dd>
            </div>
          ) : null}
          {step.fitKey ? (
            <div>
              <dt className="inline font-semibold text-slate-700 dark:text-slate-200">
                {t("tutorial_fit_label")}
              </dt>
              <dd className="inline text-slate-600 dark:text-slate-300">{t(step.fitKey)}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </>
  );
}

/**
 * Spotlight tour: dims the app, outlines the current step's element, and
 * shows an explanation card beside it.
 * 分步高亮引导：压暗界面、框出当前步骤的元素，并在旁边显示说明卡片。
 *
 * The whole app is blocked while the tour runs so a stray click cannot open a
 * file picker or start a job; the tour only explains. When the element cannot
 * be found the card is centered and the tour continues.
 * 引导期间屏蔽整个界面，避免误触打开文件选择框或启动任务；引导只做讲解。
 * 找不到目标元素时卡片居中显示，引导照常进行。
 */
export default function TutorialTour(): JSX.Element | null {
  const { t } = useI18n();
  const stepIndex = useTutorialStore((s) => s.stepIndex);
  const next = useTutorialStore((s) => s.next);
  const back = useTutorialStore((s) => s.back);
  const skip = useTutorialStore((s) => s.skip);
  const step = TUTORIAL_STEPS[stepIndex] ?? TUTORIAL_STEPS[0];
  const isFirst = stepIndex === 0;
  const isLast = stepIndex === TUTORIAL_STEPS.length - 1;

  const anchor = useTutorialAnchor(step.anchor);
  const viewport = useViewportSize();
  const reduceMotion = useReducedMotion();
  const cardRef = useRef<HTMLDivElement>(null);
  const [cardSize, setCardSize] = useState<TutorialSize>(DEFAULT_CARD_SIZE);

  // Card height changes with each step's copy; re-measure whenever it resizes.
  useLayoutEffect(() => {
    const card = cardRef.current;
    if (!card) {
      return;
    }
    const measure = () => {
      const width = card.offsetWidth;
      const height = card.offsetHeight;
      if (width <= 0) {
        return;
      }
      setCardSize((prev) =>
        prev.width === width && prev.height === height ? prev : { width, height },
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(card);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    cardRef.current?.focus({ preventScroll: true });
  }, [stepIndex, anchor.status]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        skip("escape");
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        next();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        back();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [next, back, skip]);

  if (typeof document === "undefined") {
    return null;
  }

  const spotlight =
    anchor.status === "found" && anchor.rect
      ? {
          top: anchor.rect.top - SPOTLIGHT_PADDING_PX,
          left: anchor.rect.left - SPOTLIGHT_PADDING_PX,
          width: anchor.rect.width + SPOTLIGHT_PADDING_PX * 2,
          height: anchor.rect.height + SPOTLIGHT_PADDING_PX * 2,
        }
      : null;
  const position = computeTutorialCardPosition(spotlight, cardSize, viewport);
  const showCard = anchor.status !== "searching";
  const transition = reduceMotion ? { duration: 0 } : { duration: 0.2, ease: "easeOut" as const };

  return createPortal(
    <div className="fixed inset-0 z-[9000]" data-testid="tutorial-tour">
      {/* Click shield: the tour explains only, it never lets clicks through. */}
      <div
        className="absolute inset-0"
        style={spotlight ? undefined : { background: "var(--surface-scrim)" }}
        onClick={(event) => event.stopPropagation()}
        onPointerDown={(event) => event.stopPropagation()}
        data-testid="tutorial-click-shield"
      />

      {spotlight ? (
        <>
          {/* Dim layer with a rounded cut-out. The app disables box-shadow
              globally, so the scrim is drawn with an SVG mask instead. */}
          <svg aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full">
            <defs>
              <mask id="tutorial-spotlight-mask">
                <rect width="100%" height="100%" fill="white" />
                <motion.rect
                  rx={SPOTLIGHT_RADIUS_PX}
                  fill="black"
                  initial={false}
                  animate={{
                    x: spotlight.left,
                    y: spotlight.top,
                    width: spotlight.width,
                    height: spotlight.height,
                  }}
                  transition={transition}
                />
              </mask>
            </defs>
            <rect
              width="100%"
              height="100%"
              mask="url(#tutorial-spotlight-mask)"
              style={{ fill: "var(--surface-scrim)" }}
            />
          </svg>
          <motion.div
            aria-hidden="true"
            data-testid="tutorial-spotlight"
            className="pointer-events-none absolute border-2 border-blue-500 dark:border-blue-400"
            style={{ borderRadius: SPOTLIGHT_RADIUS_PX }}
            initial={false}
            animate={spotlight}
            transition={transition}
          />
        </>
      ) : null}

      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tutorial-step-title"
        aria-describedby="tutorial-step-body"
        tabIndex={-1}
        data-testid="tutorial-card"
        data-side={position.side}
        className="absolute w-[min(380px,calc(100vw-32px))] rounded-2xl border p-5 shadow-2xl outline-none"
        style={{
          top: position.top,
          left: position.left,
          visibility: showCard ? "visible" : "hidden",
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
      >
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-semibold text-blue-600 dark:text-blue-400">
            {t("tutorial_progress_label")} · {stepIndex + 1} / {TUTORIAL_STEPS.length}
          </span>
          <button
            type="button"
            data-testid="tutorial-skip-button"
            onClick={() => skip("skip_button")}
            className="rounded-lg px-2 py-1 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            {t("tutorial_skip")}
          </button>
        </div>

        <h2
          id="tutorial-step-title"
          className="mt-2 text-base font-semibold text-slate-800 dark:text-slate-100"
        >
          {t(step.titleKey)}
        </h2>
        <p
          id="tutorial-step-body"
          className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-600 dark:text-slate-300"
        >
          {t(step.bodyKey)}
        </p>

        <TutorialStepDetails step={step} />

        <div className="mt-4 flex items-center justify-end gap-2">
          {!isFirst ? (
            <Button label={t("tutorial_back")} variant="secondary" size="sm" onClick={back} />
          ) : null}
          <Button
            label={isLast ? t("tutorial_done") : t("tutorial_next")}
            variant="primary"
            size="sm"
            onClick={next}
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}
