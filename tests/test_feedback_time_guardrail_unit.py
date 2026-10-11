"""Structured server log timestamps remain UTC regardless of ticket time zones."""

from __future__ import annotations

import io
import json
import logging

from api.structured_logging import _JsonFormatter, get_logger




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
