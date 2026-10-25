import type { CreditsCatalog } from './types';

export interface CreditsGardenLabels {
  noResults: string;
  found: string;
  source: string;
}

export interface CreditsGardenController {
  setEffects(enabled: boolean): void;
  setMotion(enabled: boolean): void;
  dispose(): void;
}

export function createCreditsGarden(root: HTMLElement, catalog: CreditsCatalog,
  labels: CreditsGardenLabels): CreditsGardenController;
