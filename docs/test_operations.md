# Test Operations Guide

## 1) Test Layers (default workflow)

### `smoke` (pre-commit fast gate)
- Command: `python scripts/run_smoke_tests.py`
- Includes:
  - Backend smoke: `pytest -m smoke`
  - Frontend core vitest subset
  - Frontend lint
- Use when:
  - Before push
  - During iterative fixes
- Output contract:
  - prints gate start/end time, total duration, failure summary, and next-step commands.

### `full` (release-level regression)
- Command: `python scripts/run_full_tests.py`
- Includes:
  - Backend full pytest
  - Frontend full vitest
  - Frontend lint
- Use when:
  - Before merge/release
  - After refactor touches shared flows
- Output contract:
  - same structured summary as smoke (start/end/duration/failure summary/recovery commands).

### `watch` (local realtime feedback)
- Command: `python scripts/run_realtime_tests.py`
- Behavior:
  - Periodic backend smoke
  - Vitest watch for core suites
  - Optional periodic lint
  - Live terminal status panel + log files under `.cache/test-dashboard/`
- Useful flags:
  - `--no-lint`
  - `--smoke-interval 60`
  - `--lint-interval 180`

### `profile-stage3` (local perf baseline for S06/S07/S11)
- Command: `python scripts/profile_stage3.py`
- Outputs:
  - `artifacts/perf_baseline.json`
  - `docs/perf_baseline.md`
- Policy:
  - local machine baseline is authoritative for P2 stage-3 v4
  - regression thresholds: `warn=+15%`, `fail=+30%` vs median baseline
  - report includes warm hotspot ranking (top 3 segments per dataset) for diagnosis-first iteration.

### `perf-regression-check` (baseline guard)
- Command: `python scripts/check_perf_regression.py`
- Optional refresh command:
  - `python scripts/check_perf_regression.py --regenerate-current`
- Optional cold-start mode:
  - `python scripts/check_perf_regression.py --use-cold-start`
- Exit code contract:
  - `0=PASS`, `1=WARN`, `2=FAIL`
- Output:
  - regressed metrics (`dataset.metric`), regression percentage, and suggested action.
- Policy:
  - default gate compares `warm median` (run2/run3)
  - `cold-start` (run1) is tracked for startup-path observability, not default blocking signal.
  - when `total_s` regresses, script prints top segment diagnostics to point to S07- or S11-dominant side.

### Performance triage path
- `python scripts/profile_stage3.py --also-write-latest`
- `python scripts/check_perf_regression.py`
- read warm hotspot top3 from `docs/perf_baseline.md`
- apply narrow optimization to dominant segment
- rerun profile + regression check

## 2) Hypothesis & asyncio stability rules

### Hypothesis defaults
- Repo baseline is configured in `tests/conftest.py`:
  - profile: `max_examples=100`
  - `deadline=None`
  - `suppress_health_check=[HealthCheck.too_slow]`
- Prefer these defaults for most property tests.

### When to use `deadline=None` explicitly
- Use for property tests that:
  - involve image/matrix operations
  - involve filesystem or process-pool boundaries
  - have known high runtime variance

### When to use `suppress_health_check=[HealthCheck.too_slow]`
- Use only when variability is expected and deterministic speed is not the test target.
- Do not suppress unrelated health checks unless justified.

### asyncio usage boundary
- `pytest.ini` uses `asyncio_mode=auto`.
- For pure async unit tests, explicit `@pytest.mark.asyncio` is still allowed and recommended for clarity.
- Do not mix blocking event-loop calls and async fixtures in one test without clear isolation.

## 3) Fast failure triage

### A. Environment/setup failure
- Symptoms:
  - import/module not found
  - plugin/runner initialization errors
- First commands:
  - `pip install -r requirements.txt`
  - `cd frontend && pnpm install`
  - `python -m pytest tests/test_logging_exception_governance_unit.py -q`

### B. Smoke failed, full not run yet
- Path:
  1. Re-run failing command printed by smoke script.
  2. Run `python scripts/run_realtime_tests.py --no-lint`.
  3. Fix and re-run smoke.

### C. Full failed after smoke passed
- Path:
  1. Re-run only failed suite:
     - backend: `python -m pytest tests -q`
     - frontend: `python scripts/run_vitest.py run`
  2. Check contract guardrails:
     - `python -m pytest tests/test_logging_exception_governance_unit.py -q`
     - `python scripts/run_vitest.py run src/__tests__/resource-url.test.ts src/__tests__/url-localhost-guard.test.ts`
  3. Re-run full gate.

### D. Contract drift suspicion (URL / exception boundary)
- URL drift checks:
  - `python scripts/run_vitest.py run src/__tests__/resource-url.test.ts src/__tests__/url-localhost-guard.test.ts`
- Exception governance check:
  - `python -m pytest tests/test_logging_exception_governance_unit.py -q`
- If behavior changed intentionally, update:
  - ADR docs under `docs/adr/`
  - governance/report docs

## 4) New test checklist (recommended)
- Unit tests:
  - deterministic and fast
- Property tests:
  - bounded generators
  - explicit assumptions for domain constraints
  - avoid over-broad random blobs unless necessary
- Async tests:
  - isolate side effects
  - clear timeout expectations
- Before submit:
  - smoke must pass
  - full must pass for shared or refactor changes
