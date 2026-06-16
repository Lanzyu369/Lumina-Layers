# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

This repo uses a multi-context domain documentation layout. Contexts are split by business system or workflow, not by a fixed frontend/backend boundary.

## Before exploring, read these

- `CONTEXT-MAP.md` at the repo root. It maps topics to context documents.
- `docs/context/<domain>/CONTEXT.md` for the relevant business system or workflow.
- `docs/adr/` for system-wide architectural decisions.
- Context-specific ADRs may live under `docs/context/<domain>/adr/` if a workflow later needs its own decisions.

If a referenced context document does not exist yet, proceed with the real code and note the missing context only when it affects the task.

## File structure

```text
/
|-- CONTEXT-MAP.md
`-- docs/
    |-- adr/
    `-- context/
        `-- <domain>/
            |-- CONTEXT.md
            `-- adr/
```

## Use the glossary's vocabulary

When your output names a domain concept in an issue title, a refactor proposal, a hypothesis, or a test name, use the term as defined in the relevant `CONTEXT.md`. Do not drift to synonyms the glossary explicitly avoids.

If the concept you need is not in the glossary yet, either reconsider whether the project already uses another term or note the gap when it affects the task.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding it.
