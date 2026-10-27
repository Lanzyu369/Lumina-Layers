# Logging and exception handling

Current logging usage and verification are documented in [logging-guide.md](logging-guide.md).

- Core code raises domain errors; API boundaries use `api.errors.to_http_exception()` for readable, deterministic responses.
- Failures should retain actionable context and request/session correlation where available.
- Catch broad exceptions only at explicit boundaries or documented fallback paths. Do not replace a useful failure with apparent success.
- Validate actual error responses and structured output with the existing API/error/logger tests.

The former source event inventories, exception-count ceilings, INFO budgets, reviewer baselines, and governance rounds have been removed. No registration procedure is required for ordinary changes.
