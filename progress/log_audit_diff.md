# Lumina Studio log governance final audit

Generated: 2026-04-26 (Asia/Shanghai)
Updated: 2026-04-27 (Asia/Shanghai), with unmocked worker business-flow audit inputs

## Audit inputs

Baseline command/source:

```powershell
Get-Content -Encoding UTF8 progress\log_audit_baseline.json
```

After command:

```powershell
python scripts/audit_logs.py --logs logs --latest 1 --output progress/log_audit_after.json --label after
```

The first sandboxed run failed while writing `progress\log_audit_after.json` with `PermissionError: [Errno 13] Permission denied`. The same command was rerun with approved escalation and generated the after report successfully.

## Initial sample limitation

Both baseline and after reports point to the same latest log file:

```text
logs\lumina_20260426_135251.log
```

That file has only 2 lines and 470 bytes:

```text
[13:52:51.524] [LOG] E:\Lumina-Layers\LL-1296\Lumina-Layers\logs\lumina_20260426_135251.log
[13:52:51.544] {"timestamp":"2026-04-26T05:52:51.544646+00:00","level":"WARNING","event":"optional_dependency_missing",...}
```

This is not a real startup + preview + generation workflow log. It is retained here only as the initial sample limitation. It is not used as the final business-flow acceptance basis.

## Initial tiny-sample metrics

| Metric | Baseline | After |
| --- | ---: | ---: |
| total_lines | 2 | 2 |
| total_bytes | 470 | 470 |
| duplicate_event_count | 0 | 0 |
| duplicate_event_ratio | 0.0 | 0.0 |
| request_completed_count | 0 | 0 |
| request_completed_ratio | 0.0 | 0.0 |
| structured_lines | 1 | 1 |
| unstructured_lines | 1 | 1 |
| top_events | unstructured=1, optional_dependency_missing=1 | unstructured=1, optional_dependency_missing=1 |

## Business-flow audit

Final quantitative acceptance uses the following business-flow audit reports:

- Before: `progress\log_audit_flow_before.json`, generated from `logs\lumina_20260425_232340.log`. This is a historical pre-change preview + generate log with `preview=True` and `generate=True`.
- Mocked after, superseded: `progress\log_audit_flow_after.json`, generated from `progress\flow_after_logs\lumina_20260426_154520.log`. This was produced from current code with TestClient running startup, one `/api/convert/preview`, one `/api/convert/generate`, and shutdown.
- Unmocked after: `progress\log_audit_unmocked_after.json`, regenerated from `logs\lumina_20260427_003445.log`. This was produced from `python api_server.py` with a real WorkerPool, one `GET /api/lut/list`, one `POST /api/convert/preview`, one `POST /api/convert/generate`, one `POST /api/convert/region-detect`, and one `POST /api/convert/region-replace`.

Historical caveat, now superseded: the previous after sample used a mocked worker. FastAPI middleware, routing, and route-level logging were real executions, but the real worker internals were not represented by that sample. The unmocked audit session above replaces it as the release-quality source for worker-inclusive log numbers.

Unmocked command notes:

```powershell
$env:LUMINA_LOG_PATH = "logs\unmocked_after.log"
$env:LUMINA_LOG_LEVEL = "INFO"
python api_server.py
python scripts/audit_logs.py --logs logs\lumina_20260427_003445.log --latest 1 --output progress\log_audit_unmocked_after.json --label unmocked_after
```

Current `api_server.py` still selected a timestamped file through `setup_file_logging()` and overwrote the pre-set path. The actual audited file was therefore `logs\lumina_20260427_003445.log`; it has been removed as a temporary log after the JSON report was generated.

| Metric | Flow before | Unmocked after | Reduction |
| --- | ---: | ---: | ---: |
| total_lines | 1001 | 11 | 98.90% |
| total_bytes | 361231 | 3275 | 99.09% |
| duplicate_event_count | 978 | 3 | 99.69% |
| duplicate_event_ratio | 0.977022977022977 | 0.2727272727272727 | 72.09% |
| request_completed_count | 613 | 0 | 100.00% |
| request_completed_ratio | 0.6123876123876124 | 0.0 | 100.00% |
| structured_lines | 832 | 11 | n/a |
| unstructured_lines | 169 | 0 | 100.00% |

Before top events:

```text
request_completed=613, unstructured=169, client_log=93, inactive_session_registry_cleanup=46, converter_layer_images_cache_hit=10, converter_layer_images_cache_miss=9, converter_glb_scheduled=8, converter_glb_completed=7
```

