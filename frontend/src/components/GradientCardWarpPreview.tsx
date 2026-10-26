import type { GradientCardSampleBox } from "../api/types";
import GradientCardCanvasPreview from "./GradientCardCanvasPreview";

interface GradientCardWarpPreviewProps {
  title: string;
  imageUrl: string;
  alt: string;
  sampleBoxes: GradientCardSampleBox[];
  warpWidth: number | null;
  warpHeight: number | null;
  testIdPrefix: string;
}

export default function GradientCardWarpPreview({
  title,
  imageUrl,
  alt,
  sampleBoxes,
  warpWidth,
  warpHeight,
  testIdPrefix,
}: GradientCardWarpPreviewProps) {
  return (
    <GradientCardCanvasPreview
      title={title}
      imageUrl={imageUrl}
      alt={alt}
      sampleBoxes={sampleBoxes}
      warpWidth={warpWidth}
      warpHeight={warpHeight}
      dataTestId={testIdPrefix}
    />
  );
}
