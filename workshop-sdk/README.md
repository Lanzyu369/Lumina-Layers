# Lumina Workshop SDK

`@lumina/workshop-sdk` is the public, versioned contract between Lumina Studio
and installable Creative Workshop modules.

Modules run inside a restricted iframe. They never import Lumina Studio source
files or call private APIs. Instead, they connect through the SDK and request
explicit capabilities such as image selection, project storage, the current
color library, and image handoff.

## Install the immutable v1 release

Lumina publishes the SDK only as a versioned GitHub Release asset. Verify the
checksum before adding the exact tarball URL to a module:

```text
https://github.com/lumina-layer-studio/Lumina-studio/releases/download/workshop-sdk-v1.0.1/lumina-workshop-sdk-1.0.1.tgz
```

```bash
gh release download workshop-sdk-v1.0.1 \
  --repo lumina-layer-studio/Lumina-studio \
  --pattern "lumina-workshop-sdk-1.0.1.tgz*" \
  --dir .workshop-sdk-release
cd .workshop-sdk-release
shasum -a 256 -c lumina-workshop-sdk-1.0.1.tgz.sha256
```

Pin that exact immutable asset in `package.json`:

```json
{
  "dependencies": {
    "@lumina/workshop-sdk": "https://github.com/lumina-layer-studio/Lumina-studio/releases/download/workshop-sdk-v1.0.1/lumina-workshop-sdk-1.0.1.tgz"
  }
}
```

There is no npm publication, floating release asset, or unversioned download
URL. A module repository should commit its lockfile so the resolved SDK
artifact remains reviewable.

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

## Minimal connection fixture

```ts
import {
  connectWorkshop,
} from "@lumina/workshop-sdk";

const host = await connectWorkshop({
  moduleId: "studio.lumina.example",
  moduleVersion: "1.0.0",
});

await host.lifecycle.ready();
```

The host validates the module identity, negotiates only declared permissions,
and activates a candidate only after this ready handshake succeeds.
