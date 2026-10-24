/* eslint-disable react-refresh/only-export-components */
import { useRef, useEffect, useCallback, useState } from "react";
import { useExtractorStore } from "../stores/extractorStore";
import { ExtractorColorMode, ExtractorPage, type LutPreviewResolvedCell } from "../api/types";
import { resolveLutPreviewCell } from "../api/extractor";
import { apiErrorToVisibleMessage } from "../api/client";
import { useI18n } from "../i18n/context";
import { getObjectFitRect, type RenderedImageRect } from "../utils/lutCoordUtils";
import { hexToRgb } from "../utils/colorUtils";
import { UI_COLOR_TOKENS } from "../theme/uiTokens";

// ========== Corner Labels Mapping (exported for testing) ==========

/**
 * Position i18n keys in canonical placement order (TL, TR, BR, BL).
 * 角点位置国际化键（按落点顺序：左上、右上、右下、左下）。
 */
export const CORNER_POSITION_KEYS = [
  "ext_corner_pos_tl",
  "ext_corner_pos_tr",
  "ext_corner_pos_br",
  "ext_corner_pos_bl",
] as const;

/**
 * Per-color-mode mapping to color-name i18n keys. `null` = position only.
 * 每个颜色模式对应的颜色名 i18n 键数组；为 null 时仅显示位置。
 */
const CORNER_COLOR_KEYS: Record<string, Array<string | null>> = {
  "BW (Black & White)": [
    "ext_color_white",
    "ext_color_black",
    "ext_color_black",
    "ext_color_black",
  ],
  "4-Color (CMYW)": [
    "ext_color_white",
    "ext_color_cyan",
    "ext_color_magenta",
    "ext_color_yellow",
  ],
  "4-Color (RYBW)": [null, null, null, null],
  "6-Color (CMYWGK 1296)": [
    "ext_color_white",
    "ext_color_cyan",
    "ext_color_magenta",
    "ext_color_yellow",
  ],
  "6-Color (RYBWGK 1296)": [
    "ext_color_white",
    "ext_color_red",
    "ext_color_blue",
    "ext_color_yellow",
  ],
  "8-Color Max": [null, null, null, null],
  // 5-Color Extended page 1 uses the RYBW-style corners (TL=White, TR=Red,
  // BR=Blue, BL=Yellow) — matching ``ColorSystem.FIVE_COLOR_EXTENDED``'s
  // ``corner_labels`` on the backend. Page 2 swaps TL to Blue and BR to Black
  // (see ``core/extractor.py::draw_corner_points``). Use
  // ``buildCornerLabels`` to pick the right list; this entry is the page-1
  // default.
  // 5-Color Extended 第 1 页使用 RYBW 式角点（左上=白，右上=红，右下=蓝，
  // 左下=黄）—— 与后端 ``ColorSystem.FIVE_COLOR_EXTENDED`` 的
  // ``corner_labels`` 一致。第 2 页左上变为蓝、右下变为黑（见
  // ``core/extractor.py::draw_corner_points``）。请用 ``buildCornerLabels``
  // 选择正确列表；此条目为第 1 页的默认值。
  "5-Color Extended": [
    "ext_color_white",
    "ext_color_red",
    "ext_color_blue",
    "ext_color_yellow",
  ],
};

// ========== Page-specific overrides for 5-Color Extended ==========
//
// 5-Color Extended spans two calibration sheets. Page 2 intentionally uses a
// different corner layout from page 1 so that the extractor can capture the
// outer "Black" material plus a repeated Blue anchor:
//
//   - Page 1 corners: White / Red / Blue / Yellow (= standard RYBW 4-corner).
//   - Page 2 corners: Blue  / Red / Black / Yellow.
//
// Keep this table in sync with ``core/extractor.py::draw_corner_points``
// (the "5-Color Extended" branch).
// 5-Color Extended 会跨两张校准板。第 2 页刻意使用与第 1 页不同的角点排布，
// 以同时采到外层黑料和重复的蓝色锚点：
//   - 第 1 页角点：白 / 红 / 蓝 / 黄（=标准 RYBW 四角）。
//   - 第 2 页角点：蓝 / 红 / 黑 / 黄。
// 该表必须与后端 ``core/extractor.py::draw_corner_points`` 的
// "5-Color Extended" 分支保持一致。
export const CORNER_COLOR_KEYS_5C_EXT_PAGE2: Array<string | null> = [
  "ext_color_blue",
  "ext_color_red",
  "ext_color_black",
  "ext_color_yellow",
];

