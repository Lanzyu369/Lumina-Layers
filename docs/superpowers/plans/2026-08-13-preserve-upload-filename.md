# Preserve Uploaded Filename for 3MF Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a default-off Settings switch that makes normal single-item 3MF downloads use the uploaded artwork basename, for example `海报.png` → `海报.3mf`.

**Architecture:** Keep worker output paths and 3MF bytes unchanged. Send the client-local preference as an outer field on only the normal generate request, resolve a safe public filename from the preview session's `source_basename`, and pass that filename to `FileRegistry` so every download-link consumer receives the same `Content-Disposition`. A narrow frontend invalidator clears only an eligible single-item download when the preference changes and preserves preview state.

**Tech Stack:** Python 3, FastAPI, Pydantic, pytest, React 19, TypeScript, Zustand, Vitest, Testing Library.

---

## File map

- `core/naming.py`: own the reusable, cross-platform source-basename-to-3MF filename normalization.
- `api/routers/converter/generate.py`: validate the outer preference field and select the public filename at final artifact registration.
- `tests/test_naming_unit.py`: cover filename normalization and fallback inputs.
- `tests/test_converter_generate_unit.py`: cover default compatibility, enabled registration, UTF-8 response headers, color-card exclusion, and session-close lifecycle.
- `frontend/src/api/converter.ts`: serialize the preference outside `ConvertGenerateRequest` for normal generation only.
- `frontend/src/__tests__/converter-api.test.ts`: lock the request-body boundary.
- `frontend/src/stores/generatedArtifactInvalidation.ts`: expose a narrowly named single-item download invalidation bridge.
- `frontend/src/stores/settingsStore.ts`: persist the default-off preference and invoke the narrow invalidator on change.
- `frontend/src/stores/converter/store.ts`: forward the preference for normal generation and adopt the invalidator without clearing previews or excluded outputs.
- `frontend/src/__tests__/settings-store-hydration.test.ts`: verify the store forwards the preference to normal generation.
- `frontend/src/__tests__/settings-upload-filename.test.ts`: verify persistence, legacy fallback, and targeted invalidation.
- `frontend/src/components/SettingsPanel.tsx`: render the switch under Settings > General.
- `frontend/src/components/__tests__/SettingsPanel.layout.test.tsx`: verify placement, copy, accessibility, and interaction.
- `frontend/src/i18n/translations.ts`: provide bilingual regular UI copy.
- `frontend/src/data/announcements.ts`: add the required bilingual end-user announcement for 2026-08-13.
- `frontend/src/__tests__/useAnnouncement.test.ts` and `frontend/src/__tests__/announcement-dialog.test.tsx`: existing announcement contracts; run unchanged as regressions.
- `frontend/src/api/feedback.ts` and `frontend/src/utils/bugReportContext.ts`: capture the current boolean for filename-issue reproduction without exposing a source name or path.
- `api/routers/feedback.py` and `api/feedback_index.py`: accept the optional diagnostic from old/new clients and surface it in ticket triage output.
- `frontend/src/utils/__tests__/bugReportContext.test.ts`, `tests/test_feedback_router_unit.py`, and `tests/test_feedback_index_unit.py`: cover diagnostic capture, compatibility, persistence, and rendering.

### Task 1: Normalize a source basename into a safe 3MF download name

**Files:**
- Modify: `tests/test_naming_unit.py`
- Modify: `core/naming.py`

- [ ] **Step 1: Write failing normalization tests**

Import `generate_preserved_upload_3mf_filename` and add focused cases:

```python
@pytest.mark.parametrize(
    ("source_basename", "expected"),
    [
        ("海报", "海报.3mf"),
        ("海报 final", "海报 final.3mf"),
        ("海报.final", "海报.final.3mf"),
        ('bad<name>:*', "bad_name___.3mf"),
        ("tmpabcd1234_poster", "poster.3mf"),
        ("line\nbreak", "line_break.3mf"),
        ("  poster.  ", "poster.3mf"),
    ],
)
def test_generate_preserved_upload_3mf_filename(source_basename, expected):
    assert generate_preserved_upload_3mf_filename(source_basename) == expected


@pytest.mark.parametrize("source_basename", [None, "", "   ", ".", ".."])
def test_generate_preserved_upload_3mf_filename_returns_none_without_safe_stem(
    source_basename,
):
    assert generate_preserved_upload_3mf_filename(source_basename) is None
```

