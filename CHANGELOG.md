# Changelog

All notable changes to Lumina Studio are documented in this file.

[📖 中文更新日志 / Chinese Changelog](CHANGELOG_CN.md)

---

## Unreleased

### Removed
- **Docker deployment** - Removed image builds, Compose provisioning, deployment/auto-update scripts, container CI and public-test origin bypasses. Use local installation or the Electron desktop client. Linux native wheels now build directly on the host; see [Runtime support](docs/runtime-support.md).

### Features
- **Quick Recolor & Similar Recipes** - Color Adjustment gains a new **Similar colors** selection tool (selects every block within a ΔE00 color-difference tolerance) and a quick-recolor card: choose a target color B (type it, or use the eyedropper to click any point on the image) and replace the current selection with it in one click (LUT sources snap B to the nearest printable color), or pick from similar recipes ranked by color difference, each showing its layer stack. LUT sources suggest measured LUT entries (plus predicted recipes when the LUT has a prediction model); material-archive sources suggest colors already in the image. Suggestions whose color already appears in the image are marked "In image".
- **Selection Workstation (Next-Gen)** - Reworked region selection around a single authoritative server-side selection mask with revision-based optimistic locking. Clicking a block now selects the whole visible matched-colour component instantly (local 4-connected flood-fill with server reconciliation), clicking again deselects, and a new **Selection Brush** paints circular strokes to sweep whole blocks into the selection. Selection boundaries render as Photoshop-style marching ants (white/black dual dashed outline) that stay crisp at any zoom and honour reduced-motion preferences.
- **Checkpoint-based Undo/Redo** - All colour adjustments (replace, region replace, batch, recipe overrides, free colours, reset) now snapshot server-side before applying; undo/redo restores the exact state including the execution-time selection. Selection gestures are undoable individually and fold into the content operation they precede. "Clear all replacements" is itself undoable, and free-colour toggles are now reversible.
- **Same-Colour Select Follows Recolour** - After recolouring a block, picking the new colour on the preview continues editing the same upstream colour; "select all same colour" and "pick blocks" now share one selection that survives tool switches.
- **Extractor Enhancements** - Manufacturer field selects from the material library (with load/empty states), extracted brand names canonicalize to a standard form (incl. the "Aliz" Chinese alias), and 5-colour JSON recipes are preserved through extraction.
- **Custom Recipe Layer Editing** - Reorder layers by drag-and-drop, apply a recipe by typing colour letters (e.g. `WRYBG`), and see "viewing face" annotations in the hover inspector.
- **Help & Settings Copy Rework** - All help triggers use a lighter info icon (also available on dropdowns/radio groups), and every basic-setting item gained a plain-language explanation free of algorithm jargon; guidance is codified in `DESIGN.md`.
- **Puzzle Mode Finish Pass** - Added puzzle-layout overlay preview in the converter workspace, a dedicated puzzle settings widget, 2D/3D overlay rendering, recipe import/export support, and combined 3MF assembly for per-piece puzzle generation
- **Native Source Bundle Selection** - Added legacy/native source switching, native brand + DB bundle selection, native predictive source metadata, and backend catalog/normalization for reference bundles
- **Single-Stage Workflow** - Added single-stage dataset extraction, Stage A fitting endpoints, store wiring, and UI/test coverage for the single-stage calibration flow
- **Predictive Recipe Workflow** - Added predictive recipe color search/apply flows, native custom recipe editing, and supporting runtime metadata for predictive/native LUT sources
- **Reproducible Bug Reports** - Bug reports now land as ticket directories (`feedback/<YYYY-MM>/<ticket_id>/`) carrying the user's original image, generated 3MF / ZIP, LUT snapshot, selected materials bundle, 30-minute action history, 500-entry client log buffer, and a bilingual `index.md` / `summary.txt`. Run `python scripts/load_bug_repro.py <ticket_id>` to rebuild the session locally without guessing what the user did.

