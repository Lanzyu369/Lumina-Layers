# Design QA — Material picker selection feedback

**Comparison target**

- Source visual truth: `/var/folders/gn/myfgtzws3fx2b0m2nn6w8h7r0000gn/T/codex-clipboard-18d509fb-5cdf-4270-9b87-6fb3067e119a.png`
- Preserved source copy: `/Users/min/.codex/worktrees/a1ad/Lumina-studio/.scratch/design-audit/material-picker-focus-ring/user-reference.png`
- Earlier focus-ring implementation: `/Users/min/.codex/worktrees/a1ad/Lumina-studio/.scratch/design-audit/material-picker-focus-ring/browser-after-matched.jpg`
- Earlier focused comparison: `/Users/min/.codex/worktrees/a1ad/Lumina-studio/.scratch/design-audit/material-picker-focus-ring/focused-comparison.png`
- Source pixels: `1560 × 720`; browser screenshot pixels and CSS viewport: `1316 × 815`; browser density was unchanged.
- State: light theme, material archive picker open, one single-profile material selected through a pointer click.
- Normalization: the source is a camera crop with a handwritten annotation, so pixel-perfect full-modal comparison would be misleading. The selected-card regions were cropped and normalized to the same width for the combined focused comparison.

**Findings**

- No remaining actionable P0, P1, or P2 issue in the requested pointer-selection state.
- Fonts and typography: unchanged; the fix does not alter type family, size, weight, line height, wrapping, or truncation.
- Spacing and layout rhythm: card padding, radius, grid, metadata row, and favorite-button spacing remain unchanged.
- Colors and visual tokens: the unintended four-pixel inner focus ring is absent after a pointer click. The final selected state uses only the whole-card pale-blue surface, border, and light drop shadow; the redundant circle and check are absent.
- Image quality and asset fidelity: material swatches and the favorite-star icon remain sharp.
- Copy and content: unchanged.

**Full-view comparison evidence**

- The final live-browser pass confirms the modal layout, brand sidebar, card geometry, footer, and favorite control remain intact.
- The selected material uses its whole-card pale-blue treatment without an inner focus rectangle, circle, or check.
- Selected and unselected comparison cards both measured `413 × 100.5` CSS pixels and retained `transform: none`.

**Focused region comparison evidence**

- The earlier `focused-comparison.png` documents the pointer-ring correction; the final no-indicator state was validated in the live browser.
- Browser-computed evidence after the pointer click: the selection button remained the active element and `box-shadow` was `none`.
- A new selection reported `animation-name: material-picker-card-select`, `animation-duration: 0.18s`, and `animation-iteration-count: 1`.
- After the effect finished, the pale-blue surface and light drop shadow remained. Deselecting removed the effect class, and selecting again replayed it once.

**Comparison history**

1. Initial finding: `[P2]` a pointer click triggered `focus:ring-4`, leaving a pale-blue inner rectangle even though the button did not match `:focus-visible`.
2. Incorrect first iteration: the selected card's outer active style was removed, but the reported inner focus ring remained. This did not address the user's annotated target.
3. Corrective fix: restored the outer selected-card treatment and changed material selection controls from `focus:ring-4` to `focus-visible:ring-2`.
4. Final interaction refinement: removed the single-profile circle and check, then added a reduced-motion-safe 180ms whole-card glow for newly selected profiles only.
5. Post-fix evidence: a same-viewport pointer click produced `box-shadow: none`; selecting, deselecting, and reselecting changed the staged count `8 → 9 → 8 → 9` without changing card geometry.

**Open Questions**

- None.

**Implementation Checklist**

- [x] Remove the persistent inner ring from pointer selection.
- [x] Retain a keyboard-only focus indicator.
- [x] Restore the intended outer selected-card treatment.
- [x] Remove the redundant single-profile circle and check.
- [x] Play one 180ms whole-card effect only for a new selection.
- [x] Disable the effect when reduced motion is requested.
- [x] Cover the pointer-focus class contract and selected-card treatment with regression tests.
- [x] Verify the actual interaction in the user's Chrome page.

**Follow-up Polish**

- None required for this focused correction.

final result: passed