- [ ] **Step 2: Run the tests and confirm the missing helper failure**

Run:

```bash
python -m pytest tests/test_naming_unit.py -q
```

Expected: collection fails because `generate_preserved_upload_3mf_filename` is not defined.

- [ ] **Step 3: Implement the focused naming helper**

Add a control-character regex and this public helper to `core/naming.py`, reusing the existing temp-prefix and forbidden-character logic:

```python
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def generate_preserved_upload_3mf_filename(
    source_basename: str | None,
) -> str | None:
    """Build a safe 3MF download name from an uploaded source basename.

    根据上传文件的无扩展名名称生成安全的 3MF 下载文件名。

    Args:
        source_basename: Extension-free basename captured from upload metadata.
            从上传元数据中取得的无扩展名文件名。

    Returns:
        A safe ``.3mf`` filename, or ``None`` when no usable stem remains.
        安全的 ``.3mf`` 文件名；无法得到有效名称时返回 ``None``。
    """
    stem = str(source_basename or "").strip()
    if not stem:
        return None
    stem = _strip_temp_prefix(stem)
    stem = _CONTROL_CHAR_RE.sub("_", stem)
    stem = _sanitize(stem).strip(" .")
    return f"{stem}.3mf" if stem else None
```

- [ ] **Step 4: Run the naming tests and verify green**

Run:

```bash
python -m pytest tests/test_naming_unit.py -q
```

Expected: all naming tests pass, including existing timestamped naming behavior.

- [ ] **Step 5: Commit the naming unit**

```bash
git add core/naming.py tests/test_naming_unit.py
git commit -m "feat(converter): add upload filename normalizer"
```

### Task 2: Apply the name only at normal single-item file registration

**Files:**
- Modify: `tests/test_converter_generate_unit.py`
- Modify: `api/routers/converter/generate.py`

- [ ] **Step 1: Add failing endpoint tests**

Extend the existing source-session lifecycle fixture so the session contains
`source_basename = "海报.final"`, then exercise both request modes:

```python
_test_store.put(sid, "source_basename", "海报.final")

enabled_payload = {
    "session_id": sid,
    "preserve_upload_filename_for_3mf": True,
    "params": {"lut_name": "test_lut"},
}
response = client.post("/api/convert/generate", json=enabled_payload)
file_id = response.json()["download_url"].rsplit("/", 1)[-1]
entry = _test_registry.get_entry(file_id)
assert entry is not None
assert entry["filename"] == "海报.final.3mf"
assert entry["path"] == out_path

download = client.get(response.json()["download_url"])
assert download.headers["content-disposition"] == (
    "attachment; filename*=utf-8''%E6%B5%B7%E6%8A%A5.final.3mf"
)
```

Add separate assertions that:

```python
# Missing outer field remains backward-compatible.
assert default_entry["filename"] == os.path.basename(out_path)

# Strict bool validation rejects accidental strings.
assert client.post(
    "/api/convert/generate",
    json={
        "session_id": sid,
        "preserve_upload_filename_for_3mf": "true",
        "params": {"lut_name": "test_lut"},
    },
).status_code == 422
```

Use the existing color-card generate fixture with the outer flag enabled and
assert the registry filename remains the worker-generated color-card name. Keep
the enabled lifecycle test's source-session close before the final GET so the
TTL download contract is covered by the same test.

- [ ] **Step 2: Run focused endpoint tests and confirm failures**

Run:

```bash
python -m pytest tests/test_converter_generate_unit.py -q -k "filename or session_close or color_card"
```

Expected: enabled-name and strict-validation assertions fail because the outer field and registration override do not exist yet.

- [ ] **Step 3: Add the outer strict field and registration resolver**

In `api/routers/converter/generate.py`, import `StrictBool` and the Task 1 helper:

```python
from pydantic import BaseModel, StrictBool, ValidationError
from core.naming import generate_preserved_upload_3mf_filename
```

Extend only `_GenerateBody`:

```python
class _GenerateBody(BaseModel):
    """Wrapper combining session_id with generate parameters."""

    session_id: str
    params: ConvertGenerateRequest
    preserve_upload_filename_for_3mf: StrictBool = False
```

Immediately before the first final-3MF `register_path()` call, resolve a public
name without changing `threemf_path`:

