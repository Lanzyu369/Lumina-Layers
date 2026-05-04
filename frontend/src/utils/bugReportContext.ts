import type { BugReportContextPayload } from "../api/feedback";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useWidgetStore } from "../stores/widgetStore";

declare const __LUMINA_VERSION__: string | undefined;

export function collectBugReportContext(): BugReportContextPayload {
  const converter = useConverterStore.getState();
  const singleStage = useSingleStageStore.getState();
  const settings = useSettingsStore.getState();
  const widget = useWidgetStore.getState();

  // Prefer the active workstream's live store value over the persisted
  // ``settings.lastColorMode`` / ``settings.lastLutName`` preference.
  // The settings fields only change on explicit persist events, so they
  // lag in-session switches (e.g. user is working in 8-Color Max on the
  // converter tab while settings still hold the 4-Color RYBW default,
  // making the bug report misleading). For ``activeTab === "converter"``
  // we read directly from the converter store; the single-stage
  // workstream does not own these fields, so we fall back to the
  // settings preference there for backwards compatibility.
  // 优先读取当前激活工作流 store 中的实时值，而不是仅在显式持久化时才更新
  // 的 settings.lastColorMode / lastLutName。后者会滞后于会话内切换
  // （例如用户在 converter tab 切到 8-Color Max，但 settings 仍是默认的
  // 4-Color RYBW，导致 bug 反馈里 color_mode 误导）。当 activeTab 为
  // "converter" 时直接读 converter store；单阶段工作流不维护这两个字段，
  // 回落到 settings 偏好以保持向后兼容。
  const isConverterActive = widget.activeTab === "converter";
  const sourceVersion = isConverterActive ? converter.source_version ?? null : null;
  const isMaterialSource = sourceVersion === "material";
  const isNativeSource = sourceVersion === "native";
  const colorMode = isConverterActive
    ? (isMaterialSource ? null : converter.color_mode || null)
    : settings.lastColorMode || null;
  const lutName = isConverterActive
    ? (isMaterialSource ? null : converter.lut_name || null)
    : settings.lastLutName || null;

  return {
    url: typeof window !== "undefined" ? window.location.href : "",
    user_agent: typeof navigator !== "undefined" ? navigator.userAgent : "",
    screen_width: typeof window !== "undefined" ? window.innerWidth : 0,
    screen_height: typeof window !== "undefined" ? window.innerHeight : 0,
    device_pixel_ratio: typeof window !== "undefined" ? window.devicePixelRatio : 1,
    app_version: typeof __LUMINA_VERSION__ === "string" ? __LUMINA_VERSION__ : "unknown",
    language: settings.language,
    theme: settings.theme,
    active_tab: widget.activeTab,
    active_session_ids: {
      converter: converter.sessionId ?? null,
      single_stage: singleStage.sessionId ?? null,
    },
    color_mode: colorMode,
    lut_name: lutName,
    source_version: sourceVersion,
    selected_native_brand_key: isNativeSource ? converter.selectedNativeBrandKey || null : null,
    selected_native_db_names: isNativeSource ? converter.selectedNativeDbNames : [],
    selected_material_dir_names: isMaterialSource ? converter.selectedMaterialDirNames : [],
    material_layer_count: isMaterialSource ? converter.materialLayerCount : null,
    material_layer_height_mm: isMaterialSource ? converter.materialLayerHeightMm : null,
    material_backing_material_dir_name: isMaterialSource ? converter.materialBackingMaterialDirName : null,
    recent_client_logs: [],
  };
}
