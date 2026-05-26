import type {
  BugReportContextPayload,
  FinalArtifactRef,
  OriginalImageRef,
} from "../api/feedback";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useWidgetStore } from "../stores/widgetStore";
import { buildAdvancedParams } from "./advancedParamsBuilder";
import { getRecentClientLogs } from "./clientLog";

declare const __LUMINA_VERSION__: string | undefined;

/**
 * Best-effort shape of the converter generation artifact. The converter
 * store tracks ``downloadUrl`` (typically ``/api/files/<file_id>``) and
 * ``threemfDiskPath`` after a successful ``convertGenerate``. When either
 * is populated we treat it as evidence of a recent artifact.
 *
 * 最近一次生成的产物引用：converter store 在生成成功后写入 downloadUrl /
 * threemfDiskPath；任一存在即视为最近产物。
 */
function deriveFinalArtifact(): FinalArtifactRef | null {
  const converter = useConverterStore.getState();
  const downloadUrl = converter.downloadUrl ?? null;
  const diskPath = converter.threemfDiskPath ?? null;
  if (!downloadUrl && !diskPath) {
    return null;
  }
  const artifactType: FinalArtifactRef["artifact_type"] = diskPath
    ? diskPath.toLowerCase().endsWith(".zip")
      ? "zip"
      : "3mf"
    : converter.largeFormatEnabled
      ? "zip"
      : downloadUrl && downloadUrl.toLowerCase().includes(".zip")
        ? "zip"
        : "3mf";
  return {
    session_id: converter.sessionId ?? null,
    download_url: downloadUrl,
    artifact_type: artifactType,
    disk_path: diskPath,
    source: "converter",
  };
}

/**
 * Reference to the source image the user uploaded in the currently active
 * workstream. We only record identifying metadata here; the backend reads
 * the actual bytes through its own FileRegistry using ``session_id``.
 *
 * 指向当前活动工作流中用户上传的原图的引用；只带元信息，真实内容由后端
 * 通过 session_id 去 FileRegistry 取。
 */
function deriveOriginalImageRef(
  isConverterActive: boolean,
  converterSessionId: string | null,
  singleStageSessionId: string | null,
): OriginalImageRef | null {
  if (isConverterActive) {
    if (!converterSessionId) return null;
    return {
      session_id: converterSessionId,
      filename: null,
      source: "converter",
    };
  }
  if (singleStageSessionId) {
    return {
      session_id: singleStageSessionId,
      filename: null,
      source: "single_stage",
    };
  }
  return null;
}

export function collectBugReportContext(): BugReportContextPayload {
  const converter = useConverterStore.getState();
  const singleStage = useSingleStageStore.getState();
  const settings = useSettingsStore.getState();
  const widget = useWidgetStore.getState();

  // Eagerly merge any sessionStorage-persisted entries so a page refresh
  // between the bug happening and the user clicking "Report" still ships the
  // complete action history. ``loadPersistedHistory`` is idempotent and
  // swallow-safe so calling it here is zero-risk.
  // 在合并上下文前显式加载持久化的历史，确保刷新页面后仍能保留现场。
  useActionHistoryStore.getState().loadPersistedHistory();
  const actionExport = useActionHistoryStore.getState().exportForReport();

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
    recent_client_logs: getRecentClientLogs(),
    action_history: actionExport.history,
    session_history: actionExport.session_history,
    active_original_image_ref: deriveOriginalImageRef(
      isConverterActive,
      converter.sessionId ?? null,
      singleStage.sessionId ?? null,
    ),
    active_final_artifact_ref: deriveFinalArtifact(),
    advanced_params: buildAdvancedParams(converter, widget.activeTab, {
      maxBytes: 8192,
      svgPixelsPerMm: settings.svgPixelsPerMm,
    }),
  };
}
