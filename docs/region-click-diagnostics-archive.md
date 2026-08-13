# Region click diagnostics archive

Last updated: 2026-06-17

## Status

The temporary click-selection diagnostics added during the color adjustment
selection investigation are disabled. The normal selection path should not show
a diagnostics toolbar, copy diagnostic JSON, generate per-click diagnostic IDs,
or echo those IDs through `/api/convert/region-detect`.

## Why it was disabled

- The diagnostics UI was only useful while investigating missed or delayed
  click selection.
- Keeping the button in the palette tools added visual noise.
- Sending a generated click ID through frontend state, API payloads, backend
  response models, and structured logs added overhead to the hot click path.
- Default region detection already avoids highlight PNG generation; selected
  areas are drawn from returned contours on the frontend.

## What the temporary report contained

The removed frontend report assembled:

- page URL, user agent, viewport, and device pixel ratio;
- current converter session id and selection mode;
- preview image URL, base preview URL, preview pixel size, and preview width in
  millimeters;
- selected color, selected color count, current region, and selected regions;
- recent client log entries related to region/click selection;
- recent generated click ids.

## If diagnostics are needed again

Prefer reintroducing them behind an explicit development flag instead of showing
them in the default UI. Keep the production click path free of:

- automatic click-id generation;
- extra client log entries on every click;
- API request/response fields used only for tracing;
- backend preview PNG generation unless a debug caller explicitly requests it.

For normal user-facing selection, render exact contours on the frontend and keep
backend work limited to region lookup plus contour generation for the selected
component.
