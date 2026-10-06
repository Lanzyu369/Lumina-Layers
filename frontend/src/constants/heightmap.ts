/** Formats accepted by the heightmap picker and share-card restoration. */
export const HEIGHTMAP_IMAGE_TYPES = [
  "image/png",
  "image/jpeg",
  "image/bmp",
  "image/tiff",
] as const;

export const ACCEPT_HEIGHTMAP_FORMATS = HEIGHTMAP_IMAGE_TYPES.join(",");