```python
download_filename = None
if body.preserve_upload_filename_for_3mf and not generated_color_card_svg:
    download_filename = generate_preserved_upload_3mf_filename(
        session_data.get("source_basename")
    )

download_id = registry.register_path(
    str(uuid.uuid4()),
    threemf_path,
    filename=download_filename,
    ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
)
```

Passing `None` deliberately retains the registry's existing path-basename fallback.

- [ ] **Step 4: Run backend tests and verify behavior**

Run:

```bash
python -m pytest tests/test_naming_unit.py tests/test_converter_generate_unit.py -q
```

Expected: PASS; enabled downloads expose the uploaded basename, default and color-card paths retain their old names, and downloads survive session close.

- [ ] **Step 5: Commit the backend behavior**

```bash
git add api/routers/converter/generate.py tests/test_converter_generate_unit.py
git commit -m "feat(converter): preserve source name for 3mf downloads"
```

### Task 3: Add the normal-generate client boundary and store forwarding

**Files:**
- Modify: `frontend/src/__tests__/converter-api.test.ts`
- Modify: `frontend/src/__tests__/settings-store-hydration.test.ts`
- Modify: `frontend/src/api/converter.ts`
- Modify: `frontend/src/stores/converter/store.ts`

- [ ] **Step 1: Write failing API and store assertions**

Update the normal client test to call:

```typescript
await convertGenerate("sess-abc", generateParams, true);

expect(body).toEqual({
  session_id: "sess-abc",
  preserve_upload_filename_for_3mf: true,
  params: generateParams,
});
```

Retain a second call with the third argument omitted and assert the field is
`false`. In `settings-store-hydration.test.ts`, set:

```typescript
settingsStoreModule.useSettingsStore.setState({
  preserveUploadFilenameFor3mf: true,
});
```

and assert:

```typescript
expect(converterApi.convertGenerate).toHaveBeenCalledWith(
  "sess-1",
  expect.any(Object),
  true,
);
```

- [ ] **Step 2: Run the focused frontend tests and confirm signature failures**

Run:

```bash
python scripts/run_vitest.py run src/__tests__/converter-api.test.ts src/__tests__/settings-store-hydration.test.ts
```

Expected: FAIL because `convertGenerate` accepts two arguments and the setting does not exist.

- [ ] **Step 3: Extend the API function without touching converter parameters**

Change `convertGenerate` to:

```typescript
export async function convertGenerate(
  sessionId: string,
  params: ConvertGenerateRequest,
  preserveUploadFilenameFor3mf = false,
): Promise<GenerateResponse> {
  const response = await apiClient.post<GenerateResponse>(
    "/convert/generate",
    {
      session_id: sessionId,
      preserve_upload_filename_for_3mf: preserveUploadFilenameFor3mf,
      params,
    },
    { timeout: 0 },
  );
  return response.data;
}
```

Do not add this field to `ConvertGenerateRequest`, `LargeFormatGenerateRequest`,
`PuzzleGenerateRequest`, batch payloads, or recipe schemas.

- [ ] **Step 4: Forward the setting only from the normal store branch**

In the branch after puzzle and large-format early returns, call:

```typescript
const response = await apiConvertGenerate(
  sessionId,
  baseParams,
  useSettingsStore.getState().preserveUploadFilenameFor3mf,
);
```

Puzzle, large-format, and batch calls remain unchanged, which mechanically
prevents the preference from entering excluded workflows.

- [ ] **Step 5: Run API/store tests and verify green**

Run:

```bash
python scripts/run_vitest.py run src/__tests__/converter-api.test.ts src/__tests__/settings-store-hydration.test.ts src/stores/__tests__/converter-native-source.test.ts
```

Expected: PASS; normal generation has the third argument and excluded endpoint calls retain their existing shapes.

- [ ] **Step 6: Commit the request plumbing**

```bash
git add frontend/src/api/converter.ts frontend/src/stores/converter/store.ts frontend/src/__tests__/converter-api.test.ts frontend/src/__tests__/settings-store-hydration.test.ts
git commit -m "feat(converter): send 3mf filename preference"
```

### Task 4: Persist the switch and invalidate only eligible downloads