Unmocked after top events:

```text
log_file_configured=2, image_processor_init=2, image_processor_done=2, worker_pool_started=1, lut_presets_discovered=1, converter_preview_timing=1, converter_generate_timing=1, converter_region_replace_timing=1
```

Business-flow line budget:

| Segment | Previous expectation | Unmocked measured | Result |
| --- | ---: | ---: | --- |
| Preview INFO lines | <= 8 | 3 | PASS |
| Preview + generate + region-replace INFO lines | <= 30 | 7 | PASS |

Overall reduction checklist items still pass against the historical before sample, and the worker-inclusive per-flow line budgets now pass.

## 二阶治理可读性重构

Evidence: `progress\log_audit_unmocked_after.json`.

| Priority | Finding | Evidence |
| --- | --- | --- |
| P0 | True worker per-flow INFO budgets now pass. | Preview INFO `27 -> 3`, target `<= 8`; preview+generate+region-replace measured `7`, target `<= 30`. |
| P1 | `api_server.py` startup did not honor the pre-set `LUMINA_LOG_PATH=logs\unmocked_after.log` path in this audit run. | `setup_file_logging()` selected `logs\lumina_20260427_003445.log`; the audit used that actual file explicitly. |
| P2 | Aggregate governance metrics are materially improved and fully structured. | `total_lines 1001 -> 11`, `total_bytes 361231 -> 3275`, `duplicate_event_count 978 -> 3`, `request_completed_count 613 -> 0`, `unstructured_lines 169 -> 0`. |

Final checklist summary: aggregate 12-item governance remains PASS, and the new unmocked worker line-budget follow-up now passes.

## 12-item reviewer checklist

| # | Requirement | Result | Evidence |
| ---: | --- | --- | --- |
| 1 | Log line count down by at least 60% | PASS | Unmocked business-flow audit: `progress\log_audit_flow_before.json` total_lines=1001; `progress\log_audit_unmocked_after.json` total_lines=11; reduction=98.90%. |
| 2 | Log byte count down by at least 50% | PASS | Unmocked business-flow audit: total_bytes 361231 -> 3275; reduction=99.09%. |
| 3 | Duplicate events down by at least 70% | PASS | Unmocked business-flow audit: duplicate_event_count 978 -> 3; reduction=99.69%. |
| 4 | `request_completed` ratio <= 20% | PASS | Unmocked after audit shows `request_completed_count=0`, `request_completed_ratio=0.0`. Before ratio was 0.6123876123876124. |
| 5 | Default console format is human-readable single-line when `isatty` | PASS | `python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py -v`: `test_human_formatter_outputs_single_readable_line` and `test_configure_structured_logging_auto_uses_tty_to_select_format` passed. |
| 6 | Log files remain JSON Lines | PASS | `python -m pytest tests/test_logger_unit.py tests/test_structured_logging_unit.py -v`: `test_setup_file_logging_does_not_replace_stdout_and_writes_json_lines` and `test_configure_structured_logging_adds_one_json_file_handler` passed. |
| 7 | `utils/` `print(` count is 0 in governed scan | PASS_WITH_NOTE | `rg -n "print\(" utils core api` is the full-range scan. It may report 7 historical legacy `print(` sites that are outside this PR's governance TARGETS and belong to a separate historical cleanup; this PR did not add those prints. |
| 8 | Frontend production console debug calls are 0 | PASS | `rg -n "console\.(log\|debug\|time\|timeLog\|timeEnd)" frontend\src` returned no matches. `rg -n "\[DEBUG\]" frontend\src` only found `devLog.log(...)` source calls and `devLog` tests, not production console calls. |
| 9 | New/changed logs use `get_logger`; no new `print` or bare `logging.getLogger` | PASS | Scoped scans for `print(` and `logging.getLogger` returned no matches. Added-line diff scan `git diff --unified=0 -- api core utils frontend/src \| rg -n "^\+.*(print\(|logging\.getLogger|console\.(log|debug|time|timeLog|timeEnd))"` returned no matches. Infrastructure exceptions are confined to `api\structured_logging.py`'s `get_logger` implementation. |
| 10 | Every current log has `event`; field names follow the shared constitution | PASS | Structured logging tests passed, including extra-field preservation and null-field omission. Governance tests passed. The stale audit sample still contains an old unstructured `[LOG]` line and null-valued fields, so it is not used as evidence for current behavior. |
| 11 | Required pytest gate is green | PASS | Reviewer second-pass pytest evidence is in `progress\reviewer_pytest_full_after.log`. Targeted governance and structured logging gates are green in the gate commands section. |
| 12 | UTF-8/mojibake scan passes | PASS | The required mojibake-marker scan over `api core\pipeline utils frontend\src tests scripts progress` only matched intentional mojibake regression samples in `frontend\src\__tests__\LutColorGrid.mojibake.test.ts`. |

