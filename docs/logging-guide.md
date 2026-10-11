# Lumina Studio Logging Guide / 日志使用指南

Logs support diagnosis of startup, conversion, editing, export, and optional-feature failures. They do not impose a line budget or require an event inventory, reviewer baseline, or governance round.

## Files and configuration

`get_logger(name)` obtains a namespaced logger without configuring the process. The API entry point uses `setup_file_logging()`; standalone tools initialize logging in `main()`.

File logs are UTF-8 JSON Lines. Each record carries a UTC timestamp, level, event, module, and message. Request/session paths add `request_id` and `session_id` where available; failures include useful context such as `error_type`, `error_message`, `path`, or `dependency`. Avoid putting full images, arrays, or large payloads into logs.

| Variable | Purpose |
| --- | --- |
| `LUMINA_LOG_PATH` | Explicit file path; inherited by child processes |
| `LUMINA_LOG_DIR` | Directory for automatically named log files |
| `LUMINA_LOG_LEVEL` | Minimum level; normally `INFO`, use `DEBUG` for diagnosis |
| `LUMINA_LOG_FORMAT` | Console output: `auto`, `human`, or `json`; file output remains JSON |
| `LUMINA_LOG_INIT_BY_PARENT=1` | Children attach to the shared log without repeating initialization |

The default file is `logs/lumina_<timestamp>.log`. If that directory is not writable, logging falls back to the system temporary directory. Console output uses human-readable lines in a terminal and JSON when piped.

Use `from api.structured_logging import get_logger` on API/worker paths. Keep routine progress at DEBUG. Log meaningful completion, duration, and failures with searchable event names. Raise core/domain errors in core code and translate them through `api.errors.to_http_exception()` at API boundaries. Broad catches belong around external-library calls or explicit application boundaries, with a useful diagnostic or a defined fallback.

## Read and diagnose

```bash
# Follow the current log.
tail -f logs/lumina_*.log

# Summarize the latest file.
python scripts/audit_logs.py --logs logs/ --latest 1

# Follow one session.
jq -c 'select(.session_id=="<session_id>")' logs/lumina_<timestamp>.log

# Find actual errors.
jq -c 'select(.level=="ERROR")' logs/lumina_<timestamp>.log

# Inspect generation durations.
jq -c 'select(.event=="converter_generate_timing")' logs/lumina_<timestamp>.log
```

For a stalled generation, follow its request/session through generation initialization, timings, and export/preview results. A failed optional preview should include the dependency or path and the fallback taken. For slow conversion, use the recorded stage timings and the existing profiling tools; log line count is not a performance measurement.

## Verify relevant behavior

```bash
python -m pytest tests/test_api_errors_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -q
python scripts/log_quality_check.py --mode fast
python scripts/log_quality_check.py --mode full
```

Fast mode uses an in-process API workflow with lightweight worker replacements. Full mode starts the real backend and exercises the workflow, then stops the processes it started. It complements functional regression tests.

`--workflow` selects an existing workflow and `--output` chooses the report path. For example:

```bash
python scripts/log_quality_check.py --mode fast --workflow startup,lut_list,lut_colors,preview,generate,replace_bw
python scripts/log_quality_check.py --mode full --output .scratch/log-quality.json
```

The report records levels, events, sizes, and per-request counts for diagnosis. It checks JSON formatting, useful warning/error fields, logger initialization, and expected events for the workflow being exercised. INFO counts have no pass/fail cap. There are no frozen event-count baselines or source event whitelists to update.

Exit codes: `0` passed, `1` a log/workflow check failed, `2` setup or script failure. Inspect the reported field or workflow failure and rerun the affected check. Adding a feature does not require a new logging workflow unless existing checks leave a meaningful gap.

## 中文说明

日志用于排查启动、转换、编辑、导出和可选功能失败。文件保存在 `logs/`，使用 UTF-8 JSON Lines 和 UTC 时间；控制台按终端环境选择易读文本或 JSON。

用 `request_id`、`session_id` 关联一次操作，关注失败原因、路径、依赖和实际耗时。常规进度放 DEBUG，保留有用的完成和错误信息。子进程继承 `LUMINA_LOG_PATH`、`LUMINA_LOG_INIT_BY_PARENT=1`，不要重复初始化共享日志。

上面的 fast/full 命令验证实际日志输出和相应操作。full 会启动并收尾真实后端，不替代功能回归。报告中的条数只是诊断信息，没有 INFO 预算、事件源码白名单、冻结基线或治理回合。新增功能只需要按影响更新相关行为验证。
