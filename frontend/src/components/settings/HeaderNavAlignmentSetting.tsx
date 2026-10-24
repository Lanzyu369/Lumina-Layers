import { useI18n } from "../../i18n/context";
import {
  HEADER_NAV_ALIGNMENTS,
  isHeaderNavAlignment,
  useSettingsStore,
  type HeaderNavAlignment,
} from "../../stores/settingsStore";
import RadioGroup from "../ui/RadioGroup";

const ALIGNMENT_LABEL_KEYS: Record<HeaderNavAlignment, string> = {
  center: "settings.header_nav_alignment_center",
  left: "settings.header_nav_alignment_left",
};

/**
 * Lets users center the top navigation or align it to the left.
 * 让用户选择顶部导航居中或居左显示。
 */
export default function HeaderNavAlignmentSetting() {
  const { t } = useI18n();
  const alignment = useSettingsStore((s) => s.headerNavAlignment);
  const setAlignment = useSettingsStore((s) => s.setHeaderNavAlignment);

  return (
    <div
      data-testid="settings-header-nav-alignment-section"
      className="flex flex-col gap-4 border-t panel-divider pt-5"
    >
      <div className="min-w-0">
        <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200">
          {t("settings.header_nav_alignment_heading")}
        </h3>
      </div>
      <RadioGroup
        label={t("settings.header_nav_alignment_label")}
        tooltip={t("settings.header_nav_alignment_description")}
        value={alignment}
        options={HEADER_NAV_ALIGNMENTS.map((value) => ({
          value,
          label: t(ALIGNMENT_LABEL_KEYS[value]),
        }))}
        onChange={(value) => {
          if (isHeaderNavAlignment(value)) {
            setAlignment(value);
          }
        }}
      />
    </div>
  );
}