## C-class historical failures

Subagent J has fixed the previous C-class failures. They are retained here as historical baseline context only, not as active blockers.

| Historical test | Category |
| --- | --- |
| `tests/test_vector_engine_fixes_unit.py::TestVisibleStrokeElementsPreserved::test_stroke_only_is_widened_to_printable_width` | vector_engine 算法 |
| `tests/test_vector_engine_fixes_unit.py::TestMergedLutPaletteOverride::test_slot_names_from_palette` | LUT mode |
| `tests/test_vector_engine_fixes_unit.py::TestMergedLutPaletteOverride::test_preview_colors_from_palette` | LUT mode |
| `tests/test_vector_engine_fixes_unit.py::TestNativeBundlePaletteOverride::test_slot_names_override_stale_cmyw_color_mode` | LUT mode |
| `tests/test_vector_engine_fixes_unit.py::TestNativeBundlePaletteOverride::test_preview_colors_resolve_canonical_rgba_when_hex_missing` | LUT mode |
| `tests/test_lut_api_properties.py::TestLutInfoApiRoundTrip::test_info_consistent_with_list` | LUT mode |
| `tests/test_converter_workers_unit.py::TestParameterAnnotations::test_preview_has_expected_param_count` | worker 接口 |
| `tests/test_converter_workers_unit.py::TestParameterAnnotations::test_preview_param_names` | worker 接口 |

## Gate commands and results

```powershell
python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py -v
```

Result: PASS, 9 passed. Warning: pytest could not write `.pytest_cache` due `WinError 5`, but test execution succeeded.

```powershell
python -m pytest tests/test_logger_unit.py tests/test_structured_logging_unit.py -v
```

Result: PASS, 10 passed. Warning: pytest could not write `.pytest_cache` due `WinError 5`, but test execution succeeded.

```powershell
rg -n "print\(" utils core api
```

Result: PASS_WITH_NOTE. Full-range scanning may show 7 historical legacy `print(` sites. They are outside this PR's governance TARGETS, belong to a separate historical cleanup item, and were not introduced by this PR.

```powershell
rg -n "logging\.getLogger" utils core\pipeline api\app.py api\routers\converter
```

Result: PASS, no matches.

```powershell
rg -n "console\.(log|debug|time|timeLog|timeEnd)" frontend\src
```

Result: PASS, no matches.

```powershell
rg -n "\[DEBUG\]" frontend\src
```

Result: PASS_WITH_NOTE. Matches are `devLog.log("[DEBUG] ...")` calls in `frontend\src\stores\converter\store.ts` and `frontend\src\utils\__tests__\devLog.test.ts`; no production `console.*` debug calls remain.

```powershell
rg -n "<required mojibake marker pattern>" api core\pipeline utils frontend\src tests scripts progress
```

Result: PASS_WITH_NOTE. Matches are intentional mojibake test fixtures only:

```text
frontend\src\__tests__\LutColorGrid.mojibake.test.ts:24-27
```

```powershell
git diff --check
```

Result: PASS_WITH_NOTE. Exit code 0; only CRLF normalization warnings were printed for existing changed files.

## Announcement

`frontend/src/data/announcements.ts` was read with explicit UTF-8 handling. I did not update it.

Reason: this logging-governance work changes developer/operator observability and log formatting behavior. It does not introduce an in-app user-visible workflow, feature, UX fix, or stability fix that belongs in the first-launch announcement dialog under the repository announcement rules.

## Boundary

Files modified by this update:

- `progress/log_audit_diff.md` (updated, 12890 bytes after edit)
- `progress/log_audit_unmocked_after.json` (regenerated, 1377 bytes)

`git status --short progress` reports `?? progress/` because the progress directory is currently untracked in this workspace; no tracked business-code diff stat is produced for these files.

No `api/`, `core/`, `utils/`, `frontend/`, `tests/`, or `scripts/` files were modified by this update. No stage, commit, push, reset, or revert was performed.
