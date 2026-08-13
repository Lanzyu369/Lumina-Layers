# Preserve Uploaded Filename for 3MF Downloads Design

## Goal

Add an opt-in setting that lets a normal single-item converter export use the
uploaded artwork name for its downloaded 3MF. For example, `海报.png` downloads
as `海报.3mf`.

The setting is off by default so existing users keep the current descriptive
name, such as `海报_Lumina_HiFi_4C_20260813_123456.3mf`, until they explicitly
change the preference.

## Scope

The preference applies only to a normal single-artifact converter generation
served by `POST /api/convert/generate`, including:

- raster high-fidelity and pixel generation
- native SVG vector generation
- material-archive generation
- model-surface generation when it uses the current single uploaded artwork

The preference does not change names for:

- batch output
- puzzle output
- large-format ZIP output or the 3MF files inside it
- calibration models or kits
- recipe/material swatches and other generated color cards
- preview GLB, PNG, JSON, share-card, LUT, or material downloads

The change affects only the filename exposed to the user. It does not change
3MF bytes, geometry, slicer metadata, internal temporary paths, or the isolated
temporary copy used when Lumina opens an artifact in a slicer.

## User Experience

Add one switch under **Settings > General**:

- Chinese label: `导出 3MF 时沿用上传文件名`
- English label: `Use uploaded filename for 3MF exports`
- default: off

The supporting text states that the option applies to the next normal
single-item generation and gives the example `海报.png → 海报.3mf`. It also
states that batch, puzzle, and large-format exports keep their existing names.
All copy comes from `frontend/src/i18n/translations.ts`.

Add one bilingual, end-user-oriented entry to the in-app announcements after
following `docs/announcement-maintenance.md`. The announcement describes the
new optional setting and its default-off behavior without exposing internal
implementation terms.

Changing the switch invalidates an existing eligible single-item download URL
and disk-path fallback, because that artifact was registered under the previous
naming rule. It preserves the uploaded image, session, 2D preview, and 3D
preview, so the user only needs to generate the final 3MF again. Downloads from
excluded workflows are not invalidated by this preference.

## Approaches Considered

### 1. Override the public download filename at file registration (selected)

Keep the generated file at its existing unique, timestamped internal path. When
the option is enabled, register the final artifact with `上传名.3mf` as its
public filename. The file endpoint then produces the correct
`Content-Disposition` for button downloads and copied download links.

This is selected because naming remains an output-delivery concern, repeated
generations cannot overwrite one another, and the 3MF generation pipeline does
not need to understand a UI preference.

### 2. Set an HTML anchor `download` value in the frontend

This would be a smaller local edit, but it would affect only downloads initiated
by that specific button. A copied `/api/files/...` link and other download
callers could still receive the old name, producing inconsistent behavior.

### 3. Rename the generated file on disk

This would make the internal and public names match, but identical uploads or
repeated generations could collide. It would also spread a presentation
preference into worker and pipeline code without changing the model itself.

## Architecture and Data Flow

### Settings state

Add the boolean `preserveUploadFilenameFor3mf` and setter
`setPreserveUploadFilenameFor3mf` to `settingsStore`, with a default of `false`.
Existing Zustand persistence merges the default into older `lumina-settings`
snapshots, so no destructive migration is required.

This is a client-local file-management preference. It is intentionally excluded
from `user_settings.json` backend sync and share-card recipes because it does not
affect artwork interpretation, generated geometry, materials, print settings,
or conversion-recipe reproducibility. The current boolean is nevertheless
captured as an optional bug-report diagnostic so filename issues can be
reproduced; the source filename and path are not added to that payload.

### Request boundary

The normal `convertGenerate` client call sends the current preference as the
optional outer request field `preserve_upload_filename_for_3mf` alongside
`session_id` and `params`. The backend `_GenerateBody` wrapper declares it as a
strict boolean defaulting to `false` for compatibility with older clients.

The field must not be added to `ConvertGenerateRequest`: that object is reused
by puzzle, large-format, batch, and share-card-related flows. Keeping the option
on the outer normal-generate request makes the scope explicit and prevents it
from leaking into conversion recipes.

### Source-name resolution

Preview already records a stable extension-free `source_basename` from the
upload metadata. The normal generate endpoint reads that session value only
after a valid 3MF has been produced.

