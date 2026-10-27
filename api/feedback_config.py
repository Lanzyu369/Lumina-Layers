"""Runtime settings for feedback attachment cleanup and materials packing.

反馈附件清理与耗材打包的运行时配置。
"""

from __future__ import annotations

import os

from api.structured_logging import get_logger

__all__ = [
    "ENV_MATERIALS_BUNDLE_TIMEOUT_S",
    "ENV_TICKET_TTL_DAYS",
    "DEFAULT_MATERIALS_BUNDLE_TIMEOUT_S",
    "DEFAULT_TICKET_TTL_DAYS",
    "materials_bundle_timeout_s",
    "ticket_attachment_ttl_days",
]

log = get_logger(__name__)

ENV_MATERIALS_BUNDLE_TIMEOUT_S = "LUMINA_FEEDBACK_MATERIALS_BUNDLE_TIMEOUT_S"
ENV_TICKET_TTL_DAYS = "LUMINA_FEEDBACK_TICKET_TTL_DAYS"
DEFAULT_MATERIALS_BUNDLE_TIMEOUT_S = 0
DEFAULT_TICKET_TTL_DAYS = 30


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
    also fall back. Zero is allowed by default because TTL fields
    accept 0 to disable attachment cleanup; callers that need strict
    positivity (e.g. timeouts) pass ``allow_zero=False``.

    该辅助函数是 feedback 配置解析规则的唯一入口：非法整数会记录
    ``feedback_config_invalid_env`` 事件并回退到 ``default``；负数（以及
    ``allow_zero=False`` 时的 0）会记录 ``feedback_config_negative_env``
    事件并同样回退。TTL 字段把 0 视为禁用附件清理，因此默认
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


def materials_bundle_timeout_s() -> int:
    """Return the materials ZIP packing timeout in seconds.

    Invalid or negative values use the default with a warning; zero disables the timeout.
    返回耗材 ZIP 打包超时秒数；零表示不限制耗时，非法值或负数回退并记录警告。

    Returns:
        int: Packing timeout, re-read from the environment each call; zero disables it.
            每次读取环境变量所得的非负整数超时秒数。
    """
    return _parse_nonnegative_int(
        ENV_MATERIALS_BUNDLE_TIMEOUT_S,
        DEFAULT_MATERIALS_BUNDLE_TIMEOUT_S,
        allow_zero=True,
        purpose="materials bundle timeout (s)",
    )


def ticket_attachment_ttl_days() -> int:
    """Return bulky-attachment retention in days; zero disables cleanup.

    Invalid or negative values use the 30-day default with a warning.
    Ticket JSON, index and summary remain searchable after attachment cleanup.
    返回大附件保留天数；零禁用清理。非法值或负数回退到 30 天并记录警告。
    工单 JSON、索引和摘要保持可检索，不随附件清理删除。

    Returns:
        int: Nonnegative retention window, re-read from the environment.
            每次读取环境变量所得的非负保留天数。
    """
    return _parse_nonnegative_int(
        ENV_TICKET_TTL_DAYS,
        DEFAULT_TICKET_TTL_DAYS,
        allow_zero=True,
        purpose="ticket bulky attachment TTL (days)",
    )
