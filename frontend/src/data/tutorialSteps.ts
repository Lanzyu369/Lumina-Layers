/**
 * Beginner tutorial step definitions.
 * 新手引导步骤定义。
 *
 * Each step points at a UI element through its `data-tutorial` attribute and
 * names the page/panel that must be open before the element can be shown.
 * The tour only explains; it never uploads, previews, or generates anything.
 * 每一步通过 `data-tutorial` 属性指向界面元素，并声明显示前需要打开的页面/面板。
 * 引导只做讲解，不会替用户上传、预览或生成。
 */
import type { ConverterSubTabId, TabId, WidgetId } from "../types/widget";

export type TutorialStepId =
  | "primary-tabs"
  | "image-upload"
  | "color-source"
  | "source-legacy-lut"
  | "source-inferred-lut"
  | "source-material-archive"
  | "output-size"
  | "preview"
  | "view-3d"
  | "generate"
  | "help";

/** UI state a step needs before its anchor can be found. 步骤显示前需要的界面状态。 */
export interface TutorialStepPrepare {
  tab?: TabId;
  converterSubTab?: ConverterSubTabId;
  widget?: WidgetId;
}

/** One "gesture → effect" row, e.g. left-drag → rotate. 一行「操作 → 效果」说明。 */
export interface TutorialControlHint {
  gestureKey: string;
  effectKey: string;
}

export interface TutorialStep {
  id: TutorialStepId;
  /** `data-tutorial` value to spotlight; null shows a centered card. 高亮目标；null 时卡片居中。 */
  anchor: string | null;
  titleKey: string;
  bodyKey: string;
  /** Short principle chain rendered as numbered chips. 原理流程芯片。 */
  flowKeys?: readonly string[];
  /** "What you need" line. 「需要准备」说明。 */
  needKey?: string;
  /** "Best for" line. 「适合」说明。 */
  fitKey?: string;
  /** Gesture list rendered as a small table. 操作说明列表。 */
  controlHints?: readonly TutorialControlHint[];
  /**
   * Let the user try the spotlighted area (clicks/drags/scroll pass through
   * the cut-out); everything outside stays blocked.
   * 允许用户在高亮区域内直接试用（点击、拖动、滚轮可穿透），区域外仍屏蔽。
   */
  interactive?: boolean;
  /**
   * Place the card inside the spotlight near its bottom edge, for targets
   * too large to leave room beside them.
   * 卡片放在高亮区域内部靠下，适用于太大、旁边放不下卡片的目标。
   */
  cardInside?: boolean;
  prepare?: TutorialStepPrepare;
}

const BASIC_SETTINGS: TutorialStepPrepare = {
  tab: "converter",
  converterSubTab: "core",
  widget: "basic-settings",
};

const ACTION_BAR: TutorialStepPrepare = {
  tab: "converter",
  converterSubTab: "core",
  widget: "action-bar",
};

export const TUTORIAL_STEPS: readonly TutorialStep[] = [
  {
    id: "primary-tabs",
    anchor: "primary-tabs",
    titleKey: "tutorial_step_tabs_title",
    bodyKey: "tutorial_step_tabs_body",
    prepare: { tab: "converter", converterSubTab: "core" },
  },
  {
    id: "image-upload",
    anchor: "image-upload",
    titleKey: "tutorial_step_upload_title",
    bodyKey: "tutorial_step_upload_body",
    prepare: BASIC_SETTINGS,
  },
  {
    id: "color-source",
    anchor: "color-source",
    titleKey: "tutorial_step_source_title",
    bodyKey: "tutorial_step_source_body",
    prepare: BASIC_SETTINGS,
  },
  {
    id: "source-legacy-lut",
    anchor: "color-source",
    titleKey: "tutorial_step_legacy_title",
    bodyKey: "tutorial_step_legacy_body",
    flowKeys: [
      "tutorial_flow_legacy_print",
      "tutorial_flow_legacy_extract",
      "tutorial_flow_legacy_table",
    ],
    needKey: "tutorial_step_legacy_need",
    fitKey: "tutorial_step_legacy_fit",
    prepare: BASIC_SETTINGS,
  },
  {
    id: "source-inferred-lut",
    anchor: "color-source",
    titleKey: "tutorial_step_inferred_title",
    bodyKey: "tutorial_step_inferred_body",
    flowKeys: [
      "tutorial_flow_inferred_database",
      "tutorial_flow_inferred_predict",
      "tutorial_flow_inferred_table",
    ],
    needKey: "tutorial_step_inferred_need",
    fitKey: "tutorial_step_inferred_fit",
    prepare: BASIC_SETTINGS,
  },
  {
    id: "source-material-archive",
    anchor: "color-source",
    titleKey: "tutorial_step_material_title",
    bodyKey: "tutorial_step_material_body",
    flowKeys: [
      "tutorial_flow_material_card",
      "tutorial_flow_material_measure",
      "tutorial_flow_material_solve",
    ],
    needKey: "tutorial_step_material_need",
    fitKey: "tutorial_step_material_fit",
    prepare: BASIC_SETTINGS,
  },
  {
    id: "output-size",
    anchor: "output-size",
    titleKey: "tutorial_step_size_title",
    bodyKey: "tutorial_step_size_body",
    prepare: BASIC_SETTINGS,
  },
  {
    id: "preview",
    anchor: "preview-button",
    titleKey: "tutorial_step_preview_title",
    bodyKey: "tutorial_step_preview_body",
    prepare: ACTION_BAR,
  },
  {
    id: "view-3d",
    anchor: "viewport-3d",
    titleKey: "tutorial_step_view3d_title",
    bodyKey: "tutorial_step_view3d_body",
    controlHints: [
      { gestureKey: "tutorial_control_left_drag", effectKey: "tutorial_control_rotate" },
      { gestureKey: "tutorial_control_right_drag", effectKey: "tutorial_control_pan" },
      { gestureKey: "tutorial_control_wheel", effectKey: "tutorial_control_zoom" },
      { gestureKey: "tutorial_control_space_drag", effectKey: "tutorial_control_space_pan" },
    ],
    interactive: true,
    cardInside: true,
    prepare: { tab: "converter", converterSubTab: "core" },
  },
  {
    id: "generate",
    anchor: "generate-button",
    titleKey: "tutorial_step_generate_title",
    bodyKey: "tutorial_step_generate_body",
    prepare: ACTION_BAR,
  },
  {
    id: "help",
    anchor: "tutorial-launcher",
    titleKey: "tutorial_step_help_title",
    bodyKey: "tutorial_step_help_body",
  },
];

/**
 * Collect every translation key referenced by the tutorial steps.
 * 收集引导步骤引用的全部翻译键。
 */
export function collectTutorialStepKeys(
  steps: readonly TutorialStep[] = TUTORIAL_STEPS,
): string[] {
  return steps.flatMap((step) => [
    step.titleKey,
    step.bodyKey,
    ...(step.flowKeys ?? []),
    ...(step.needKey ? [step.needKey] : []),
    ...(step.fitKey ? [step.fitKey] : []),
    ...(step.controlHints ?? []).flatMap((hint) => [hint.gestureKey, hint.effectKey]),
  ]);
}
