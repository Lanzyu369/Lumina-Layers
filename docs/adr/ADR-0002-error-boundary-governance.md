# ADR-0002: Error Boundaries

## Status
Superseded (2026-10-11) by the current [logging guide](../logging-guide.md)
and [repository guidelines](../../AGENTS.md). The original decision was
accepted on 2026-04-01.

## Rationale
- Broad exception handling previously obscured failure causes and made responses inconsistent.
- The useful requirement is to preserve diagnostics and translate errors at the boundary that owns them.
- Fixed exception counts and source allowlists did not express those guarantees and have been retired.

## Current contract
- Core code raises domain errors; API boundaries translate them through `api.errors.to_http_exception()`.
- Broad catches belong at explicit application or external-library boundaries, with actionable diagnostics or a defined fallback.
- Required operations retain failure semantics. Cleanup and optional-feature fallbacks preserve data and explain any degraded result.

## Verification
Use the relevant error-response, cleanup and structured-log tests for the changed
behavior. The logging guide documents the existing checks and current usage.
