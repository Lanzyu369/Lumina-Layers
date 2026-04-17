import GradientCardCanvasPreview from "./GradientCardCanvasPreview";

interface GradientCardCornerSelectorProps {
  title: string;
  hint: string;
  imageUrl: string | null;
  naturalWidth: number | null;
  naturalHeight: number | null;
  cornerPoints: Array<[number, number]>;
  emptyText: string;
  dataTestId: string;
  emptyStateTestId?: string;
  onSelectPoint: (point: [number, number]) => void;
  onImageLoad: (width: number, height: number) => void;
}

export default function GradientCardCornerSelector({
  title,
  hint,
  imageUrl,
  naturalWidth,
  naturalHeight,
  cornerPoints,
  emptyText,
  dataTestId,
  emptyStateTestId,
  onSelectPoint,
  onImageLoad,
}: GradientCardCornerSelectorProps) {
  return (
    <GradientCardCanvasPreview
      title={title}
      hint={hint}
      imageUrl={imageUrl}
      alt={title}
      emptyText={emptyText}
      naturalWidth={naturalWidth}
      naturalHeight={naturalHeight}
      cornerPoints={cornerPoints}
      onSelectPoint={onSelectPoint}
      onImageLoad={onImageLoad}
      dataTestId={dataTestId}
      emptyStateTestId={emptyStateTestId}
    />
  );
}
