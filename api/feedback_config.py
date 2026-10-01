"""Environment-driven configuration for the feedback / bug-report subsystem.

反馈与 Bug 报告子系统的环境变量配置。

This module centralizes the four environment variables that tune the new
reproducible-bug-report pipeline so the rest of the spec has a single place to
import limits and timeouts from. Accessor functions re-read ``os.environ`` on
every call so tests can override values via ``monkeypatch.setenv`` without
having to reload modules or reset cached state.

本模块集中解析可重现 Bug 报告流水线的四个环境变量，让其他代码只在一处
读取上限与超时配置。访问函数每次都会重新读取 ``os.environ``，因此测试
可以直接通过 ``monkeypatch.setenv`` 覆盖值，无需重新加载模块或重置缓存。

Default values (默认值):

* ``LUMINA_FEEDBACK_MAX_LOCAL_TICKET_MB`` — 1024 MB (1 GiB), total on-disk
  budget for one ticket directory. **Reserved / parsed only**: the automatic
  eviction logic that would trim large artifacts when this budget is exceeded
  has not been implemented yet. The value is accessible for future use.
  单个工单目录在触发裁剪前的磁盘上限（兆字节）。**当前仅解析，未实际
  执行裁剪**：超限自动裁剪逻辑尚未实现，值仅供未来使用。
* ``LUMINA_FEEDBACK_MATERIALS_BUNDLE_TIMEOUT_S`` — 30 seconds, hard wall-clock
  budget for packing the ``materials/`` bundle zip during ticket assembly.
  工单装配阶段打包 ``materials/`` zip 的超时（秒）。
* ``LUMINA_FEEDBACK_TICKET_TTL_DAYS`` — 30 days, retention for the bulky
  attachments of a ticket (original image / final artifact / LUT / materials
  zip / screenshot) before they are purged by the startup cleanup task.
  工单大附件的保留天数。
* ``LUMINA_FEEDBACK_TICKET_JSON_TTL_DAYS`` — 365 days, retention for the
  small ``ticket.json`` / ``index.md`` / ``summary.txt`` files that stay
  searchable after the bulky attachments are dropped. **Reserved / parsed
  only**: the cleanup logic that would purge these files after the TTL has
  not been implemented yet. The value is accessible for future use.
  工单 JSON 等小文件的保留天数。**当前仅解析，未实际执行清理**：到期
  清理逻辑尚未实现，值仅供未来使用。

Parsing rules (解析规则):

All four accessors delegate to :func:`_parse_nonnegative_int`. If an
environment variable is present but not a valid integer, or is negative (or
zero when the caller requires strict positivity, e.g. timeouts), the helper
emits a structured WARNING log and falls back to the documented default
instead of raising. This keeps misconfigured deployments running with safe
defaults while still surfacing the problem via the standard log pipeline.

四个访问函数统一委托给 :func:`_parse_nonnegative_int` 解析。若环境变量
存在但不是合法整数，或者取到了负值（以及超时等字段不允许的 0），辅助
函数会记录结构化 WARNING 日志，然后回退到对应的默认值，而不再抛出
异常。这样即便部署侧配置错误，系统也能以安全默认值继续运行，同时
通过标准日志通道可观察到问题。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from api.structured_logging import get_logger

__all__ = [
    "ENV_MAX_LOCAL_TICKET_MB",
    "ENV_MATERIALS_BUNDLE_TIMEOUT_S",
    "ENV_TICKET_TTL_DAYS",
    "ENV_TICKET_JSON_TTL_DAYS",
    "DEFAULT_MAX_LOCAL_TICKET_MB",
    "DEFAULT_MATERIALS_BUNDLE_TIMEOUT_S",
    "DEFAULT_TICKET_TTL_DAYS",
    "DEFAULT_TICKET_JSON_TTL_DAYS",
    "FeedbackConfig",
    "max_local_ticket_bytes",
    "materials_bundle_timeout_s",
    "ticket_attachment_ttl_days",
    "ticket_json_ttl_days",
    "load_feedback_config",
]


log = get_logger(__name__)
"""Module-level structured logger used by :func:`_parse_nonnegative_int`.

