/** Public display record; funding amounts and private account details are excluded. */
export interface CreditsRecord {
  id: string;
  name: string;
  source: string;
  avatar?: string;
  avatar_size?: [number, number];
  avatar_preview?: string;
  avatar_preview_size?: [number, number];
  tier: number;
  dev: boolean;
  brand: boolean;
  aliases?: string[];
}

/** Validated catalog and the asset origin used only at the image boundary. */
export interface CreditsCatalog {
  records: CreditsRecord[];
  assetsBase: string;
  stale: boolean;
}