**Files:**
- Create: `frontend/src/__tests__/settings-upload-filename.test.ts`
- Modify: `frontend/src/stores/generatedArtifactInvalidation.ts`
- Modify: `frontend/src/stores/settingsStore.ts`
- Modify: `frontend/src/stores/converter/store.ts`

- [ ] **Step 1: Write failing setting and invalidation tests**

The new test imports both stores, resets them, and verifies:

```typescript
expect(DEFAULT_SETTINGS.preserveUploadFilenameFor3mf).toBe(false);

useSettingsStore.getState().setPreserveUploadFilenameFor3mf(true);
expect(useSettingsStore.getState().preserveUploadFilenameFor3mf).toBe(true);
expect(
  JSON.parse(localStorage.getItem("lumina-settings") ?? "{}").state
    .preserveUploadFilenameFor3mf,
).toBe(true);
```

For an ordinary result, seed `downloadUrl`, `threemfDiskPath`, `modelUrl`,
`previewGlbUrl`, and `previewImageUrl`; toggle the setting; assert only the
download URL and disk fallback become `null`. Parameterize excluded states:

```typescript
it.each([
  { batchMode: true },
  { puzzleEnabled: true },
  { largeFormatEnabled: true },
  { modeling_mode: ModelingMode.COLOR_CARD },
])("keeps excluded workflow downloads for %o", (excludedState) => {
  useConverterStore.setState({
    ...excludedState,
    downloadUrl: "/api/files/excluded",
  });
  useSettingsStore.getState().setPreserveUploadFilenameFor3mf(true);
  expect(useConverterStore.getState().downloadUrl).toBe(
    "/api/files/excluded",
  );
});
```

Also hydrate a version-1 localStorage snapshot without the new key and assert
the current default remains `false`.

- [ ] **Step 2: Run the new test and confirm missing-state failures**

Run:

```bash
python scripts/run_vitest.py run src/__tests__/settings-upload-filename.test.ts
```

Expected: FAIL because the state, setter, and narrow invalidator are missing.

- [ ] **Step 3: Add the narrow invalidation bridge**

In `generatedArtifactInvalidation.ts`, add a separately registered callback:

```typescript
type InvalidateSingleItemDownload = () => void;

let invalidateSingleItemDownloadHandler: InvalidateSingleItemDownload | null = null;

export function registerSingleItemDownloadInvalidator(
  handler: InvalidateSingleItemDownload,
): void {
  invalidateSingleItemDownloadHandler = handler;
}

export function invalidateSingleItemDownload(): void {
  invalidateSingleItemDownloadHandler?.();
}
```

In `converter/store.ts`, register the adopter next to the existing invalidators:

```typescript
registerSingleItemDownloadInvalidator(() => {
  const state = useConverterStore.getState();
  if (
    state.batchMode ||
    state.puzzleEnabled ||
    state.largeFormatEnabled ||
    state.modeling_mode === ModelingModeEnum.COLOR_CARD
  ) {
    return;
  }
  useConverterStore.setState({
    threemfDiskPath: null,
    downloadUrl: null,
  });
});
```

- [ ] **Step 4: Add the persisted default-off setting**

Add to `SettingsState`, `SettingsActions`, and `DEFAULT_SETTINGS`:

```typescript
preserveUploadFilenameFor3mf: boolean;
setPreserveUploadFilenameFor3mf: (enabled: boolean) => void;

preserveUploadFilenameFor3mf: false,
```

Implement the setter with a no-op guard and the narrow invalidator:

```typescript
setPreserveUploadFilenameFor3mf: (enabled: boolean) => {
  if (get().preserveUploadFilenameFor3mf === enabled) {
    return;
  }
  set({ preserveUploadFilenameFor3mf: enabled });
  invalidateSingleItemDownload();
},
```

Keep the preference out of `syncToBackend()` and `UserSettings`.

- [ ] **Step 5: Run the setting/invalidation tests and verify green**

Run:

```bash
python scripts/run_vitest.py run src/__tests__/settings-upload-filename.test.ts src/__tests__/settings-store.property.test.ts src/__tests__/settings-store-hydration.test.ts
```

Expected: PASS; legacy snapshots default off, ordinary stale downloads clear, and previews/excluded outputs remain.

- [ ] **Step 6: Commit the preference state**

