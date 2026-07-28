# Design QA — Material picker pointer focus ring

**Comparison target**

- Source visual truth: `/var/folders/gn/myfgtzws3fx2b0m2nn6w8h7r0000gn/T/codex-clipboard-18d509fb-5cdf-4270-9b87-6fb3067e119a.png`
- Preserved source copy: `/Users/min/.codex/worktrees/a1ad/Lumina-studio/.scratch/design-audit/material-picker-focus-ring/user-reference.png`
- Browser implementation: `/Users/min/.codex/worktrees/a1ad/Lumina-studio/.scratch/design-audit/material-picker-focus-ring/browser-after-matched.jpg`
- Combined focused comparison: `/Users/min/.codex/worktrees/a1ad/Lumina-studio/.scratch/design-audit/material-picker-focus-ring/focused-comparison.png`
- Source pixels: `1560 × 720`; browser screenshot pixels and CSS viewport: `1316 × 815`; browser density was unchanged.
- State: light theme, material archive picker open, one single-profile material selected through a pointer click.
- Normalization: the source is a camera crop with a handwritten annotation, so pixel-perfect full-modal comparison would be misleading. The selected-card regions were cropped and normalized to the same width for the combined focused comparison.

**Findings**

- No remaining actionable P0, P1, or P2 issue in the requested pointer-selection state.
- Fonts and typography: unchanged; the fix does not alter type family, size, weight, line height, wrapping, or truncation.
- Spacing and layout rhythm: card padding, radius, grid, metadata row, and favorite-button spacing remain unchanged.
- Colors and visual tokens: the unintended four-pixel inner focus ring is absent after a pointer click. The intended selected-card border and blue checked indicator remain.
- Image quality and asset fidelity: material swatches and existing Heroicons are unchanged and remain sharp.
- Copy and content: unchanged.

**Full-view comparison evidence**

- `browser-after-matched.jpg` confirms the modal layout, brand sidebar, card geometry, footer, and selection affordances remain intact.
- The selected material still has its normal outer selected-card treatment, without the extra inner pale-blue rectangle.

**Focused region comparison evidence**

- `focused-comparison.png` places the annotated source crop and the post-fix selected-card crop in one comparison image.
- Browser-computed evidence after the pointer click: the selection button remained the active element, `:focus-visible` was `false`, and `box-shadow` was `none`.

**Comparison history**

1. Initial finding: `[P2]` a pointer click triggered `focus:ring-4`, leaving a pale-blue inner rectangle even though the button did not match `:focus-visible`.
2. Incorrect first iteration: the selected card's outer active style was removed, but the reported inner focus ring remained. This did not address the user's annotated target.
3. Corrective fix: restored the outer selected-card treatment and changed material selection controls from `focus:ring-4` to `focus-visible:ring-2`.
4. Post-fix evidence: a same-viewport pointer click produced `box-shadow: none`; selecting and deselecting returned the staged material count to eight.

**Open Questions**

- None.

**Implementation Checklist**

- [x] Remove the persistent inner ring from pointer selection.
- [x] Retain a keyboard-only focus indicator.
- [x] Restore the intended outer selected-card treatment.
- [x] Cover the pointer-focus class contract and selected-card treatment with regression tests.
- [x] Verify the actual interaction in the user's Chrome page.

**Follow-up Polish**

- None required for this focused correction.

final result: passed
