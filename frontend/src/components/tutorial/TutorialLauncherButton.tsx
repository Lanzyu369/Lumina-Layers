import { useI18n } from "../../i18n/context";
import { useTutorialStore } from "../../stores/tutorialStore";
import { HEADER_ICON_BUTTON_CLASS } from "../ui/headerControls";
import { HeaderTooltip } from "../ui/HeaderTooltip";

/**
 * Header button that replays the beginner tutorial at any time.
 * 顶栏按钮，可随时重新打开新手引导。
 */
export function TutorialLauncherButton() {
  const { t } = useI18n();
  const startTour = useTutorialStore((s) => s.startTour);

  return (
    <HeaderTooltip label={t("tutorial_launcher_tooltip")}>
      <button
        type="button"
        data-testid="tutorial-launcher-button"
        data-tutorial="tutorial-launcher"
        aria-label={t("tutorial_launcher_label")}
        onClick={() => startTour("manual")}
        className={HEADER_ICON_BUTTON_CLASS}
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M12 6.5c-1.8-1.3-4.3-2-7-2v13c2.7 0 5.2.7 7 2 1.8-1.3 4.3-2 7-2v-13c-2.7 0-5.2.7-7 2Z" />
          <path d="M12 6.5v13" />
        </svg>
      </button>
    </HeaderTooltip>
  );
}
