# Design QA — Material picker selected card

**Comparison target**

- Source visual truth: user-provided `Google Chrome Appshot 2026-07-28T18-17-50.450Z.png` in this task.
- Implementation screenshot: `/Users/min/.codex/worktrees/a1ad/Lumina-studio/.scratch/design-audit/material-picker-selected-card/selected-card-after.jpg`
- Source pixels: `1055 × 768`; implementation pixels: `1316 × 871`.
- CSS viewport and density: the implementation was captured from the user's existing Chrome window at `1316 × 871`; browser density was not changed. The source and implementation use different desktop viewport sizes, so the comparison is limited to the selected-card state rather than pixel-level modal geometry.
- State: light theme, material archive picker open, all-materials tab, two-column card grid, multiple materials already selected.

**Findings**

- No remaining P0, P1, or P2 visual mismatch in the requested selected-card state.
- Fonts and typography: unchanged from the existing picker; selected and unselected cards retain the same hierarchy and wrapping behavior.
- Spacing and layout rhythm: card padding, radius, grid spacing, and modal structure are unchanged.
- Colors and visual tokens: selected cards now use the same neutral border and surface tokens as unselected cards; the blue checked circle remains the sole selection accent.
- Image quality and asset fidelity: material swatches and Heroicons remain unchanged and render sharply.
- Copy and content: unchanged.

**Full-view comparison evidence**

- The implementation screenshot preserves the existing desktop modal, brand sidebar, two-column grid, footer, and eight staged selections.
- The source's extra pale-blue selected-card frame is no longer visible.

**Focused region comparison evidence**

- The implementation view contains selected and unselected cards together. Their computed card border and background colors match, while selected cards retain the blue check indicator.
- Browser inspection confirmed the selected card has no `border-blue-400` class.

**Comparison history**

1. Earlier finding: `[P2]` selected material cards gained an extra pale-blue frame, adding a visually redundant second selection cue.
2. Fix: removed the active card frame from both single-profile and grouped-profile material cards; kept the explicit checked/radio selection indicators.
3. Post-fix evidence: `selected-card-after.jpg`; a real select/deselect interaction preserved the neutral card surface and restored the original selected count of eight.

**Open Questions**

- None.

**Implementation Checklist**

- [x] Remove the selected-card blue frame.
- [x] Preserve the blue checked selection indicator.
- [x] Verify a real select/deselect cycle.
- [x] Add regression coverage.

**Follow-up Polish**

- None required for this focused change.

final result: passed
