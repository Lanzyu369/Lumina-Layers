"""Guardrail tests: Beijing time must NOT leak into structured server logs.

确保 ``api.structured_logging`` 继续使用 UTC ISO 时间戳，不被 feedback 工单的
北京时间工具污染。日志治理工具（``scripts/log_quality_check.py``、
``scripts/audit_logs.py``、``progress/log_audit_*_reviewer.json`` 冻结基线）
依赖 UTC 时间戳；把北京时间写进结构化日志会让这些工具全部失效。

The two tests below encode two hard invariants:

1. ``api.structured_logging`` must not import anything from
   ``api.feedback_time`` — feedback-side Beijing-time helpers stay scoped to
   ticket id generation and ``received_at_cst`` fields.
2. A real log record emitted through the public
   ``api.structured_logging.get_logger`` API must serialise its ``timestamp``
   field with the UTC ``+00:00`` offset, never ``+08:00``.
"""

from __future__ import annotations

import inspect
import io
import json
import logging

import api.structured_logging as structured_logging
from api.structured_logging import _JsonFormatter, get_logger


def test_structured_logging_does_not_import_feedback_time() -> None:
    """``api.structured_logging`` source must contain no ``feedback_time`` reference.

    Test A from the guardrail plan. We deliberately check the raw source string
    rather than ``sys.modules`` because a contributor could later add a lazy /
    function-scoped import; catching it textually is both simpler and stricter.
    """
    src = inspect.getsource(structured_logging)
    assert "feedback_time" not in src, (
        "api/structured_logging.py must not reference api.feedback_time; "
        "Beijing-time helpers are scoped to feedback tickets only. See "
        "tests/test_feedback_time_guardrail_unit.py docstring for rationale."
    )


def test_structured_log_timestamp_is_utc_iso_not_beijing() -> None:
    """A real log emitted via ``get_logger`` serialises ``timestamp`` with ``+00:00``.

    Test B from the guardrail plan. Rather than poke at the JsonFormatter in
    isolation (which a careless refactor could bypass), we:

    1. Grab the public ``lumina.test`` logger through ``get_logger``.
    2. Attach a fresh :class:`_JsonFormatter`-backed stream handler pointing at
       an in-memory :class:`io.StringIO` buffer, so we read the formatter's real
       output without touching stdout, disk, or process env.
    3. Emit one INFO record.
    4. Detach the handler and assert the captured line's ``timestamp`` ends with
       ``+00:00`` (UTC) and never with ``+08:00`` (Beijing).
    """
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(_JsonFormatter())
    handler.setLevel(logging.INFO)

    logger = get_logger("lumina.test")
    # get_logger returns a namespaced logger under the configured ``lumina``
    # family; attaching our own handler here captures output without racing
    # against the real stdout/file handlers already installed.
    logger.addHandler(handler)
    try:
        logger.info(
            "guardrail probe",
            extra={"event": "feedback_time_guardrail_probe"},
        )
    finally:
        logger.removeHandler(handler)
        handler.close()

    output = buffer.getvalue().strip()
    assert output, "expected one JSON log line from the guardrail probe"

    payload = json.loads(output.splitlines()[-1])
    timestamp = payload.get("timestamp")
    assert isinstance(timestamp, str) and timestamp, (
        f"log payload missing 'timestamp' field: {payload!r}"
    )
    assert timestamp.endswith("+00:00"), (
        "structured log timestamp must stay on UTC ISO (+00:00); got "
        f"{timestamp!r}. If you moved the logger to Beijing time you have "
        "broken scripts/log_quality_check.py, scripts/audit_logs.py, and the "
        "frozen baselines in progress/log_audit_*_reviewer.json."
    )
    assert "+08:00" not in timestamp, (
        f"structured log timestamp leaked Beijing offset: {timestamp!r}"
    )
