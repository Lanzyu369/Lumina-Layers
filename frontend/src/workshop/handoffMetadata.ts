import type { WorkshopRecipeSource } from "./contracts";

const handoffColorLibraryIds =
  new WeakMap<WorkshopRecipeSource, string | null>();

export function rememberWorkshopHandoffColorLibraryId(
  source: WorkshopRecipeSource,
  colorLibraryId: string | null,
): void {
  handoffColorLibraryIds.set(source, colorLibraryId);
}

export function readWorkshopHandoffColorLibraryId(
  source: WorkshopRecipeSource,
): string | null | undefined {
  return handoffColorLibraryIds.get(source);
}
