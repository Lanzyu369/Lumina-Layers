# Lumina Studio Frontend

React, TypeScript, Zustand, and Three.js UI for the Python API. Run the backend from the repository root with `python api_server.py` or start both services with `python start_all.py`.

From this directory:

```sh
corepack enable
pnpm install
pnpm dev
pnpm build
pnpm lint
```

Use the pnpm version pinned in `package.json`. Vite serves development at `http://localhost:4174` and proxies API requests to port `8000`.

Run tests from the repository root through the process-cleanup wrapper:

```sh
python scripts/run_vitest.py run
```

See [DESIGN.md](../DESIGN.md) for UI conventions, [AGENTS.md](../AGENTS.md) for repository guidance, and [test_operations.md](../docs/test_operations.md) for targeted and full checks.