### Behavior Changes
- **Legacy LUT selection stays multi-choice** - The traditional LUT database keeps its same-group multi-select checkbox list.
- **Selection tools regrouped** - The palette toolbar now offers "Same colour / Pick blocks / Selection brush"; the former "Single" mode entry was removed (its 3D paths remain internally).

### Fixes
- **Selection reliability** - Fixed stale-response races that could pick the wrong block or resurrect cleared selections; dragging no longer misfires as a click; preview no longer flashes while region highlights load.
- **Undo/redo consistency** - Undoing a selection gesture re-publishes the restored mask so recipe/region flows keep working (previously a 409 "No selected regions available for recipe override").
- **Puzzle Preview Reliability** - Fixed stale failure races that could clear a newer successful overlay, and allowed same-parameter puzzle overlay retries after transient failures
- **Puzzle Import Normalization** - Imported recipes now normalize puzzle-vs-large-format and puzzle-vs-keychain-loop conflicts, and clear the reserved back-label engraving flag during import
- **Combined Puzzle 3MF Metadata** - Combined exports now rebuild slice metadata, filament-sequence metadata, and package preview images instead of inheriting stale first-piece metadata
- **Puzzle Export Boundary Accuracy** - Puzzle exports now preserve crop-local polygon boundaries through meshing, disable puzzle-only material dilation, and keep coating/outline geometry aligned to the authoritative piece silhouette to reduce XY overlap and oversized tabs
- **SVG Puzzle Piece Stability** - SVG puzzle generation now aligns per-piece helper rasters and boundary JSON to the worker's exact rebuild grid, and rounds float-epsilon piece widths instead of truncating them to avoid empty meshes
- **Unsupported Back Engraving Guard** - Back-label engraving is now treated as reserved and rejected during generation instead of silently exporting without geometry changes
- **Smoke Coverage** - Added puzzle backend/frontend coverage to the fast smoke gate
- **Native/Puzzle Contract Hardening** - Restored puzzle response summaries, reconnected puzzle generation to the frontend generate path, forwarded fridge-magnet payloads, and normalized recipe overrides across preview/apply/generate/large-format flows
- **Preview and Session Safety** - Cleared stale preview sessions when source selections change, prevented native bundle generate from reusing legacy sessions, and tightened pre-session temp cleanup for native preview failures
- **Governance and Encoding Cleanup** - Removed new catch-all exception regressions in governed paths, fixed the vector-engine false-positive print() governance trigger, and cleaned real mojibake from `.gitignore`
- **Single-Stage ZIP Safety** - Hardened ZIP extraction against path traversal and made malformed ZIP uploads return deterministic 422 responses with pre-session temp-file cleanup

## v1.6.4 (2026-03-20)

### Improvements (PR #159 by @sandboxdream)
- **Rendering Performance** - Optimized 3D scene rendering and reduced unnecessary re-renders
- **Panel UI Refactor** - Unified slate color scheme, rounded card layout, and `panelPrimitives` component library (`cx`, `PanelIntro`, `StatusBanner`)
- **Settings Reliability** - Async retry mechanism (`retryAsync`) for settings loading; legacy slicer/printer option ID normalization (`settingsOptionIds`)
- **Slider Enhancement** - New `displayDecimals` and `minInputWidthCh` props for finer display control
- **Tooltip Cleanup** - Removed inline tooltip from Checkbox and Slider components for cleaner UI
- **Temp File Cleanup** - Auto-detect colors endpoint now properly cleans up temporary files
- **Project Maintenance** - Updated AGENTS.md guidelines

