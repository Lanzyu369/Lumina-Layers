# Credits

The header's **More options → About Lumina Studio → Credits** action lazily opens
`AboutDialog`. The native macOS About menu opens the same page; before renderer
readiness it retains the system About fallback. The About page shows the native
app version (web package version as fallback), official site and GitHub links.
Credits opens within the same dialog and returns to About with focus restored.
The public catalog is fetched only on entering Credits, not on opening About.
The view uses the layout, shared controls, MiSans font and theme tokens from
PR #668. The current workspace stays mounted but inert and hidden; its 3D
canvas pauses until the credits view closes.

`catalog.ts` owns the public data boundary:

- Read `https://lumina-studio-credits.pages.dev/manifest.json` anonymously.
- Resolve the roster URL and `assets_base` relative to that manifest.
- Verify roster bytes, SHA-256, schema, identity fields and record count.
- Keep the last verified catalog in IndexedDB; failed updates preserve it.
- Abort closed/superseded requests. Storage failure does not block online use.

`CreditsGarden` owns the controls and a scoped canvas engine. Record avatar
paths remain unchanged in the catalog and are resolved against `assetsBase`
only when loaded. HTTPS platform avatars stay on their original origins;
Cloudflare hosts the relative WebP paths. Image loading is anonymous and
bounded, with best-effort persistent caching and full resource cleanup.

Names, avatar files and financial/source exports are not included in the
application bundle. Update the independently hosted dataset to update credits;
no application or PyPI release is needed for roster-only changes.

The canvas renderer preserves the approved bubble prototype's arc names,
search flight/displacement, pop/recovery physics and sponsor styles. Sponsor
effects start off on every visit. The renderer sizes to its own container and
retains native device-pixel resolution. UI strings live in `translations.ts`.

Focused checks from the repository root:

```sh
python3 scripts/run_vitest.py run src/credits/catalog.test.ts src/credits/AboutDialog.test.tsx src/credits/CreditsGarden.test.tsx src/credits/avatar-cache.test.ts src/components/__tests__/HeaderMenu.test.tsx src/__tests__/App.test.tsx src/__tests__/Scene3D.test.tsx src/__tests__/application-menu.test.tsx
```