```bash
git add frontend/src/stores/generatedArtifactInvalidation.ts frontend/src/stores/settingsStore.ts frontend/src/stores/converter/store.ts frontend/src/__tests__/settings-upload-filename.test.ts
git commit -m "feat(settings): persist 3mf filename preference"
```

### Task 5: Add Settings UI, bilingual copy, and announcement

**Files:**
- Modify: `frontend/src/components/__tests__/SettingsPanel.layout.test.tsx`
- Modify: `frontend/src/components/SettingsPanel.tsx`
- Modify: `frontend/src/i18n/translations.ts`
- Modify: `frontend/src/data/announcements.ts`

- [ ] **Step 1: Write the failing Settings component assertion**

After selecting the General category, assert the section and switch:

```typescript
const filenameSection = screen.getByTestId(
  "settings-preserve-upload-filename-section",
);
expect(
  within(filenameSection).getByText(
    "开启后，普通单件生成会把“海报.png”下载为“海报.3mf”。默认关闭；批量、拼图和大画幅继续使用原有名称。",
  ),
).toBeInTheDocument();

const filenameSwitch = within(filenameSection).getByRole("switch", {
  name: "导出 3MF 时沿用上传文件名",
});
fireEvent.click(filenameSwitch);
expect(
  useSettingsStore.getState().preserveUploadFilenameFor3mf,
).toBe(true);
```

- [ ] **Step 2: Run the component test and confirm it fails**

Run:

```bash
python scripts/run_vitest.py run src/components/__tests__/SettingsPanel.layout.test.tsx
```

Expected: FAIL because the section and translations do not exist.

- [ ] **Step 3: Add bilingual translation entries**

Add these keys to `translations.ts`:

```typescript
"settings.preserve_upload_filename_heading": {
  zh: "导出 3MF 时沿用上传文件名",
  en: "Use uploaded filename for 3MF exports",
},
"settings.preserve_upload_filename_description": {
  zh: "开启后，普通单件生成会把“海报.png”下载为“海报.3mf”。默认关闭；批量、拼图和大画幅继续使用原有名称。",
  en: "When enabled, a normal single-item export downloads “poster.png” as “poster.3mf”. It is off by default; batch, puzzle, and large-format exports keep their existing names.",
},
```

- [ ] **Step 4: Render the General-category switch**

Select the state and action near the other General settings, then add:

```tsx
<div
  data-testid="settings-preserve-upload-filename-section"
  className="flex items-start justify-between gap-4 border-t border-slate-200/60 pt-5 dark:border-slate-700/60"
>
  <div className="min-w-0">
    <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
      {t("settings.preserve_upload_filename_heading")}
    </h3>
    <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
      {t("settings.preserve_upload_filename_description")}
    </p>
  </div>
  <Switch
    checked={preserveUploadFilenameFor3mf}
    onChange={setPreserveUploadFilenameFor3mf}
    ariaLabel={t("settings.preserve_upload_filename_heading")}
  />
</div>
```

- [ ] **Step 5: Prepend the 2026-08-13 announcement entry**

Follow `docs/announcement-maintenance.md` and add:

```typescript
{
  version: "2026-08-13",
  title: {
    zh: "Lumina Layers — 8 月更新",
    en: "Lumina Layers — August Update",
  },
  sections: [
    {
      category: { zh: "新功能", en: "New" },
      items: [
        {
          zh: "设置里新增“导出 3MF 时沿用上传文件名”开关，默认关闭；开启后，普通单件作品会把“海报.png”下载为“海报.3mf”，批量、拼图和大画幅仍使用原有名称。",
          en: "Settings now include an optional “Use uploaded filename for 3MF exports” switch. It is off by default; when enabled, a normal single-item “poster.png” downloads as “poster.3mf”, while batch, puzzle, and large-format exports keep their existing names.",
        },
      ],
    },
  ],
},
```

- [ ] **Step 6: Run UI and announcement tests**

Run:

```bash
python scripts/run_vitest.py run src/components/__tests__/SettingsPanel.layout.test.tsx src/__tests__/useAnnouncement.test.ts src/__tests__/announcement-dialog.test.tsx
```

Expected: PASS with both locales present and the switch accessible in General.

- [ ] **Step 7: Commit the user-facing surface**

```bash
git add frontend/src/components/SettingsPanel.tsx frontend/src/components/__tests__/SettingsPanel.layout.test.tsx frontend/src/i18n/translations.ts frontend/src/data/announcements.ts
git commit -m "feat(settings): add uploaded filename switch"
```

