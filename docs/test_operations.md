# Test Operations Guide

Set up the native runtime using [desktop-electron.md](desktop-electron.md), then install test tools with `python -m pip install -r requirements-dev.txt`. PostgreSQL integration is optional: it uses `requirements-postgres.txt` and an explicitly configured disposable database.

## Choose checks for the change

Run these commands from the repository root:

- `python -m pytest tests/test_<affected>_unit.py -q`: a focused backend suite.
- `python scripts/run_vitest.py run src/<affected>.test.ts`: a focused frontend suite.
- `python scripts/run_smoke_tests.py`: backend smoke tests, the frontend core subset, and lint.
- `python scripts/run_full_tests.py`: all backend `test_*.py` files (including native integration), release-marked checks, all frontend tests, the TypeScript/Vite build, and lint.

Documentation-only edits do not need runtime tests. Use the full suite when requested or when affected shared workflows need broader coverage. Do not make it an obligation for every task.

Always use `scripts/run_vitest.py` for non-watch frontend tests so the wrapper can clean up test workers. From `frontend/`, use `pnpm build` and `pnpm lint` for build/lint checks.

For URL behavior, run `python scripts/run_vitest.py run src/__tests__/resource-url.test.ts`. For error responses and logging, use:

```sh
python -m pytest tests/test_api_errors_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -q
```

Logging workflow checks are described in [logging-guide.md](logging-guide.md).

## Live feedback

Use `python scripts/run_realtime_tests.py` when a live test dashboard is wanted. It periodically runs backend smoke checks, frontend watch tests, and optional lint; logs go under `.cache/test-dashboard/`.

Useful options are `--no-lint`, `--smoke-interval 60`, and `--lint-interval 180`. Stop the dashboard when finished; ordinary verification does not need a watch process.

## Performance checks

For performance changes, use the existing profiling tools:

```sh
python scripts/profile_stage3.py --also-write-latest
python scripts/check_perf_regression.py
```

The profile writes `artifacts/perf_baseline.json` and `docs/perf_baseline.md`. Keep a reproducible workload and environment; do not generate a historical baseline from current output just to make a check pass.

The regression check compares warm medians (runs 2 and 3) by default. Thresholds come from the baseline file, with defaults of +15% for WARN and +30% for FAIL. Exit codes are `0=PASS`, `1=WARN`, and `2=FAIL`. Use the reported hotspot segments to investigate regressions.

Use `--regenerate-current` to collect current measurements and `--use-cold-start` when deliberately investigating startup behavior. Cold-start data is separate from the default warm comparison.

## Useful regression coverage

Test observable results and known failure paths. Do not test variable spelling, helper existence, copies of the implementation, or arbitrary test-count targets.

Keep property generators within real input constraints. The Hypothesis profile in `tests/conftest.py` uses 100 examples, no deadline, and suppresses the too-slow health check; do not suppress unrelated health checks merely to pass a test.

Async tests use `asyncio_mode=auto` from `pytest.ini`. Isolate filesystem/process side effects and make timeout expectations explicit.

If behavior intentionally changes, update affected callers, regression tests, and current documentation. A separate ADR, governance report, or tracking form is not required.

## When a check fails

Re-run the failing command printed by the runner, preferably narrowing it to the failing file or case. Inspect the actual input, error, and environment before changing code.

For missing dependencies, check the runtime setup, `requirements-dev.txt`, and `pnpm install` in `frontend/`. After fixing a failure, re-run the affected checks and any broader suite requested for the task.