模块级结构化 logger，供 :func:`_parse_nonnegative_int` 在回退到默认值时
发出 WARNING 记录。
"""


# --- Environment variable names -------------------------------------------
# 环境变量名称常量，便于测试与其他模块通过符号引用，避免字符串散落。

ENV_MAX_LOCAL_TICKET_MB: str = "LUMINA_FEEDBACK_MAX_LOCAL_TICKET_MB"
"""Env var: local per-ticket total disk budget in megabytes.

单个工单目录本地磁盘上限（兆字节）的环境变量名。
"""

ENV_MATERIALS_BUNDLE_TIMEOUT_S: str = "LUMINA_FEEDBACK_MATERIALS_BUNDLE_TIMEOUT_S"
"""Env var: materials bundle packing timeout in seconds.

耗材档案打包超时（秒）的环境变量名。
"""

ENV_TICKET_TTL_DAYS: str = "LUMINA_FEEDBACK_TICKET_TTL_DAYS"
"""Env var: retention for ticket bulky attachments in days.

工单大附件保留天数的环境变量名。
"""

ENV_TICKET_JSON_TTL_DAYS: str = "LUMINA_FEEDBACK_TICKET_JSON_TTL_DAYS"
"""Env var: retention for ticket JSON / index / summary in days.

工单 JSON / 索引 / 摘要保留天数的环境变量名。
"""


# --- Default values --------------------------------------------------------
# 默认值常量，便于单测在不 set env 的场景直接引用同一份数字。

DEFAULT_MAX_LOCAL_TICKET_MB: int = 1024
"""Default: 1024 MB (1 GiB) per ticket directory.

默认值：单工单目录 1024 MB（1 GiB）。
"""

DEFAULT_MATERIALS_BUNDLE_TIMEOUT_S: int = 30
"""Default: 30 seconds to pack the materials bundle zip.

默认值：耗材档案 zip 打包 30 秒超时。
"""

DEFAULT_TICKET_TTL_DAYS: int = 30
"""Default: 30 days retention for bulky ticket attachments.

默认值：工单大附件保留 30 天。
"""

DEFAULT_TICKET_JSON_TTL_DAYS: int = 365
"""Default: 365 days retention for small ticket metadata files.