### Task 6: Full verification and real-browser acceptance

**Files:**
- Modify only if a verification failure exposes a defect in a file already listed above.

- [ ] **Step 1: Run focused backend regression suites**

```bash
python -m pytest tests/test_naming_unit.py tests/test_converter_generate_unit.py tests/test_file_registry_batch_ttl_unit.py -q
```

Expected: PASS.

- [ ] **Step 2: Run focused frontend regression suites**

```bash
python scripts/run_vitest.py run src/__tests__/converter-api.test.ts src/__tests__/settings-upload-filename.test.ts src/__tests__/settings-store.property.test.ts src/__tests__/settings-store-hydration.test.ts src/stores/__tests__/converter-native-source.test.ts src/components/__tests__/SettingsPanel.layout.test.tsx src/__tests__/useAnnouncement.test.ts src/__tests__/announcement-dialog.test.tsx
```

Expected: PASS with no orphan Vitest workers.

- [ ] **Step 3: Run static frontend checks**

From `frontend/`:

```bash
pnpm exec tsc --noEmit
pnpm lint
pnpm build
```

Expected: all commands exit 0.

- [ ] **Step 4: Run the real browser workflow**

Start the app using the repository launcher, open Settings > General, and verify
the switch is off. Upload a valid image named `海报.final.png`, generate and
download once with the setting off, then enable the setting, confirm the old
download action is invalidated without losing previews, regenerate, and confirm
the browser downloads `海报.final.3mf`. Open that file in the selected slicer and
confirm it loads normally. Switch to batch, puzzle, and large-format modes and
confirm their download naming remains unchanged.

- [ ] **Step 5: Stop every process started for acceptance**

```bash
python start_all.py --kill
```

Then inspect process command lines for this worktree and confirm no
`api_server.py`, `start_all.py`, Vite, Vitest, or esbuild process remains.

- [ ] **Step 6: Check encoding and diff hygiene**

```bash
LC_ALL=C rg -n "锟|鎷|鍙|涓|�" core/naming.py api/routers/converter/generate.py frontend/src/components/SettingsPanel.tsx frontend/src/i18n/translations.ts frontend/src/data/announcements.ts tests/test_naming_unit.py tests/test_converter_generate_unit.py frontend/src/__tests__/settings-upload-filename.test.ts frontend/src/components/__tests__/SettingsPanel.layout.test.tsx
git diff --check
git status --short
```

Expected: no mojibake marker in touched text, no whitespace errors, and only intended files changed.

- [ ] **Step 7: Commit any verification-only corrections**

If verification required a correction, stage only the affected feature files and commit:

```bash
git commit -m "test(converter): verify uploaded filename exports"
```

If no correction was needed, do not create an empty commit.

### Task 7: Capture the preference in bug-report diagnostics

**Files:**
- Modify: `frontend/src/api/feedback.ts`
- Modify: `frontend/src/utils/bugReportContext.ts`
- Modify: `frontend/src/utils/__tests__/bugReportContext.test.ts`
- Modify: `api/routers/feedback.py`
- Modify: `api/feedback_index.py`
- Modify: `tests/test_feedback_router_unit.py`
- Modify: `tests/test_feedback_index_unit.py`

- [ ] **Step 1: Add failing capture, schema, and triage-rendering tests**

Require the live client to send `preserve_upload_filename_for_3mf`, require the
backend to retain `true` and `false`, and require both `index.md` and
`summary.txt` to show the submitted state. Also prove older clients may omit the
field.

- [ ] **Step 2: Add the optional diagnostic field end to end**

Keep the frontend transport type and backend schema optional for compatibility,
while the current context collector always emits a concrete boolean. Render the
state for triage without capturing any source filename or filesystem path.

- [ ] **Step 3: Run focused feedback tests and the production build**

```bash
python -m pytest tests/test_feedback_router_unit.py tests/test_feedback_index_unit.py -q
cd frontend
python ../scripts/run_vitest.py run src/utils/__tests__/bugReportContext.test.ts src/api/__tests__/feedback.test.ts src/components/__tests__/BugReportModal.test.tsx
pnpm build
```

Expected: PASS; old feedback fixtures continue compiling and legacy payloads
remain accepted.
