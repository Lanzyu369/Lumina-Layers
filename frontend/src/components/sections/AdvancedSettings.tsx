import { useConverterStore } from "../../stores/converter";
import { useI18n } from "../../i18n/context";
import Slider from "../ui/Slider";
import Checkbox from "../ui/Checkbox";

export default function AdvancedSettings() {
  const { t } = useI18n();
  const enable_cleanup = useConverterStore((s) => s.enable_cleanup);
  const separate_backing = useConverterStore((s) => s.separate_backing);
  const hue_enable = useConverterStore((s) => s.hue_enable);
  const chroma_gate = useConverterStore((s) => s.chroma_gate);
  const quantize_colors_unlocked = useConverterStore((s) => s.quantize_colors_unlocked);
  const setEnableCleanup = useConverterStore((s) => s.setEnableCleanup);
  const setSeparateBacking = useConverterStore((s) => s.setSeparateBacking);
  const setHueEnable = useConverterStore((s) => s.setHueEnable);
  const setChromaGate = useConverterStore((s) => s.setChromaGate);
  const setQuantizeColorsUnlocked = useConverterStore((s) => s.setQuantizeColorsUnlocked);

  return (
    <div className="flex flex-col gap-4">
      <Checkbox
        label={t("adv_isolated_pixel_cleanup")}
        tooltip={t("adv_isolated_pixel_cleanup_hint")}
        checked={enable_cleanup}
        onChange={setEnableCleanup}
      />
      <Checkbox
        label={t("adv_separate_backing")}
        tooltip={t("adv_separate_backing_hint")}
        checked={separate_backing}
        onChange={setSeparateBacking}
      />
      <Checkbox
        label={t("adv_hue_protection")}
        tooltip={t("adv_hue_protection_hint")}
        checked={hue_enable}
        onChange={setHueEnable}
      />
      {hue_enable && (
        <Slider label={t("adv_chroma_gate")} tooltip={t("adv_chroma_gate_hint")} value={chroma_gate} min={0} max={50} step={1} onChange={setChromaGate} />
      )}
      <Checkbox
        label={t("adv_unlock_quantize")}
        tooltip={t("adv_unlock_quantize_hint")}
        checked={quantize_colors_unlocked}
        onChange={setQuantizeColorsUnlocked}
      />
    </div>
  );
}
