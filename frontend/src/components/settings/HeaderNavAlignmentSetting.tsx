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
      className="flex flex-col gap-4 border-t border-slate-200/60 pt-5 dark:border-slate-700/60"
    >
      <div className="min-w-0">
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
          {t("settings.header_nav_alignment_heading")}
        </h3>
        <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
          {t("settings.header_nav_alignment_description")}
        </p>
      </div>
      <RadioGroup
        label={t("settings.header_nav_alignment_label")}
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
