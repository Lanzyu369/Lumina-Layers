export const WIKI_BASE_URL = "https://wiki.luminastudio.com.cn";

export type WikiDocPath = `/docs/${string}/`;

export function buildWikiDocUrl(
  path: WikiDocPath,
  language: "zh" | "en",
): string {
  return `${WIKI_BASE_URL}/${language}${path}`;
}

export const WIKI_DOCS = {
  generateActions: "/docs/reference/converter-basic/actions/",
  imageInputAndCrop: "/docs/reference/converter-basic/image-input-and-crop/",
  sourceType: "/docs/reference/converter-basic/source-type/",
  materialArchiveSource:
    "/docs/reference/converter-basic/material-archive-source/",
  legacyLutSource: "/docs/reference/converter-basic/legacy-lut-source/",
  inferredLutSource: "/docs/reference/converter-basic/inferred-lut-source/",
  outputDimensions: "/docs/reference/converter-basic/output-dimensions/",
  largeFormat: "/docs/reference/converter-basic/large-format/",
  backingThickness: "/docs/reference/converter-basic/backing-thickness/",
  structureMode: "/docs/reference/converter-basic/structure-mode/",
  modelingMode: "/docs/reference/converter-basic/modeling-mode/",
  quantizeColors: "/docs/reference/converter-basic/quantize-colors/",
  slicerOutput: "/docs/reference/converter-basic/slicer-output/",
  isolatedPixelCleanup:
    "/docs/reference/color-matching/isolated-pixel-cleanup/",
  separateBacking: "/docs/reference/model-features/separate-backing/",
  preciseColorMatching:
    "/docs/reference/color-matching/precise-color-matching/",
  autoDynamicRange: "/docs/reference/color-matching/auto-dynamic-range/",
  highPrecision3dPreview:
    "/docs/reference/preview-and-palette/high-precision-3d-preview/",
  hueProtection: "/docs/reference/color-matching/hue-protection/",
  darkChromaGate: "/docs/reference/color-matching/dark-chroma-gate/",
  unlockQuantizeCeiling:
    "/docs/reference/color-matching/unlock-quantize-ceiling/",
  modelAssistedMatching:
    "/docs/reference/color-matching/model-assisted-matching/",
  outline: "/docs/reference/model-features/outline/",
  relief: "/docs/reference/model-features/relief/",
  cloisonne: "/docs/reference/model-features/cloisonne/",
  fridgeMagnet: "/docs/reference/model-features/fridge-magnet/",
  keychainLoop: "/docs/reference/model-features/keychain-loop/",
  puzzle: "/docs/reference/model-features/puzzle/",
  transparentCoating: "/docs/reference/model-features/transparent-coating/",
  vectorizerOverview:
    "/docs/reference/vector-and-extraction/vectorizer-overview/",
  vectorizerColorAndDetail:
    "/docs/reference/vector-and-extraction/vectorizer-color-and-detail/",
  vectorizerOutputEnhancement:
    "/docs/reference/vector-and-extraction/vectorizer-output-enhancement/",
  vectorizerPreprocessing:
    "/docs/reference/vector-and-extraction/vectorizer-preprocessing/",
  vectorizerSegmentation:
    "/docs/reference/vector-and-extraction/vectorizer-segmentation/",
  vectorizerCurveAndFiltering:
    "/docs/reference/vector-and-extraction/vectorizer-curve-and-filtering/",
  calibrationBoard: "/docs/reference/lut-management/calibration-board/",
  lutExtractor: "/docs/reference/lut-management/lut-extractor/",
  extractorPhotoCorrection:
    "/docs/reference/lut-management/extractor-photo-correction/",
  colorcheckerCalibration:
    "/docs/reference/lut-management/colorchecker-calibration/",
  gradientCardExtraction:
    "/docs/reference/materials-and-recipes/gradient-card-extraction/",
  gradientCardGeneration:
    "/docs/reference/materials-and-recipes/gradient-card-generation/",
  baseLayerModifier:
    "/docs/reference/settings-import-export/base-layer-modifier/",
  solverCacheDensity:
    "/docs/reference/settings-import-export/solver-cache-density/",
  svgRasterDensity:
    "/docs/reference/settings-import-export/svg-raster-density/",
  autoGradientReplacement:
    "/docs/reference/settings-import-export/auto-gradient-replacement/",
  cacheMaintenance:
    "/docs/reference/settings-import-export/cache-maintenance/",
  deviceAndSlicer:
    "/docs/reference/settings-import-export/device-and-slicer/",
  wittyLoading: "/docs/reference/settings-import-export/witty-loading/",
} as const satisfies Record<string, WikiDocPath>;
