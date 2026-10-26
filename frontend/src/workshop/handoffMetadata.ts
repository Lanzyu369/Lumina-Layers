import type {
  WorkshopColorLibrary,
  WorkshopRecipeSource,
} from "./contracts";

interface WorkshopHandoffColorLibraryMetadata {
  id: string | null;
  matchedSelectionKey: string | null;
}

const handoffColorLibraryMetadata =
  new WeakMap<
    WorkshopRecipeSource,
    WorkshopHandoffColorLibraryMetadata
  >();

export function rememberWorkshopHandoffColorLibraryId(
  source: WorkshopRecipeSource,
  colorLibraryId: string | null,
  currentColorLibrary?: WorkshopColorLibrary | null,
  currentSelectionKey?: string,
): void {
  handoffColorLibraryMetadata.set(source, {
    id: colorLibraryId,
    matchedSelectionKey:
      colorLibraryId !== null &&
      colorLibraryId === currentColorLibrary?.id &&
      currentSelectionKey !== undefined
        ? currentSelectionKey
        : null,
  });
}

export function readWorkshopHandoffColorLibraryId(
  source: WorkshopRecipeSource,
): string | null | undefined {
  return handoffColorLibraryMetadata.get(source)?.id;
}

export function hasWorkshopHandoffColorLibraryChanged(
  source: WorkshopRecipeSource,
  currentColorLibrary: WorkshopColorLibrary | null,
  currentSelectionKey?: string,
): boolean {
  const metadata = handoffColorLibraryMetadata.get(source);
  if (metadata === undefined) {
    return false;
  }
  if (
    metadata.matchedSelectionKey !== null &&
    metadata.matchedSelectionKey === currentSelectionKey
  ) {
    return false;
  }
  return metadata.id !== (currentColorLibrary?.id ?? null);
}