### Contributors
- Thanks to [@sandboxdream](https://github.com/sandboxdream) for the comprehensive UI/UX improvements and settings reliability enhancements in PR [#159](https://github.com/MOVIBALE/Lumina-Layers/pull/159) 🎉

---

## v1.6.3 (2026-03-08)

### Features
- **Cloisonné Mode** - Auto-extract color boundaries to generate metal wire frames; wire exported as independent object for metallic material assignment; adjustable wire width (0.2-1.2mm) and height (0.04-1.0mm); enforced single-sided mode
- **Free Color Mode** - Use any RGB color beyond LUT constraints; custom color sets with independent 3MF object export
- **Transparent Coating Layer** - Add transparent protective layer at model bottom; adjustable height (0.04-0.12mm); independent object export for transparent material
- **Outline Border** - Add customizable border around model; adjustable width (0.5-5.0mm); smart integration with coating layers
- **Card Palette Layout** - Display LUT colors in physical calibration board spatial arrangement; 8-color auto A/B group split; toggle between block/card layout
- **Color Search & Filter** - Color picker search, Hex/RGB text search, hue family filtering (Red/Orange/Yellow/Green/Cyan/Blue/Purple/Neutral), auto-scroll with breathing light animation
- **2.5D Relief Mode** - Height-based modeling with independent Z-axis heights per color; optical layering preserved (top 5 layers); auto height generator (Min-Max normalization); heightmap support (PNG/JPG/BMP); smart validation for aspect ratio and contrast
- **Isolated Pixel Cleanup** - Automatic noise reduction for isolated color pixels; auto-enabled in High-Fidelity mode
- **Connected Region Color Replacement** - Local color replacement by 4-connected regions; dual-list palette (user replacement / auto-matched); click-to-replace on 2D preview
- **CIELAB Perceptual Color Matching** - Color matching switched from RGB Euclidean distance to CIELAB perceptual uniform space; applied to all color matching operations
- **Automatic Color Merging** - Low-usage color consolidation with CIELAB Delta-E distance; adjustable threshold with preview/apply/revert; test case: 390 → 62 colors (84% reduction)
- **Slicer Integration** - One-click launch for Bambu Studio / OrcaSlicer / ElegooSlicer; direct workflow without manual drag-and-drop; persistent slicer selection
- **Complete BambuStudio 3MF Export** - Full multi-material support with proper object naming and metadata integration
- **5-Color Extended Mode** - Full pipeline support for 5-color extended mode (extractor/converter/naming/UI)
- **Color Recipe Logging** - Color mapping documentation and logging system with download support
- **Clear Output** - Support clearing output directory with real-time size display
- **Large Canvas Option** - Advanced option to remove size limits
- **Progress Display** - Real-time progress feedback across convert_image_to_3d/svg_to_mesh stages

### Bug Fixes
- Fixed 8-color stacking order causing incorrect color mixing
- Fixed 8-color ref_stacks format consistency with 4-color/6-color [top...bottom]
- Fixed viewing surface (Z=0) and back surface inversion
- Fixed RYBW mode incorrectly detected as BW mode
- Fixed color replacement now correctly updates material_matrix stacking data
- Fixed outline mesh missing on image boundary edges
- Fixed missing import for safe_fix_3mf_names in BW calibration generation
- Fixed coating/outline compatibility when both features enabled simultaneously
- Fixed relief/cloisonné mutual exclusion with auto-disable and info toast
- Fixed preview click coordinate transformation
- Fixed 5-Color high-fidelity top/bottom and left/right orientation
- Fixed 5-Color Extended model orientation and SVG layer count
- Disabled 2.5D relief for 5-Color Extended mode
- Fixed 2.5D relief mode state leaks, hex key mismatch and parameter clamping
- Fixed SVG subpath handling
- Fixed color_recipe_path return value inconsistency after main branch merge
- Removed svg_to_mesh internal progress calls to avoid UI event loop GIL interference
- Removed redundant preview pre-generation in generate_with_auto_preview
- Fixed HEIC format support: frontend display, upload file_types, passback conversion
- Fixed cached 3MF invalidation when parameters change
- Fixed ModelingMode None crash on image upload
- Unified 8-color stacks asset path resolution
- Restored ZIP_DEFLATED compression and indent alignment
- Removed leftover conflict marker in bambu_3mf_writer.py
- Fixed SVG upload crash during base64 preprocessing
- Fixed SVG geometry crop: replaced pixel-based Dual-Pass Crop with geometry-based bounds crop
- Fixed SVG even-odd fill rule when combining subpaths
- Fixed icon.ico dimensions
- Fixed slicer launch return count mismatch (5 outputs)
- Removed unused create_5color_combination_tab and duplicate helper functions from layout_new.py

### Features (Post-Release)
- **Multi-Color LUT Support** - Added multi-color LUT support and color recipe query functionality

### Performance
- Full pipeline speed optimization: SVG mode UI ~140s → ~51s (2.7x speedup)
- Optimized 3MF generation pipeline: vectorized mesh, parallel generation, streaming export, SVG caching

### Other
- Relicensed project to GPLv3
- Relief max height default adjusted to 2.4; coating slider range to 0.08-0.16
- Standardized status messages by removing emoji characters

---

## v1.5.9 (2026-02-26)

### Code Quality
- Replaced all bare exception catches (`except:`) with `except Exception:`

---

## v1.5.8 (2026-02-25)

### Features
- **Isolated Pixel Cleanup** - Auto-enabled in High-Fidelity mode; smart detection and merging of isolated color blocks
- **Backing Separation** - Backing exported as independent object; fixed backing layer hardcoding and parameter passing

---

## v1.5.7 (2026-02-10)

### Features
- **6-Color Extended Mode** - 1296 colors (6 base filaments × 3 layers) for wider color gamut
- **8-Color Professional Mode** - 2738 colors (8 base filaments × 2 pages) for maximum color range
- **Two-Page Workflow** - 8-color mode uses two calibration boards merged into single LUT
- **Manual Color Correction** - Click any color cell to manually adjust RGB values before merging
- **Smart Corner Detection** - Automatic corner marker colors based on selected mode
- **BW Grayscale Mode** - 32-level grayscale calibration for monochrome prints
- **LUT Merging with Stacking Preservation** - Combine multiple LUTs (8+6+4+BW); NPZ format with colors and stacking arrays; intelligent reconstruction; full color replacement support
- **Docker Support** - Dockerfile for containerized deployment
- **Unified 4-Color Architecture** - Unified 4-color mode architecture with full automated test suite

### Bug Fixes
- Fixed 8-color stacking order causing incorrect color mixing
- Fixed 8-color ref_stacks format consistency [top...bottom]
- Fixed viewing surface (Z=0) and back surface inversion
- Fixed RYBW mode incorrectly detected as BW mode
- Fixed RYBW calibration board color recognition
- Fixed 8-color manual correction persistence after merge
- Fixed Mac UI styling issues
- Width/height slider input blur triggers linked calculation to avoid frequent jumps during manual input

---

## v1.5.6 (2026-02-08)

### Features
- **Complete 8-Color Image Conversion** - Full 8-color mode support in UI; auto-detection for 2600-2800 color range LUTs
- **ModelingMode Enum Migration** - Migrated modeling mode from string comparison to ModelingMode enum

### Bug Fixes
- Fixed 8-color mode stacking effect
- Fixed about page missing v1.5.4 version number

---

## v1.5.5 (2026-02-07)

### Features
- 8-color calibration board algorithm optimization and quality improvement

---

## v1.5.4 (2026-02-06)

### Features
- **Vector Mode Improvements** - Boolean operation optimization for color overlap handling; SVG order preservation for correct layering; micro Z-offset (0.001mm) for detail independence; enhanced small feature protection

### Bug Fixes
- Fixed black background in vector mode 2D preview
- Fixed preview click coordinate transformation
- Added missing colormath library to requirements

### Other
- Removed deprecated layout.py

---

## v1.5.3 (2026-02-05)

### Features
- **Image Cropping** - Non-invasive image cropping with aspect ratio presets
- **Color Analyzer** - Extracted color recommendation algorithm to independent ColorAnalyzer module
- **Auto Color Detail Button** - Added width factor support; fixed duplicate click toast issue
- **Color Replacement Undo** - Added undo functionality; fixed quantized color count parameter not passed

### Performance
- Vectorized color mapping with RGB encoding + searchsorted
- Vectorized _greedy_rect_merge with NumPy operations

---

## v1.5.1 (2026-02-03)

### Features
- **Complete UI Overhaul** - Full UI redesign with batch mode implementation and i18n support
- **Preview Follows Modeling Mode** - Preview updates based on modeling mode selection
- **Greedy Rectangle Merge** - Optimized 3MF face count with greedy rectangle merging algorithm

### Performance
- K-Means pre-scaling optimization: 20-50x speedup for large images

### Bug Fixes
- Fixed single-sided 3MF output X-axis mirroring
- Reverted smart mesh simplification to fix missing mesh bugs
- Fixed merge conflicts in i18n.py

---

## v1.5.0 (2026-02-01)

### Features
- **Code Standardization** - All code comments translated to English; unified Google-style docstrings; removed redundant comments

---

## v1.4.2 (2026-01-31)

### Features
- **Tray Icon i18n** - Multi-language support for system tray icon menu options

### Bug Fixes
- Version number update and bug fixes
- Reverted "3MF color injection" feature

---

## v1.4.1 (2026-01-29)

### Features
- **Modeling Mode Consolidation** - High-Fidelity mode replaces Vector & Woodblock modes; two unified modes (High-Fidelity / Pixel Art)
- **Dynamic Language Toggle** - Click language button to switch Chinese/English; full UI translation without page reload
- **Output Directory** - Save output files to local project output directory instead of C: temp

### Bug Fixes
- Fixed 3MF naming issue when colors are missing; use local output dir
- Fixed transparent background recognition issue

---

## v1.4 (2026-01-20)

### Features
- **Three Modeling Modes** - Vector Mode (smooth curves, OpenCV contour extraction), Woodblock Mode (SLIC superpixels + detail preservation), Voxel Mode (blocky geometry)
- **Color Quantization Engine** - "Cluster First, Match Second" with K-Means clustering (8-256 colors); 1000x speed improvement; spatial denoising
- **Resolution Decoupling** - Vector/Woodblock: 10 px/mm, Voxel: 2.4 px/mm
- **Smart 3D Preview Downsampling** - Large models auto-simplify preview
- **Browser Crash Protection** - Detects model complexity, disables preview for 2M+ pixels
- **System Tray Integration** - System tray icon with macOS title bar support
- **Modular Code Structure** - Refactored into Core/UI/Utils modules
- **Auto Port Selection** - Automatically selects available port to avoid conflicts

### Bug Fixes
- Fixed macOS 26812 trace trap memory issue
- Fixed cumulative generation statistics font color
- Fixed language switch button styling
- Fixed Windows image causing errors on deletion

---

## v1.3 (2026-01-18)

### Features
- **Bilingual UI** - Chinese/English labels throughout the interface
- **Live 3D Preview** - Interactive preview with actual LUT-matched colors
- **Dual Color Modes** - Full support for both CMYW and RYBW color systems

### Bug Fixes
- Fixed 3MF naming (slicer shows correct color names)
- Optimized default gap to 0.82mm for standard line widths

---

## v1.2 (2026-01-17)

### Features
- **Unified Application** - All three tools (Calibration Generator, Color Extractor, Image Converter) merged into single application

---

## v1.0 (2026-01-15)

### Initial Release
- Calibration board generator
- Color extractor with computer vision
- Image-to-3D converter with LUT-based color matching
- CMYW/RYBW color system support
- 3MF export for BambuStudio compatibility