// ========== Page-aware label builder (exported for testing) ==========

/**
 * Build localized corner labels for the given color mode + page combination.
 *
 * Only 5-Color Extended is page-aware; every other mode ignores ``page`` and
 * returns its entry from ``CORNER_COLOR_KEYS``. Unknown modes fall back to the
 * RYBW 4-corner list.
 *
 * 根据颜色模式 + 页码构建本地化的角点标签。只有 5-Color Extended 会依赖
 * ``page``，其他模式忽略该参数并返回 ``CORNER_COLOR_KEYS`` 中的对应条目。
 * 未知模式回退到 RYBW 四角。
 */
export function buildCornerLabels(
  colorMode: string,
  page: string,
  t: (key: string) => string,
): string[] {
  let colorKeys: Array<string | null>;
  if (
    colorMode === ExtractorColorMode.FIVE_COLOR_EXT &&
    page === ExtractorPage.PAGE_2
  ) {
    colorKeys = CORNER_COLOR_KEYS_5C_EXT_PAGE2;
  } else {
    colorKeys = CORNER_COLOR_KEYS[colorMode] ?? CORNER_COLOR_KEYS["4-Color (RYBW)"];
  }
  return CORNER_POSITION_KEYS.map((posKey, idx) => {
    const pos = t(posKey);
    const colorKey = colorKeys[idx];
    if (!colorKey) return pos;
    return `${t(colorKey)}（${pos}）`;
  });
}

// ========== Coordinate Conversion (exported for testing) ==========

export function canvasClickToImageCoord(
  event: React.MouseEvent<HTMLCanvasElement>,
  canvas: HTMLCanvasElement,
  imageWidth: number,
  imageHeight: number
): [number, number] {
  const rect = canvas.getBoundingClientRect();
  const scaleX = imageWidth / rect.width;
  const scaleY = imageHeight / rect.height;
  const x = Math.round((event.clientX - rect.left) * scaleX);
  const y = Math.round((event.clientY - rect.top) * scaleY);
  return [x, y];
}

