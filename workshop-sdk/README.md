# Lumina Workshop SDK

`@lumina/workshop-sdk` is the public, versioned contract between Lumina Studio
and installable Creative Workshop modules.

Modules run inside a restricted iframe. They never import Lumina Studio source
files or call private APIs. Instead, they connect through the SDK and request
explicit capabilities such as image selection, project storage, the current
color library, and image handoff.

## Install

```bash
pnpm add @lumina/workshop-sdk
```

## Package contract

- API version: `1.0.0`
- Manifest version: `1`
- UI entry point: `ui/index.html`
- Runtime transport: a host-provided `MessagePort`

The module manifest must declare every requested permission and explain why it
is needed. Lumina Studio remains responsible for user confirmation, storage
quotas, converter handoff, and runtime isolation.

The complete module-development and packaging guide lives in the Lumina Studio
repository at `docs/workshop-module-development.md`.
