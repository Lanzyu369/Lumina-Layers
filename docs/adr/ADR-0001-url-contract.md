# ADR-0001: Frontend Resource URL Contract

## Status
Accepted (2026-04-01)
Updated (2026-10-11): retired the test-source literal allowlist.

## Context
- URL drift previously caused grouped frontend test failures (`absolute` vs `relative` mismatch).
- Current frontend behavior stores resource links in state and passes them across components, making contract consistency mandatory.

## Decision
- Canonical form for backend resource links in frontend state and business logic is **relative URL**.
  - Examples: `/api/files/<id>`, `/output/<name>.zip`
- Absolute backend URL input is treated as compatibility input and must be normalized before writing it to state.
- Tests may supply absolute URLs to exercise normalization, compatibility and failure paths. Assertions on stored backend resource links follow the relative URL contract.

## Consequences
- Prevents environment-coupled test assertions (e.g. `localhost:8000`).
- Keeps frontend behavior stable across local/dev/proxy deployment topologies.
- Test fixtures can describe external inputs without imposing a filename allowlist.

## Verification
- [Normalization tests](../../frontend/src/__tests__/resource-url.test.ts) exercise actual URL conversion.
- Relevant API and store tests check the resource links produced by the affected workflow.