A focused naming helper defensively normalizes the basename before adding
`.3mf`:

- preserve Unicode, spaces, hyphens, and internal dots
- remove only the final uploaded extension before generation, so
  `海报.final.png` becomes `海报.final.3mf`
- replace cross-platform forbidden characters, prefix Windows reserved device
  names, and truncate on code-point boundaries so the final `.3mf` component
  fits within 255 UTF-8 bytes
- remove legacy temporary-upload prefixes
- trim unsafe leading or trailing spaces and dots
- return no override when the result is empty

If the option is off, the session value is missing/stale, or normalization
produces an empty name, registration falls back to the existing generated
filename. A naming preference must never make an otherwise valid generation
fail.

### File registration and download

The worker continues returning the existing unique timestamped 3MF path. The
router passes the resolved public filename to `FileRegistry.register_path()`
only for an eligible normal single-item output. The registry remains the source
of truth for `/api/files/{id}`, and `file_to_response()` continues producing an
RFC 5987 UTF-8 `Content-Disposition` for non-ASCII names.

The final artifact keeps its current TTL/ephemeral lifecycle and remains
downloadable after the source session is closed or switched. No disk path is
exposed in the API response.

Opening the result in a slicer continues to use Lumina's isolated launch-copy
mechanism. That temporary copy is intentionally outside this feature: it is not
the user's exported file and protects the canonical generated artifact from
slicer mutations.

## Error Handling and Safety

- The new request field is optional and strict boolean validation rejects
  malformed values rather than interpreting arbitrary strings as enabled.
- Filename normalization is deterministic and cannot introduce path
  separators or response-header control characters.
- Missing upload metadata and legacy sessions fall back to the current name.
- Internal paths stay unique, so two uploads with the same source name cannot
  overwrite one another. The browser may apply its normal duplicate-download
  suffix when a file with the same name already exists locally.
- The filename and source path are not added to analytics payloads or new INFO
  logs.

## Testing and Verification

### Backend

- Naming-helper unit tests cover Chinese/Unicode, spaces, multiple dots,
  forbidden characters, control characters, temporary prefixes, and empty
  fallback cases.
- Normal generate endpoint tests prove the default/off path retains the current
  descriptive filename.
- Enabled endpoint tests prove `海报.png` resolves to a public `海报.3mf`
  filename while the registered disk path remains the unique generated path.
- A download-response test checks the UTF-8 `Content-Disposition` value.
- A lifecycle regression closes or switches the source session before fetching
  the enabled download URL and proves the 3MF still downloads with the intended
  name and bytes.
- Color-card generation retains its current filename even if the outer option
  is enabled.
- Existing puzzle, large-format, batch, calibration, and swatch naming tests
  remain unchanged and pass.

### Frontend

- Settings-store tests cover default-off behavior, setter persistence, and
  hydration from a legacy snapshot with no new field.
- Settings-panel tests cover bilingual copy, General-category placement, switch
  state, and accessible labeling.
- Converter API tests prove only the normal generate wrapper sends the optional
  outer field.
- Converter-store tests prove normal single generation forwards the setting;
  puzzle, large-format, and batch requests do not inherit it.
- Invalidation tests prove toggling the setting clears only an eligible existing
  single-item download while preserving preview state and excluded-workflow
  downloads.
- Bug-report tests prove the current boolean is captured, accepted by the
  backend, rendered for triage, and remains optional for older clients.

### Verification commands and manual check

- Run focused backend tests for naming, file responses, settings-adjacent
  contracts, and converter generation.
- Run focused frontend suites through `python scripts/run_vitest.py run ...`.
- Run the frontend TypeScript build and lint checks relevant to touched files.
- In the real browser flow, upload `海报.final.png`, generate once with the
  setting off and once with it on, and verify the downloaded names differ as
  designed while the 3MF opens normally.
- Confirm there are no leftover backend, Vite, Vitest, or browser-verification
  helper processes.

## Non-Goals

- A user-editable filename text field or filename template language
- Renaming already generated artifacts without regenerating
- Changing names inside batch, puzzle, large-format, calibration, or swatch
  packages
- Renaming slicer launch copies
- Syncing the preference across browsers or embedding it in share cards
- Changing 3MF package contents, geometry, materials, thumbnails, or print
  profiles
