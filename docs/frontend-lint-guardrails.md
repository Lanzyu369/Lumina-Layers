# Frontend Lint Guardrails (P1-1)

This document defines the lint guardrails added for i18n and theme-token convergence.

## Rules

- `lumina/no-hardcoded-ui-text` (`warn` now, target `error`)
- `lumina/no-raw-ui-colors` (`warn` now, target `error`)

## What is blocked

- Hardcoded user-facing UI text in component JSX
- Hardcoded text in user-facing attributes: `aria-label`, `title`, `placeholder`, `alt`
- Raw UI color literals in JSX/class/style:
  - `#hex`
  - `rgb(...)` / `rgba(...)`
  - `bg-white`
  - `text-black`

## Allowed exceptions

- `src/__tests__/**`
- `src/i18n/translations.ts`
- `src/theme/**` (token source of truth)
- Low-level render constants that are centralized in theme/token modules

## Migration pattern

- Text:
  - Before: `<button>Close</button>`
  - After: `<button>{t("action_close")}</button>`
- Colors:
  - Before: `style={{ border: "2px solid rgba(...)" }}`
  - After: `style={{ border: UI_COLOR_TOKENS.someBorder }}`

## Debt metric

Use:

```bash
pnpm run lint:debt
```

Current output keys:

- `[token-debt] raw-color-hits=`
- `[token-debt] hardcoded-text-hits=`

The metric should be non-increasing across PRs.
