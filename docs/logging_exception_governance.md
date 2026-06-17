# Logging & Exception Governance

## Structured Logging Schema
- `timestamp`: ISO8601 UTC
- `level`: logging level
- `event`: stable event name for querying
- `module`: logger module path
- `request_id`: request correlation id
- `session_id`: Lumina session id if available
- `path`, `method`, `status_code`, `duration_ms`
- `error_type`, `error_message`

## Rules
- Use `api.structured_logging.get_logger(__name__)` in API/worker code.
- Use module-private loggers (for example `_log = logging.getLogger(__name__)`) in `core/*` hot paths.
- Do not add business `print(...)` under governed `api/` and `core/` paths.
- Prefer explicit exceptions first; keep only boundary catch-all points where necessary.
- Use `api.errors.to_http_exception()` at API boundaries for stable mapping.

## Governance Scope
- Guardrail test: `tests/test_logging_exception_governance_unit.py`
- Current governed paths include:
  - API app/router/worker hot paths (`api/app.py`, converter/extractor/vectorizer routers, converter/vectorizer workers).
  - Core converter/extractor/image pipeline hot paths, including:
    - pipeline steps `s01/s03/s04/s06/s07/s08/s09/s11`, `coordinator`, `p01`, `pipeline_utils`
    - processing ops `bilateral/median/image_scaler/lut_color_matcher/kmeans/svg_rasterizer/lut_loader`
    - `core/vector_engine.py`, `core/calibration.py`
- Baseline policy:
  - `print(` in governed paths: `0` (must stay 0)
  - `except Exception` in governed paths: `1` (must not increase; only top-level request middleware guard remains)

## Design Retention Allowlist
- Allowed catch-all location:
  - `api/app.py` request middleware top-level guard.
- Rationale:
  - Ensures unhandled exceptions still produce correlated structured logs
    (`request_id`, `path`, `method`, `duration_ms`) before re-raise.
  - Prevents silent request-chain loss in edge failures outside route-level mapping.
- Policy:
  - No additional `except Exception` points may be introduced in governed scope.
  - If this allowlist changes, update both:
    - `tests/test_logging_exception_governance_unit.py`
    - this governance document

## Request Context
- `X-Request-ID` is accepted from caller or generated server-side.
- Response returns `X-Request-ID`.
- Session-bound endpoints should bind `session_id` for log correlation.

## Examples
- API HTTP errors: `event=api_http_error`, include `request_id`, `path`,
  `method`, `status_code`, `error_type`, and `error_message`
- API validation errors: `event=api_validation_failed`, include the same
  request fields plus a bounded validation summary
- Unhandled API exceptions: `event=api_unhandled_exception`, emitted only by
  the top-level request middleware guard before returning a deterministic 500
- Worker tasks: `event=worker_<name>_started|failed|done`

Do not introduce request-scoped catch-all event names such as
`request_completed`, `request_failed`, or `request_*`. The log quality gate
counts those as bucket events; governed paths must keep
`request_completed_count == 0` and catch-all event count at zero.