默认值：工单 JSON 等小文件保留 365 天。
"""


# Maximum length of the raw env-var value we are willing to echo back in
# WARNING logs. Long strings (e.g. an accidentally pasted file blob) would
# otherwise bloat the JSON lines log and hide the actual issue.
# 记录在 WARNING 中的原始 env 字符串截断长度；避免超长值把结构化日志
# 撑大，掩盖真正的问题。
_RAW_VALUE_LOG_LIMIT: int = 80


def _truncate_raw(value: str) -> str:
    """Return ``value`` shortened to :data:`_RAW_VALUE_LOG_LIMIT` chars.

    Long user-supplied env strings are truncated with an explicit ``...``
    suffix so the structured log stays compact and the fact that we truncated
    is obvious to an operator skimming the logs.

    将超长的原始 env 字符串截断到 :data:`_RAW_VALUE_LOG_LIMIT` 字符并追加
    ``...``，保证结构化日志简洁，也让运维一眼看出发生了截断。

    Args:
        value: Raw environment variable string.

    Returns:
        str: Possibly truncated representation safe for logging.
    """
    if len(value) <= _RAW_VALUE_LOG_LIMIT:
        return value
    return value[:_RAW_VALUE_LOG_LIMIT] + "..."


def _parse_nonnegative_int(
    env_name: str,
    default: int,
    *,
    allow_zero: bool = True,
    purpose: str = "",
) -> int:
    """Parse an int env var, falling back to default on invalid/negative.

    解析整数类型的环境变量，遇到非法或负数时回退到默认值。

    The helper is the single source of truth for the feedback-config parsing
    rules: invalid ints log a WARNING with event ``feedback_config_invalid_env``
    and fall back to ``default``; negative ints (or zero when
    ``allow_zero=False``) log WARNING ``feedback_config_negative_env`` and
    also fall back. Zero is allowed by default because size / TTL fields
    accept 0 as "disabled" semantics for now; callers that need strict
    positivity (e.g. timeouts) pass ``allow_zero=False``.

    该辅助函数是 feedback 配置解析规则的唯一入口：非法整数会记录
    ``feedback_config_invalid_env`` 事件并回退到 ``default``；负数（以及
    ``allow_zero=False`` 时的 0）会记录 ``feedback_config_negative_env``
    事件并同样回退。大小 / TTL 字段当前把 0 视为"禁用"语义，因此默认
    ``allow_zero=True``；对于必须严格为正的字段（例如超时），调用方传入
    ``allow_zero=False`` 即可。

    Args:
        env_name: Name of the environment variable to read.
            (要读取的环境变量名)
        default: Fallback integer used when the env var is missing, invalid,
            or violates the non-negativity contract.
            (环境变量缺失、非法或违反非负约束时使用的回退整数)
        allow_zero: When ``True`` (the default) zero is a legal value; when
            ``False`` zero is rejected alongside negatives.
            (为 ``True`` 时允许 0；为 ``False`` 时把 0 与负数一并拒绝)
        purpose: Optional free-text description of what the setting controls
            (e.g. ``"materials bundle timeout"``). Surfaced as the ``purpose``
            field in the WARNING log to speed up triage.
            (可选的用途描述，会作为 WARNING 日志的 ``purpose`` 字段输出，
            帮助运维快速定位)

    Returns:
        int: The parsed value if present and valid, otherwise ``default``.
    """
    raw = os.environ.get(env_name)
    if raw is None:
        return default

    try:
        parsed = int(raw)
    except (TypeError, ValueError) as exc:
        log.warning(
            "Invalid integer for %s; falling back to default %d.",
            env_name,
            default,
            extra={
                "event": "feedback_config_invalid_env",
                "env_name": env_name,
                "raw_value": _truncate_raw(raw),
                "default_value": default,
                "error_type": "ValueError",
                "error_message": str(exc) or f"cannot parse {raw!r} as int",
                "purpose": purpose,
            },
        )
        return default

    if parsed < 0:
        log.warning(
            "Negative value for %s; falling back to default %d.",
            env_name,
            default,
            extra={
                "event": "feedback_config_negative_env",
                "env_name": env_name,
                "raw_value": _truncate_raw(raw),
                "default_value": default,
                "error_type": "NegativeValue",
                "error_message": f"value {parsed} is negative; must be >= 0",
                "purpose": purpose,
            },
        )
        return default

    if parsed == 0 and not allow_zero:
        log.warning(
            "Zero is not allowed for %s; falling back to default %d.",
            env_name,
            default,
            extra={
                "event": "feedback_config_negative_env",
                "env_name": env_name,
                "raw_value": _truncate_raw(raw),
                "default_value": default,
                "error_type": "ZeroDisallowed",
                "error_message": f"value 0 is not allowed for {env_name}; must be > 0",
                "purpose": purpose,
            },
        )
        return default

    return parsed


@dataclass(frozen=True)
class FeedbackConfig:
    """Immutable snapshot of all feedback-subsystem environment values.

    反馈子系统所有环境变量值的不可变快照。

    Downstream modules that prefer a plain data object over calling the
    individual accessors can take a snapshot via :func:`load_feedback_config`
    at a well-defined moment (e.g. the start of ticket assembly) and carry it
    through the rest of the pipeline. Because the class is ``frozen``, the
    snapshot cannot accidentally drift once captured.

    希望拿到纯数据对象而不是逐个调用访问函数的下游模块，可以在确定的时机
    （例如工单装配开始时）通过 :func:`load_feedback_config` 抓取一份快照，
    再传递给后续流程。由于该类是 ``frozen`` 的，快照一旦生成就不会被
    意外修改。

    Attributes:
        max_local_ticket_bytes: Per-ticket on-disk budget in bytes.
            (单工单磁盘上限，字节)
        materials_bundle_timeout_s: Materials zip packing timeout in seconds.
            (耗材档案打包超时，秒)
        ticket_attachment_ttl_days: Bulky-attachment retention in days.
            (大附件保留天数)
        ticket_json_ttl_days: Small-file retention in days.
            (小文件保留天数)
    """

    max_local_ticket_bytes: int
    materials_bundle_timeout_s: int
    ticket_attachment_ttl_days: int
    ticket_json_ttl_days: int


def max_local_ticket_bytes() -> int:
    """Return the per-ticket on-disk budget in bytes.

    返回单个工单目录的磁盘上限（字节）。

    **Reserved / parsed only**: the automatic eviction logic that would trim
    large artifacts when this budget is exceeded has not been implemented yet.
    The value is accessible for future use.
    **当前仅解析，未实际执行裁剪**：超限自动裁剪逻辑尚未实现。

    Reads :data:`ENV_MAX_LOCAL_TICKET_MB` as an integer number of megabytes
    and converts to bytes via ``value * 1024 * 1024``. The default is
    :data:`DEFAULT_MAX_LOCAL_TICKET_MB` (1024 MB), which is effectively 1 GiB
    (``1024 * 1024 * 1024 = 1_073_741_824`` bytes) — the extra factor of 1024
    comes from the MB → bytes conversion, not from the constant itself.
    Invalid or negative values silently fall back to the default with a
    WARNING log (see :func:`_parse_nonnegative_int`).

    以兆字节为单位读取环境变量 :data:`ENV_MAX_LOCAL_TICKET_MB`，通过
    ``value * 1024 * 1024`` 转换为字节。默认 :data:`DEFAULT_MAX_LOCAL_TICKET_MB`
    为 1024 MB，等价于 1 GiB（``1024 * 1024 * 1024 = 1_073_741_824`` 字节）；
    最后一次 ``* 1024`` 来自 MB → 字节换算，而不是常量本身。非法值或负数
    会静默回退到默认值，并通过 :func:`_parse_nonnegative_int` 记录 WARNING
    日志。

    Returns:
        int: Maximum total size for one ticket directory, in bytes.
    """
    mb = _parse_nonnegative_int(
        ENV_MAX_LOCAL_TICKET_MB,
        DEFAULT_MAX_LOCAL_TICKET_MB,
        allow_zero=True,
        purpose="per-ticket on-disk budget (MB)",
    )
    return mb * 1024 * 1024


def materials_bundle_timeout_s() -> int:
    """Return the materials-bundle packing timeout in seconds.

    返回耗材档案打包超时（秒）。

    Reads :data:`ENV_MATERIALS_BUNDLE_TIMEOUT_S` as an integer number of
    seconds. Defaults to :data:`DEFAULT_MATERIALS_BUNDLE_TIMEOUT_S` (30 s)
    when the env var is unset. Zero is disallowed because a timeout of zero
    would make the packing step fail instantly; invalid, negative, or zero
    values silently fall back to the default with a WARNING log (see
    :func:`_parse_nonnegative_int`).

    以秒为单位读取环境变量 :data:`ENV_MATERIALS_BUNDLE_TIMEOUT_S`。未
    设置时回退到 :data:`DEFAULT_MATERIALS_BUNDLE_TIMEOUT_S`（30 秒）。超时
    为 0 会让打包步骤立刻失败，因此禁用 0；非法值、负数或 0 都会静默
    回退到默认值，并通过 :func:`_parse_nonnegative_int` 记录 WARNING 日志。

    Returns:
        int: Packing timeout in seconds (strictly positive).
    """
    return _parse_nonnegative_int(
        ENV_MATERIALS_BUNDLE_TIMEOUT_S,
        DEFAULT_MATERIALS_BUNDLE_TIMEOUT_S,
        allow_zero=False,
        purpose="materials bundle timeout (s)",
    )


def ticket_attachment_ttl_days() -> int:
    """Return the bulky-attachment retention window in days.

    返回工单大附件的保留天数。

    Reads :data:`ENV_TICKET_TTL_DAYS` as an integer number of days. Defaults
    to :data:`DEFAULT_TICKET_TTL_DAYS` (30 days) when the env var is unset.
    Applies to the original image, final artifact, LUT file, materials zip,
    and user screenshot inside a ticket directory; the small metadata files
    (``ticket.json`` / ``index.md`` / ``summary.txt``) follow the separate
    :func:`ticket_json_ttl_days` budget. Invalid or negative values silently
    fall back to the default with a WARNING log (see
    :func:`_parse_nonnegative_int`).

    以天为单位读取环境变量 :data:`ENV_TICKET_TTL_DAYS`。未设置时回退到
    :data:`DEFAULT_TICKET_TTL_DAYS`（30 天）。此值适用于工单目录下的原图、
    最终产物、LUT 文件、耗材 zip 以及用户截图；而工单 JSON / 索引 / 摘要
    等小文件使用 :func:`ticket_json_ttl_days` 单独的预算。非法值或负数会
    静默回退到默认值，并通过 :func:`_parse_nonnegative_int` 记录 WARNING
    日志。

    Returns:
        int: Retention window in days.
    """
    return _parse_nonnegative_int(
        ENV_TICKET_TTL_DAYS,
        DEFAULT_TICKET_TTL_DAYS,
        allow_zero=True,
        purpose="ticket bulky attachment TTL (days)",
    )


def ticket_json_ttl_days() -> int:
    """Return the small-file retention window in days.

    返回工单 JSON / 索引 / 摘要的保留天数。

    **Reserved / parsed only**: the cleanup logic that would purge these
    files after the TTL has not been implemented yet. The value is accessible
    for future use.
    **当前仅解析，未实际执行清理**：到期清理逻辑尚未实现。

    Reads :data:`ENV_TICKET_JSON_TTL_DAYS` as an integer number of days.
    Defaults to :data:`DEFAULT_TICKET_JSON_TTL_DAYS` (365 days) when the env
    var is unset. These files are small and stay searchable long after the
    bulky attachments have been purged. Invalid or negative values silently
    fall back to the default with a WARNING log (see
    :func:`_parse_nonnegative_int`).

    以天为单位读取环境变量 :data:`ENV_TICKET_JSON_TTL_DAYS`。未设置时回退到
    :data:`DEFAULT_TICKET_JSON_TTL_DAYS`（365 天）。这些文件体积小，即便在
    大附件被清理后仍可长期检索。非法值或负数会静默回退到默认值，并通过
    :func:`_parse_nonnegative_int` 记录 WARNING 日志。

    Returns:
        int: Retention window in days.
    """
    return _parse_nonnegative_int(
        ENV_TICKET_JSON_TTL_DAYS,
        DEFAULT_TICKET_JSON_TTL_DAYS,
        allow_zero=True,
        purpose="ticket JSON / index / summary TTL (days)",
    )


def load_feedback_config() -> FeedbackConfig:
    """Snapshot all four feedback-subsystem values at the current moment.

    抓取反馈子系统所有四个值的当前快照。

    Calls each of the individual accessors (:func:`max_local_ticket_bytes`, :func:`materials_bundle_timeout_s`,
    :func:`ticket_attachment_ttl_days`, :func:`ticket_json_ttl_days`) once and
    packages the results into a :class:`FeedbackConfig`. Because the accessors
    each re-read ``os.environ``, the snapshot reflects environment state at
    call time. After the snapshot is returned the dataclass is immutable.
    Invalid or negative env values silently fall back to defaults with a
    WARNING log (see :func:`_parse_nonnegative_int`).

    依次调用四个访问函数
    （:func:`max_local_ticket_bytes`、
    :func:`materials_bundle_timeout_s`、:func:`ticket_attachment_ttl_days`、
    :func:`ticket_json_ttl_days`），把结果封装成
    :class:`FeedbackConfig`。由于访问函数每次都会重新读取 ``os.environ``，
    快照反映的是调用当下的环境状态；返回后数据类不可再修改。非法值或
    负数会静默回退到默认值，并通过 :func:`_parse_nonnegative_int` 记录
    WARNING 日志。

    Returns:
        FeedbackConfig: Immutable snapshot with byte-valued size fields and
        day/second-valued duration fields.
    """
    return FeedbackConfig(
        max_local_ticket_bytes=max_local_ticket_bytes(),
        materials_bundle_timeout_s=materials_bundle_timeout_s(),
        ticket_attachment_ttl_days=ticket_attachment_ttl_days(),
        ticket_json_ttl_days=ticket_json_ttl_days(),
    )
