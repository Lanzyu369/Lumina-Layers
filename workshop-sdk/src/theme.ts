import { WorkshopUiState } from "./contracts.js";

export function applyWorkshopUiState(
  state: WorkshopUiState,
  root: HTMLElement = document.documentElement,
): void {
  root.lang = state.locale;
  root.dataset.theme = state.theme;
  for (const [name, value] of Object.entries(state.tokens)) {
    if (/^--lumina-[a-z0-9-]+$/.test(name)) {
      root.style.setProperty(name, value);
    }
  }
}
