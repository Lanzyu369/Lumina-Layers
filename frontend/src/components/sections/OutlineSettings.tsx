import { useConverterStore } from "../../stores/converter";
import { useI18n } from "../../i18n/context";
import Checkbox from "../ui/Checkbox";
import Slider from "../ui/Slider";
import { WIKI_DOCS } from "../../utils/wikiDocs";

/**
 * Compute whether the "Enable Outline" checkbox should be disabled and, if
 * so, which i18n key explains why. Drives the decision matrix from
 * `progress/svg-vector-outline-acceptance-checkpoint.md`:
 *
 *   - D1–D4 / D7 / D8 (default supported rows): return `null` → enabled.
 *   - D5 (subscription / 8-Color Max edge combo): return
 *     `outline_enable_unsupported_subscription_combo`.
 *   - D6 (alpha channel unavailable): return
 *     `outline_enable_unsupported_alpha_unavailable`.
 *
 * Detecting D5 / D6 requires signals that are not currently exposed to the
 * UI (subscription state, alpha-channel detection on the uploaded asset).
 * Until those signals exist, every supported vector / non-vector flow
 * resolves to the supported branch and the checkbox is enabled. The
 * disable mechanism stays wired so a future change can flip the reason on
 * without re-touching the JSX.
 *
 * 决策矩阵驱动的 disabled 原因计算：
 *   - D1–D4/D7/D8 默认支持，返回 null（不禁用）。
 *   - D5/D6 命中时返回对应 i18n key（当前没有判定信号，恒为 null）。
 */
function computeOutlineDisabledReason(): string | null {
  // No D5 / D6 detection signals available today; default to enabled for
  // all currently supported decision-matrix rows.
  // 目前没有 D5/D6 判定信号，所有支持的决策矩阵行都返回 null。
  return null;
}

export default function OutlineSettings() {
  const { t } = useI18n();
  const enable_outline = useConverterStore((s) => s.enable_outline);
  const outline_width = useConverterStore((s) => s.outline_width);
  const setEnableOutline = useConverterStore((s) => s.setEnableOutline);
  const setOutlineWidth = useConverterStore((s) => s.setOutlineWidth);

  const outlineDisabledReason = computeOutlineDisabledReason();
  const isOutlineDisabled = outlineDisabledReason !== null;

  return (
    <div className="flex flex-col gap-4">
      <Checkbox
        label={t("outline_enable")}
        checked={enable_outline}
        onChange={setEnableOutline}
        disabled={isOutlineDisabled}
        tooltip={
          outlineDisabledReason
            ? t(outlineDisabledReason)
            : t("outline_enable_hint")
        }
        wikiPath={WIKI_DOCS.outline}
      />
      {enable_outline && (
        <Slider
          label={t("outline_width")}
          tooltip={t("outline_width_hint")}
          wikiPath={WIKI_DOCS.outline}
          value={outline_width}
          min={0.5}
          max={10.0}
          step={0.5}
          unit="mm"
          onChange={setOutlineWidth}
        />
      )}
    </div>
  );
}
