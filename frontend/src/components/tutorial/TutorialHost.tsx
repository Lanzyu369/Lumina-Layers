import { useEffect } from "react";
import { useTutorialStore } from "../../stores/tutorialStore";
import TutorialTour from "./TutorialTour";
import TutorialWelcomeDialog from "./TutorialWelcomeDialog";

interface TutorialHostProps {
  /**
   * True once nothing else (such as the release announcement) is on screen,
   * so the first-run welcome never stacks on another dialog.
   * 其他弹窗（如更新公告）都已关闭时为 true，避免欢迎窗与其他弹窗叠在一起。
   */
  canAutoOffer: boolean;
}

/**
 * Mounts the beginner tutorial and offers it once on first launch.
 * 挂载新手引导，并在首次启动时自动弹出一次。
 */
export function TutorialHost({ canAutoOffer }: TutorialHostProps) {
  const phase = useTutorialStore((s) => s.phase);
  const offerFirstRun = useTutorialStore((s) => s.offerFirstRun);
  const startTour = useTutorialStore((s) => s.startTour);
  const skip = useTutorialStore((s) => s.skip);

  useEffect(() => {
    if (canAutoOffer) {
      offerFirstRun();
    }
  }, [canAutoOffer, offerFirstRun]);

  if (phase === "touring") {
    return <TutorialTour />;
  }

  return (
    <TutorialWelcomeDialog
      open={phase === "welcome"}
      onStart={() => startTour("auto")}
      onSkip={() => skip("welcome")}
    />
  );
}
