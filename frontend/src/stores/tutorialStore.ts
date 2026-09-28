/**
 * Beginner tutorial orchestration store.
 * 新手引导编排 store。
 *
 * Owns the welcome/tour phase, the current step, first-run persistence, and
 * usage analytics. Components only render state and call these actions.
 * 负责欢迎窗/分步引导阶段、当前步骤、首次启动记录和使用统计；
 * 组件只负责渲染状态并调用这些 action。
 */
import { create } from "zustand";
import { trackLuminaEvent } from "../analytics/umami";
import { TUTORIAL_STEPS } from "../data/tutorialSteps";
import type { TutorialStep } from "../data/tutorialSteps";
import {
  hasTutorialBeenOffered,
  writeTutorialProgress,
} from "../utils/tutorialProgress";
import { useWidgetStore } from "./widgetStore";

export type TutorialPhase = "idle" | "welcome" | "touring";
/** How the tutorial was opened. 引导的打开方式。 */
export type TutorialTrigger = "auto" | "manual";
/** How the tutorial was skipped. 引导的跳过方式。 */
export type TutorialSkipVia = "welcome" | "skip_button" | "escape";

interface TutorialState {
  phase: TutorialPhase;
  stepIndex: number;
  trigger: TutorialTrigger;
  startedAtMs: number | null;
  /** Open the welcome dialog once per device. 每台设备只自动弹出一次欢迎窗。 */
  offerFirstRun: () => void;
  startTour: (trigger: TutorialTrigger) => void;
  next: () => void;
  back: () => void;
  skip: (via: TutorialSkipVia) => void;
  finish: () => void;
}

const TOTAL_STEPS = TUTORIAL_STEPS.length;

/**
 * Open the page, sub-tab, and panel a step needs so its anchor can render.
 * 打开步骤所需的页面、子页面和面板，使高亮目标能够渲染出来。
 *
 * Args:
 *     step (TutorialStep): Step about to be shown. 即将显示的步骤。
 */
export function applyTutorialStepPrepare(step: TutorialStep): void {
  const prepare = step.prepare;
  if (!prepare) {
    return;
  }
  const widgetStore = useWidgetStore.getState();
  if (prepare.tab && widgetStore.activeTab !== prepare.tab) {
    widgetStore.setActiveTab(prepare.tab);
  }
  if (
    prepare.converterSubTab &&
    widgetStore.activeConverterSubTab !== prepare.converterSubTab
  ) {
    widgetStore.setActiveConverterSubTab(prepare.converterSubTab);
  }
  if (prepare.widget) {
    const layout = useWidgetStore.getState().widgets[prepare.widget];
    if (layout && !layout.visible) {
      widgetStore.toggleVisible(prepare.widget);
    }
    if (layout && layout.collapsed) {
      widgetStore.toggleCollapse(prepare.widget);
    }
  }
}

function elapsedSeconds(startedAtMs: number | null): number | null {
  if (startedAtMs === null) {
    return null;
  }
  return Math.max(0, Math.round((Date.now() - startedAtMs) / 1000));
}

function trackStepView(trigger: TutorialTrigger, stepIndex: number): void {
  trackLuminaEvent("lumina_tutorial_step_view", {
    trigger,
    step_id: TUTORIAL_STEPS[stepIndex]?.id ?? null,
    step_index: stepIndex + 1,
    total_steps: TOTAL_STEPS,
  });
}

export const useTutorialStore = create<TutorialState>()((set, get) => {
  const goToStep = (stepIndex: number) => {
    const step = TUTORIAL_STEPS[stepIndex];
    if (!step) {
      return;
    }
    applyTutorialStepPrepare(step);
    set({ stepIndex });
    trackStepView(get().trigger, stepIndex);
  };

  return {
    phase: "idle",
    stepIndex: 0,
    trigger: "auto",
    startedAtMs: null,

    offerFirstRun: () => {
      if (get().phase !== "idle" || hasTutorialBeenOffered()) {
        return;
      }
      // Record the offer before any choice so closing the app mid-dialog
      // still counts as "shown once".
      // 在用户做选择前就记录，确保中途关闭软件也算「已弹出过一次」。
      writeTutorialProgress("offered");
      set({ phase: "welcome", trigger: "auto", stepIndex: 0, startedAtMs: null });
      trackLuminaEvent("lumina_tutorial_offered");
    },

    startTour: (trigger) => {
      if (get().phase === "touring") {
        return;
      }
      set({ phase: "touring", trigger, startedAtMs: Date.now() });
      trackLuminaEvent("lumina_tutorial_started", { trigger });
      goToStep(0);
    },

    next: () => {
      const { phase, stepIndex, finish } = get();
      if (phase !== "touring") {
        return;
      }
      if (stepIndex >= TOTAL_STEPS - 1) {
        finish();
        return;
      }
      goToStep(stepIndex + 1);
    },

    back: () => {
      const { phase, stepIndex } = get();
      if (phase !== "touring" || stepIndex <= 0) {
        return;
      }
      goToStep(stepIndex - 1);
    },

    skip: (via) => {
      const { phase, stepIndex, trigger, startedAtMs } = get();
      if (phase === "idle") {
        return;
      }
      const onWelcome = phase === "welcome";
      writeTutorialProgress("skipped");
      trackLuminaEvent("lumina_tutorial_skipped", {
        trigger,
        via,
        step_id: onWelcome ? "welcome" : (TUTORIAL_STEPS[stepIndex]?.id ?? null),
        step_index: onWelcome ? 0 : stepIndex + 1,
        total_steps: TOTAL_STEPS,
        elapsed_s: elapsedSeconds(startedAtMs),
      });
      set({ phase: "idle", stepIndex: 0, startedAtMs: null });
    },

    finish: () => {
      const { phase, trigger, startedAtMs } = get();
      if (phase !== "touring") {
        return;
      }
      writeTutorialProgress("completed");
      trackLuminaEvent("lumina_tutorial_completed", {
        trigger,
        total_steps: TOTAL_STEPS,
        elapsed_s: elapsedSeconds(startedAtMs),
      });
      set({ phase: "idle", stepIndex: 0, startedAtMs: null });
    },
  };
});