function nearestCornerIndex(points: Array<[number, number]>, target: [number, number]): number {
  let bestIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  points.forEach(([x, y], index) => {
    const dx = x - target[0];
    const dy = y - target[1];
    const distance = dx * dx + dy * dy;
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

// ========== Corner marker drawing constants ==========

const MARKER_RADIUS = 8;
const MARKER_FONT = "bold 12px sans-serif";
const MARKER_FILL = UI_COLOR_TOKENS.extractorMarkerFill;
const MARKER_STROKE = UI_COLOR_TOKENS.extractorMarkerStroke;
const MARKER_TEXT_COLOR = UI_COLOR_TOKENS.extractorMarkerText;

// ========== Helper: draw image + corner markers on canvas ==========

function drawMarkers(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  corners: Array<[number, number]>,
  fill: string,
  stroke: string,
  labelPrefix: string,
): void {
  const { width, height } = ctx.canvas;
  corners.forEach(([ix, iy], idx) => {
    const cx = (ix / img.naturalWidth) * width;
    const cy = (iy / img.naturalHeight) * height;
    ctx.beginPath();
    ctx.arc(cx, cy, MARKER_RADIUS, 0, Math.PI * 2);
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = MARKER_TEXT_COLOR;
    ctx.font = MARKER_FONT;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(`${labelPrefix}${idx + 1}`, cx, cy);
  });
}

function drawCanvas(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  corners: Array<[number, number]>,
): void {
  const { width, height } = ctx.canvas;
  ctx.clearRect(0, 0, width, height);
  ctx.drawImage(img, 0, 0, width, height);

  // Draw extraction corners in blue
  if (corners.length > 0) {
    drawMarkers(ctx, img, corners, MARKER_FILL, MARKER_STROKE, "");
  }
}

const EXTRACTOR_RESULT_MEDIA_MAX_HEIGHT = "clamp(16rem, 48vh, 56rem)";
const EXTRACTOR_CANVAS_MAX_HEIGHT = "min(78vh, calc(100dvh - 12rem))";

function getResolvedCellOverlayStyle(
  resolved: LutPreviewResolvedCell,
  rendered: RenderedImageRect,
) {
  const bbox = resolved.overlay_bbox;
  return {
    left: rendered.offsetX + bbox.left * rendered.width,
    top: rendered.offsetY + bbox.top * rendered.height,
    width: bbox.width * rendered.width,
    height: bbox.height * rendered.height,
  };
}

const LUT_PREVIEW_OUTSIDE_AREA_ERROR = "Clicked cell is outside the valid LUT area";

function getResolveCellErrorMessage(error: unknown, fallback: string): string | null {
  const message = error instanceof Error ? error.message.trim() : "";
  if (message === LUT_PREVIEW_OUTSIDE_AREA_ERROR) return null;
  return apiErrorToVisibleMessage(error, fallback);
}

// ========== Component ==========

export default function ExtractorCanvas() {
  const { t } = useI18n();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  const imagePreviewUrl = useExtractorStore((s) => s.imagePreviewUrl);
  const imageNaturalWidth = useExtractorStore((s) => s.imageNaturalWidth);
  const imageNaturalHeight = useExtractorStore((s) => s.imageNaturalHeight);
  const corner_points = useExtractorStore((s) => s.corner_points);
  const color_mode = useExtractorStore((s) => s.color_mode);
  const page = useExtractorStore((s) => s.page);
  const warp_view_url = useExtractorStore((s) => s.warp_view_url);
  const lut_preview_url = useExtractorStore((s) => s.lut_preview_url);
  const session_id = useExtractorStore((s) => s.session_id);
  const addCornerPoint = useExtractorStore((s) => s.addCornerPoint);
  const moveCornerPoint = useExtractorStore((s) => s.moveCornerPoint);
  const activeCornerIndex = useExtractorStore((s) => s.active_corner_index);

  const submitManualFix = useExtractorStore((s) => s.submitManualFix);
  const setManualFixError = useExtractorStore((s) => s.setManualFixError);
  const manualFixLoading = useExtractorStore((s) => s.manualFixLoading);
  const rotateImage = useExtractorStore((s) => s.rotateImage);

  // ---------- Manual fix state: selected cell + color picker ----------
  // ``initialFixColor`` is only used as the seed for ``ManualFixPopover``'s
  // internal state, so dragging the color picker only re-renders the popover
  // instead of the entire canvas + LUT preview tree.
  // ``initialFixColor`` 仅作为 ManualFixPopover 内部状态的初值，避免拖动
  // 取色器时连带整张画布 + LUT 预览一起重绘。
  const [selectedCell, setSelectedCell] = useState<LutPreviewResolvedCell | null>(null);
  const [initialFixColor, setInitialFixColor] = useState<string>(
    UI_COLOR_TOKENS.extractorFixColorDefault,
  );
  const [renderedRect, setRenderedRect] = useState<RenderedImageRect | null>(null);
  const lutPreviewRef = useRef<HTMLImageElement>(null);

  // ---------- Load image into off-screen Image object ----------
  useEffect(() => {
    if (!imagePreviewUrl) {
      imageRef.current = null;
      return;
    }
    const img = new Image();
    img.onload = () => {
      imageRef.current = img;
      // Trigger initial draw
      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext("2d");
        if (ctx) drawCanvas(ctx, img, corner_points);
      }
    };
    img.src = imagePreviewUrl;
  }, [imagePreviewUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------- Redraw when natural dimensions arrive or corners change ----------
  useEffect(() => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img || !imageNaturalWidth || !imageNaturalHeight) return;
    const ctx = canvas.getContext("2d");
    if (ctx) drawCanvas(ctx, img, corner_points);
  }, [corner_points, imageNaturalWidth, imageNaturalHeight]);

  // ---------- Canvas click handler ----------
  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas || !imageNaturalWidth || !imageNaturalHeight) return;

      const [x, y] = canvasClickToImageCoord(
        e,
        canvas,
        imageNaturalWidth,
        imageNaturalHeight
      );
      if (corner_points.length >= 4) {
        const targetIndex =
          activeCornerIndex !== null && activeCornerIndex >= 0 && activeCornerIndex < corner_points.length
            ? activeCornerIndex
            : nearestCornerIndex(corner_points, [x, y]);
        moveCornerPoint(targetIndex, [x, y]);
        return;
      }
      addCornerPoint([x, y]);
    },
    [
      imageNaturalWidth,
      imageNaturalHeight,
      corner_points,
      activeCornerIndex,
      addCornerPoint,
      moveCornerPoint,
    ]
  );

  // ---------- Derive hint text ----------
  const cornerCount = corner_points.length;
  const labels = buildCornerLabels(color_mode, page, t);
  const hintText =
    cornerCount >= 4
      ? t("ext_canvas_positioning_done")
      : t("ext_canvas_click_corner").replace("{n}", String(cornerCount + 1)).replace("{label}", labels[cornerCount]);

  // ---------- LUT preview click handler (for manual fix) ----------
  const handleLutPreviewClick = useCallback(
    (e: React.MouseEvent<HTMLImageElement>) => {
      const img = lutPreviewRef.current;
      if (!img) return;
      const rect = img.getBoundingClientRect();

      const rendered = getObjectFitRect(
        img.naturalWidth, img.naturalHeight,
        rect.width, rect.height
      );
      if (!session_id || rendered.width <= 0 || rendered.height <= 0) return;
      const relX = e.clientX - rect.left - rendered.offsetX;
      const relY = e.clientY - rect.top - rendered.offsetY;
      if (relX < 0 || relY < 0 || relX >= rendered.width || relY >= rendered.height) return;
      const x = relX / rendered.width;
      const y = relY / rendered.height;
      setManualFixError(null);
      void resolveLutPreviewCell(session_id, x, y)
        .then((cell) => {
          setSelectedCell(cell);
          setRenderedRect(rendered);
          setInitialFixColor(cell.hex || UI_COLOR_TOKENS.extractorFixColorDefault);
        })
        .catch((err) => {
          setSelectedCell(null);
          const message = getResolveCellErrorMessage(
            err,
            t("ext_manual_fix_resolve_failed"),
          );
          if (message) {
            setManualFixError(message);
          }
        });
      // 留白区域点击被忽略
    },
    [session_id, setManualFixError, t]
  );

  const handleFixSubmit = useCallback(
    (hex: string) => {
      if (!selectedCell) return;
      void submitManualFix(selectedCell.cell.row_index, hex);
      setSelectedCell(null);
    },
    [selectedCell, submitManualFix],
  );

  const handleFixCancel = useCallback(() => {
    setSelectedCell(null);
  }, []);

  // ===== Result mode =====
  if (warp_view_url || lut_preview_url) {
    return (
      <div
        data-testid="extractor-results"
      >
        {/* 色卡 + LUT 预览：左右并排，等宽 */}
        <div className="flex h-full min-h-0 w-full flex-col gap-6 2xl:flex-row">
          {warp_view_url && (
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <span className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                {t("ext_canvas_warp_view")}
              </span>
              <img
                data-testid="warp-view-image"
                src={warp_view_url}
                alt={t("ext_canvas_warp_view")}
                className="h-auto w-full object-contain"
                style={{ maxHeight: EXTRACTOR_RESULT_MEDIA_MAX_HEIGHT }}
              />
            </div>
          )}
          {lut_preview_url && (
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <span className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                {t("ext_canvas_lut_preview")}
              </span>
              <div className="relative w-full">
                <img
                  ref={lutPreviewRef}
                  data-testid="lut-preview-image"
                  src={lut_preview_url}
                  alt={t("ext_canvas_lut_preview")}
                  onClick={handleLutPreviewClick}
                  className="h-auto w-full cursor-crosshair object-contain"
                  style={{ maxHeight: EXTRACTOR_RESULT_MEDIA_MAX_HEIGHT }}
                />
                {selectedCell && renderedRect && (() => {
                  const overlay = getResolvedCellOverlayStyle(selectedCell, renderedRect);
                  return (
                    <div
                      data-testid="cell-highlight-overlay"
                      style={{
                        position: "absolute",
                        left: overlay.left,
                        top: overlay.top,
                        width: overlay.width,
                        height: overlay.height,
                        border: UI_COLOR_TOKENS.extractorCellOverlayBorder,
                        pointerEvents: "none",
                        boxShadow: UI_COLOR_TOKENS.extractorCellOverlayShadow,
                        boxSizing: "border-box",
                      }}
                    />
                  );
                })()}
              </div>
            </div>
          )}
        </div>
        {/* 手动修正浮层：选中色块后悬浮显示 */}
        {selectedCell && (
          <ManualFixPopover
            key={`${selectedCell.cell.row_index}`}
            cell={selectedCell}
            initialColor={initialFixColor}
            loading={manualFixLoading}
            onSubmit={handleFixSubmit}
            onCancel={handleFixCancel}
          />
        )}
      </div>
    );
  }

  // ===== Empty state =====
  if (!imagePreviewUrl) {
    return (
      <div
        data-testid="extractor-empty-state"
        className="flex h-full flex-1 flex-col items-center justify-center gap-3 text-slate-400 dark:text-slate-500"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-16 w-16 opacity-40"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
          />
        </svg>
        <p className="text-sm">{t("ext_canvas_upload_hint")}</p>
      </div>
    );
  }

  // ===== Canvas mode =====
  return (
    <div className="flex h-full min-h-0 flex-1 flex-col items-center justify-center gap-4 px-3 py-3 sm:px-5 sm:py-4 xl:px-7 xl:py-5">
      {/* Corner hint + rotate button */}
      <div className="flex items-center gap-2">
        <p
          data-testid="corner-hint"
          className={`rounded-full px-3 py-1 text-sm font-medium ${
            cornerCount >= 4 ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-amber-500/10 text-amber-600 dark:text-amber-300"
          }`}
        >
          {hintText}
        </p>
        <button
          data-testid="rotate-image-btn"
          onClick={rotateImage}
          className="action-control rounded-full border px-3 py-1 text-sm transition-colors"
        >
          {t("ext_rotate_btn")}
        </button>
      </div>

      {/* Canvas */}
      <canvas
        ref={canvasRef}
        data-testid="extractor-canvas"
        width={imageNaturalWidth ?? 800}
        height={imageNaturalHeight ?? 600}
        onClick={handleCanvasClick}
        className="max-w-full cursor-crosshair object-contain"
        style={{ objectFit: "contain", maxHeight: EXTRACTOR_CANVAS_MAX_HEIGHT }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Manual fix popover
// ---------------------------------------------------------------------------

interface ManualFixPopoverProps {
  cell: LutPreviewResolvedCell;
  initialColor: string;
  loading: boolean;
  onSubmit: (hex: string) => void;
  onCancel: () => void;
}

/**
 * Floating popover over the LUT preview for tweaking one LUT cell's color.
 * 悬浮在 LUT 预览上的单元手动修正弹层。
 *
 * Owns its own ``fixColor`` state so that continuous ``<input type="color">``
 * drag events only re-render this small popover and not the full extractor
 * canvas / LUT preview tree. The parent passes ``initialColor`` as the seed
 * and re-mounts the component via a ``key`` tied to ``cell`` whenever the
 * user picks a different cell.
 * 组件内部自持 fixColor 状态，避免拖动取色器时连带整张提取器画布和 LUT
 * 预览一起重绘。父组件通过 key 绑定 cell 触发子组件重建，从而用新的
 * initialColor 重新播种。
 */
function ManualFixPopover({
  cell,
  initialColor,
  loading,
  onSubmit,
  onCancel,
}: ManualFixPopoverProps) {
  const { t } = useI18n();
  const [fixColor, setFixColor] = useState<string>(initialColor);

  const handleSubmit = useCallback(() => {
    onSubmit(fixColor);
  }, [fixColor, onSubmit]);

  const [r, g, b] = hexToRgb(fixColor);

  return (
    <div
      data-testid="manual-fix-popup"
    >
      <span className="text-sm text-slate-700 dark:text-slate-300">
        {t("ext_canvas_row")} {cell.cell.display_row} / {t("ext_canvas_col")} {cell.cell.display_col}
      </span>
      <input
        data-testid="fix-color-picker"
        type="color"
        value={fixColor}
        onChange={(e) => setFixColor(e.target.value)}
        className="h-8 w-10 cursor-pointer rounded-xl border border-slate-300 bg-transparent dark:border-slate-500"
      />
      <span className="font-mono text-xs text-slate-500 dark:text-slate-400">
        {`RGB(${r}, ${g}, ${b})`}
      </span>
      <button
        data-testid="fix-submit-button"
        onClick={handleSubmit}
        disabled={loading}
        className="action-control action-control-primary rounded-lg px-3 py-1.5 text-sm"
      >
        {loading ? t("ext_canvas_fixing") : t("ext_canvas_confirm_fix")}
      </button>
      <button
        onClick={onCancel}
      >
        {t("ext_canvas_cancel")}
      </button>
    </div>
  );
}
