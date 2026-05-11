/**
 * Shared types for the action-history store used by the bug report pipeline.
 * Bug 反馈复现包所用的操作历史数据类型。
 *
 * These types intentionally live outside `stores/actionHistoryStore.ts` so
 * downstream consumers (bugReportContext builders, tests, UI summaries)
 * can import them without creating a circular dependency back to the store.
 * 把类型抽离独立文件，避免反馈上下文组装、测试、摘要组件再引用 store 时出现循环依赖。
 */

/**
 * Snapshot of the fields that influence workflow reproduction at a point in
 * time. All fields are captured by-value at push-action time.
 * 工作流快照：捕获某一时刻所有可能影响复现结果的字段。
 */
export interface WorkflowSnapshot {
  color_mode: string | null;
  lut_name: string | null;
  source_version: "legacy" | "native" | "material" | null;
  selected_native_db_names: readonly string[];
  selected_material_dir_names: readonly string[];
  material_layer_count: number | null;
  material_layer_height_mm: number | null;
  material_backing_material_dir_name: string | null;
  active_tab: string;
}

/**
 * Discriminator for every kind of user-visible action the store tracks.
 * 操作历史记录的类型枚举。
 */
export type ActionType =
  | "upload_image"
  | "preview"
  | "generate"
  | "download"
  | "apply_recipe"
  | "region_replace"
  | "switch_tab"
  | "switch_subtab"
  | "color_mode_change"
  | "lut_change"
  | "source_version_change"
  | "material_selection_change"
  | "material_param_commit"
  | "api_error";

/**
 * Extra error details attached only to `api_error` action entries.
 * 仅当 action_type === 'api_error' 时附带的错误信息。
 */
export interface ActionErrorInfo {
  status_code: number;
  path: string;
  error_message: string;
}

/**
 * A single row in the action history ring.
 * 操作历史中的一条记录。
 */
export interface ActionEntry {
  /** Epoch milliseconds at push time. / 入栈时的毫秒时间戳。 */
  timestamp: number;
  action_type: ActionType;
  /** Optional map of field-level deltas captured by the caller. / 可选的字段级变化说明。 */
  changed_fields?: Record<string, { from: unknown; to: unknown }>;
  /** Snapshot of the workflow at push time. / 入栈时的工作流快照。 */
  snapshot: WorkflowSnapshot;
  /** Only present on api_error entries. / 仅 api_error 记录携带。 */
  error?: ActionErrorInfo;
}

/**
 * Work surface the session id belongs to.
 * Session id 所属的工作流。
 */
export type Workstream = "converter" | "single_stage";

/**
 * Entry in the 5-slot session ring. Stores workstream plus first/last seen
 * timestamps so developers can grep backend logs by session id after the
 * fact even if the source session has been cleaned up.
 * 会话环中的一条记录，保留首次/最后一次观察到的时间戳，便于后端日志追溯。
 */
export interface SessionRingEntry {
  workstream: Workstream;
  session_id: string;
  first_seen_at: number;
  last_seen_at: number;
}

/**
 * Exported payload shape consumed by bug report context builders.
 * 反馈上下文组装时导出的载荷结构。
 */
export interface ActionHistoryExport {
  history: ActionEntry[];
  session_history: SessionRingEntry[];
}
