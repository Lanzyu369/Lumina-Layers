import type { CSSProperties } from "react"
import { useI18n } from "../../i18n/context"
import type { HoverLayerColorSample } from "./previewHoverInspectorUtils"
import { MAGNIFIER_SIZE_PX } from "./previewHoverInspectorUtils"
import { getHoverInspectorLayout } from "./previewHoverInspectorUtils"
import { formatDisplayLayerLabelParts } from "../../utils/layerLabels"

interface PreviewHoverInspectorProps {
  dataTestId: string
  style: CSSProperties
  magnifierCanvasRef: React.RefObject<HTMLCanvasElement | null>
  pixelX: number
  pixelY: number
  surfaceHex: string | null
  hoverLayerColors: HoverLayerColorSample[]
  layerImagesLoading: boolean
  showMagnifier?: boolean
  showLayerDetails?: boolean
}

export default function PreviewHoverInspector({
  dataTestId,
  style,
  magnifierCanvasRef,
  pixelX,
  pixelY,
  surfaceHex,
  hoverLayerColors,
  layerImagesLoading,
  showMagnifier = true,
  showLayerDetails = true,
}: PreviewHoverInspectorProps) {
  const { t, lang } = useI18n()
  const layerLayout = getHoverInspectorLayout(hoverLayerColors.length, showLayerDetails)

  return (
    <div
      className="pointer-events-none fixed z-[60]"
      style={style}
      data-testid={dataTestId}
    >
      <div
        className="w-[248px] rounded-xl border p-2 shadow-xl backdrop-blur-sm"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
          color: "var(--surface-text)",
        }}
      >
        {showMagnifier && (
          <div
            className="relative overflow-hidden rounded-md border"
            style={{ borderColor: "var(--surface-outline)" }}
          >
            <canvas
              ref={magnifierCanvasRef}
              width={MAGNIFIER_SIZE_PX}
              height={MAGNIFIER_SIZE_PX}
              className="h-[152px] w-[152px]"
              aria-label={t("viewer_hover_magnifier")}
            />
            <span
              className="absolute left-2 top-2 rounded border px-1.5 py-0.5 text-[10px]"
              style={{
                borderColor: "var(--surface-outline)",
                background: "var(--surface-section-muted)",
              }}
            >
              {t("viewer_hover_magnifier")}
            </span>
          </div>
        )}

        <div className="mt-2 space-y-1 text-[11px]">
          <div className="flex items-center justify-between">
            <span>{t("viewer_hover_pixel")}</span>
            <span className="font-mono">({pixelX}, {pixelY})</span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span>{t("viewer_hover_surface_color")}</span>
            <span className="inline-flex items-center gap-1.5 font-mono">
              <span
                className="h-3 w-3 rounded border"
                style={{
                  borderColor: "var(--surface-outline)",
                  backgroundColor: surfaceHex ? `#${surfaceHex}` : "transparent",
                }}
              />
              {surfaceHex ? `#${surfaceHex}` : t("viewer_hover_transparent")}
            </span>
          </div>
        </div>

        {showLayerDetails && (
          <div
            className="mt-2 border-t pt-2"
            style={{ borderColor: "var(--surface-outline)" }}
          >
            <div className="mb-1 text-[11px] font-semibold">
              {t("viewer_hover_layers_title")}
            </div>
            {layerImagesLoading && hoverLayerColors.length === 0 ? (
              <p className="text-[11px]">{t("viewer_hover_loading_layers")}</p>
            ) : hoverLayerColors.length > 0 ? (
              <ul
                className={
                  layerLayout.isCompactGrid
                    ? "grid grid-cols-2 gap-x-2 gap-y-1 text-[11px]"
                    : "space-y-1 text-[11px]"
                }
              >
                {hoverLayerColors.map((layer) => {
                  const layerLabel = formatDisplayLayerLabelParts(layer.displayIndex - 1, t, lang)
                  return (
                    <li
                      key={`${layer.displayIndex}-${layer.layerName}`}
                      className={
                        layerLayout.isCompactGrid
                          ? "flex min-w-0 items-start justify-between gap-1"
                          : "flex items-start justify-between gap-2"
                      }
                    >
                      <span className="min-w-0 leading-tight">
                        <span className="block">{layerLabel.label}</span>
                        {layerLabel.viewerSuffix && (
                          <span
                            className="block text-[9px] font-normal leading-tight"
                            style={{ color: "var(--surface-text-muted)" }}
                          >
                            {layerLabel.viewerSuffix}
                          </span>
                        )}
                      </span>
                      <span className="inline-flex items-center gap-1.5 font-mono">
                        <span
                          className="h-2.5 w-2.5 rounded border"
                          style={{
                            borderColor: "var(--surface-outline)",
                            backgroundColor: layer.colorHex ? `#${layer.colorHex}` : "transparent",
                          }}
                        />
                        {layer.colorHex ? `#${layer.colorHex}` : t("viewer_hover_transparent")}
                      </span>
                    </li>
                  )
                })}
              </ul>
            ) : (
              <p className="text-[11px]">{t("viewer_hover_no_layer_data")}</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
