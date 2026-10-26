import { useCallback } from "react";
import { useShallow } from "zustand/react/shallow";
import {
  getMaterialArchiveReliefMinimumExtraHeight,
  useConverterStore,
} from "../../stores/converter";
import {
  ColorMode,
  ModelingMode,
  StructureMode,
  type AutoHeightMode,
} from "../../api/types";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";
import Dropdown from "../ui/Dropdown";
import ImageUpload from "../ui/ImageUpload";
import { ACCEPT_HEIGHTMAP_FORMATS } from "../../constants/heightmap";
import { useI18n } from "../../i18n/context";
import { workstationFieldLabelClass } from "../ui/panelPrimitives";
import { WIKI_DOCS } from "../../utils/wikiDocs";

export default function ReliefSettings() {
  const { t } = useI18n();

  const AUTO_HEIGHT_OPTIONS: { label: string; value: AutoHeightMode }[] = [
    { label: t("relief_darker_higher"), value: "darker-higher" },
    { label: t("relief_lighter_higher"), value: "lighter-higher" },
    { label: t("relief_use_heightmap"), value: "use-heightmap" },
  ];

  const {
    enable_relief,
    heightmap_max_height,
    autoHeightMode,
    heightmapFile,
    heightmapThumbnailUrl,
    source_version,
    materialLayerCount,
    materialDynamicLayerCountEnabled,
    materialMaxLayerCount,
    spacer_thick,
    color_mode,
    modeling_mode,
    structure_mode,
  } = useConverterStore(useShallow((s) => ({
    enable_relief: s.enable_relief,
    heightmap_max_height: s.heightmap_max_height,
    autoHeightMode: s.autoHeightMode,
    heightmapFile: s.heightmapFile,
    heightmapThumbnailUrl: s.heightmapThumbnailUrl,
    source_version: s.source_version,
    materialLayerCount: s.materialLayerCount,
    materialDynamicLayerCountEnabled: s.materialDynamicLayerCountEnabled,
    materialMaxLayerCount: s.materialMaxLayerCount,
    spacer_thick: s.spacer_thick,
    color_mode: s.color_mode,
    modeling_mode: s.modeling_mode,
    structure_mode: s.structure_mode,
  })));

  const isUnsupportedVectorRelief =
    modeling_mode === ModelingMode.VECTOR &&
    (color_mode === ColorMode.FIVE_COLOR_EXT ||
      structure_mode !== StructureMode.SINGLE_SIDED);

  const minimumReliefHeight = getMaterialArchiveReliefMinimumExtraHeight({
    source_version,
    materialLayerCount,
    materialDynamicLayerCountEnabled,
    materialMaxLayerCount,
    spacer_thick,
  });

  // Actions extracted individually (stable references)
  const setEnableRelief = useConverterStore((s) => s.setEnableRelief);
  const setHeightmapMaxHeight = useConverterStore((s) => s.setHeightmapMaxHeight);
  const setAutoHeightMode = useConverterStore((s) => s.setAutoHeightMode);
  const applyAutoHeight = useConverterStore((s) => s.applyAutoHeight);
  const setHeightmapFile = useConverterStore((s) => s.setHeightmapFile);
  const uploadHeightmap = useConverterStore((s) => s.uploadHeightmap);

  const handleModeChange = useCallback(
    (value: string) => {
      const mode = value as AutoHeightMode;
      setAutoHeightMode(mode);
      if (mode !== "use-heightmap") {
        applyAutoHeight(mode);
      }
    },
    [setAutoHeightMode, applyAutoHeight],
  );

  const handleHeightmapSelect = useCallback(
    (file: File) => {
      setHeightmapFile(file);
      // 设置文件后自动触发上传
      // 需要在下一个 tick 执行，因为 setHeightmapFile 是异步更新 state
      setTimeout(() => {
        uploadHeightmap();
      }, 0);
    },
    [setHeightmapFile, uploadHeightmap],
  );

  return (
    <div className="flex flex-col gap-4">
        <Checkbox
          label={t("relief_enable")}
          checked={enable_relief}
          onChange={setEnableRelief}
          disabled={isUnsupportedVectorRelief}
          tooltip={
            isUnsupportedVectorRelief
              ? t("relief_vector_unsupported_mode")
              : t("relief_enable_hint")
          }
          wikiPath={WIKI_DOCS.relief}
        />

        {enable_relief && (
          <>
            <Slider
              label={t("relief_max_height")}
              tooltip={t("relief_max_height_hint")}
              wikiPath={WIKI_DOCS.relief}
              value={heightmap_max_height}
              min={minimumReliefHeight}
              max={15.0}
              step={0.04}
              unit="mm"
              onChange={setHeightmapMaxHeight}
            />

            <Dropdown
              label={t("relief_auto_height_mode")}
              tooltip={t("relief_enable_hint")}
              wikiPath={WIKI_DOCS.relief}
              value={autoHeightMode}
              options={AUTO_HEIGHT_OPTIONS}
              onChange={handleModeChange}
            />

            {autoHeightMode === "use-heightmap" && (
              <div className="flex flex-col gap-2">
                <label className={workstationFieldLabelClass}>{t("relief_heightmap_label")}</label>
                <ImageUpload
                  onFileSelect={handleHeightmapSelect}
                  accept={ACCEPT_HEIGHTMAP_FORMATS}
                  preview={heightmapThumbnailUrl ?? undefined}
                />
                {heightmapFile && !heightmapThumbnailUrl && (
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {t("relief_file_selected")}: {heightmapFile.name}
                  </span>
                )}
              </div>
            )}
          </>
        )}
    </div>
  );
}
