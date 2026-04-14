/**
 * Color2DOverlay — color editing overlay above the 3D scene.
 * Color2DOverlay — 覆盖在 3D 场景上方的颜色编辑面板。
 *
 * Shows PalettePanel (top) + LUT Color Grid (bottom) for color
 * replacement. The user selects colors by clicking on the 3D model
 * in the scene underneath, then uses this panel to pick target colors.
 * 显示调色板（上）+ LUT 颜色网格（下）用于颜色替换。
 * 用户在下方 3D 场景中点击模型选色，然后在此面板中选择目标色。
 */

import { useEffect, useCallback, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { useWidgetStore } from '../../stores/widgetStore';
import { useConverterStore } from '../../stores/converter';
import { useI18n } from '../../i18n/context';
import ColorPreview2D from '../sections/ColorPreview2D';
import PalettePanel from '../sections/PalettePanel';
import LutColorGrid from '../sections/LutColorGrid';

export default function Color2DOverlay() {
  const closeOverlay = useWidgetStore((s) => s.closeColor2DOverlay);
  const { t } = useI18n();

  const imageFile = useConverterStore((s) => s.imageFile);
  const previewImageUrl = useConverterStore((s) => s.previewImageUrl);
  const isLoading = useConverterStore((s) => s.isLoading);
  const submitPreview = useConverterStore((s) => s.submitPreview);
  const [showHoverMagnifier, setShowHoverMagnifier] = useState(true);
  const [showHoverLayerDetails, setShowHoverLayerDetails] = useState(true);

  // Auto-trigger preview when overlay opens with an image but no preview
  const didAutoPreview = useRef(false);
  useEffect(() => {
    if (imageFile && !previewImageUrl && !isLoading && !didAutoPreview.current) {
      didAutoPreview.current = true;
      void submitPreview();
    }
  }, [imageFile, previewImageUrl, isLoading, submitPreview]);

  // ESC key to close (return to 3D view)
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeOverlay();
      }
    },
    [closeOverlay],
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  return (
    <motion.div
      initial={{ opacity: 0, y: -50 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 50 }}
      transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
      data-testid="color-2d-overlay"
      className="absolute inset-0 z-[45] flex flex-col bg-slate-50/95 dark:bg-slate-950/95 backdrop-blur-sm"
    >
      {/* Header: title + close */}
      <div className="flex shrink-0 items-center justify-between border-b border-slate-200/80 px-4 py-1.5 dark:border-slate-800/80">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {t('color_2d_overlay_title')}
        </h2>
        <button
          type="button"
          onClick={closeOverlay}
          className="rounded-full border border-slate-200/80 bg-slate-100/85 px-3 py-1 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200 dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:bg-slate-800"
          aria-label={t('color_2d_overlay_close')}
        >
          {t('color_2d_overlay_close')} <span className="ml-1 text-[10px] text-slate-400">{t('color_2d_overlay_close_shortcut')}</span>
        </button>
      </div>

      {/* Content: left = 2D preview, right = palette + LUT grid in two columns */}
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(18rem,0.82fr)_minmax(17rem,0.46fr)_minmax(20rem,0.72fr)] gap-0">
        {/* Left: 2D preview image (click to select color/region) */}
        <div className="min-h-0 border-r border-slate-200/60 px-2 py-3 dark:border-slate-800/60">
          <ColorPreview2D
            showMagnifier={showHoverMagnifier}
            showLayerDetails={showHoverLayerDetails}
          />
        </div>

        {/* Middle: palette panel */}
        <div className="min-h-0 border-r border-slate-200/60 px-3 py-2 dark:border-slate-800/60">
          <div className="h-full overflow-y-auto">
            <PalettePanel
              showHoverMagnifier={showHoverMagnifier}
              showHoverLayerDetails={showHoverLayerDetails}
              onToggleHoverMagnifier={setShowHoverMagnifier}
              onToggleHoverLayerDetails={setShowHoverLayerDetails}
            />
          </div>
        </div>

        {/* Right: LUT color grid */}
        <div className="min-h-0 px-3 py-2">
          <div className="h-full overflow-y-auto">
            <LutColorGrid />
          </div>
        </div>
      </div>
    </motion.div>
  );
}
