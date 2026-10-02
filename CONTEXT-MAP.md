# Lumina Studio Context Map

This map lists only the business-system contexts that are currently
documented. It does not imply that unlisted Lumina workflows are incomplete
or unsupported.

| Topic | Read first | Covers |
| --- | --- | --- |
| Converter edits, commit receipts, preview and generation | [`docs/context/editor/CONTEXT.md`](docs/context/editor/CONTEXT.md) | operation ordering, unknown receipts, publication/rollback, recipe masks, generation snapshots and download lifetime |
| Native SVG coordinate handoff and print geometry | [`docs/context/vector-geometry/CONTEXT.md`](docs/context/vector-geometry/CONTEXT.md) | exact working coordinates, print-grid partition, caches/spawn, structural geometry and native tiling |
| Model-surface selection, preview and generation | [`docs/context/model-surface/CONTEXT.md`](docs/context/model-surface/CONTEXT.md) | local U/V coordinates, model pose ownership, selection/restoration camera transitions, native pocket cutting and regression coverage |
| Creative Workshop, installable modules, public SDK, package validation, Registry, sandbox, project storage, image handoff, official seed | [`docs/context/workshop/CONTEXT.md`](docs/context/workshop/CONTEXT.md) | public `Lumina-Workshop-SDK`, `core/workshop/`, `/api/workshop/v1`, `frontend/src/workshop/`, Electron runtime boundary, recipe and diagnostics integration |

For system-wide decisions, also inspect `docs/adr/` when present. When a topic
has no context document yet, use the real code, tests, and focused maintenance
guide as the source of truth.
