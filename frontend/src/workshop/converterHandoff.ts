import { useConverterStore } from "../stores/converter";
import { useWidgetStore } from "../stores/widgetStore";
import type {
  WorkshopHandoffOptions,
  WorkshopHandoffResult,
  WorkshopImageHandoff,
} from "./types";

export async function handoffWorkshopImageToConverter(
  handoff: WorkshopImageHandoff,
  options?: WorkshopHandoffOptions,
): Promise<WorkshopHandoffResult> {
  const converter = useConverterStore.getState();
  const occupied =
    converter.imageFile !== null || converter.batchFiles.length > 0;
  if (occupied && !options?.replaceExisting) {
    return { status: "needs-confirmation" };
  }

  converter.loadWorkshopImageIntoConverter({
    file: handoff.file,
    pixelWidth: handoff.pixelWidth,
    pixelHeight: handoff.pixelHeight,
    targetWidthMm: handoff.recommendedWidthMm,
    targetHeightMm: handoff.recommendedHeightMm,
    source: handoff.recipeSource,
  });
  useWidgetStore.getState().setActiveTab("converter");
  return { status: "completed" };
}
