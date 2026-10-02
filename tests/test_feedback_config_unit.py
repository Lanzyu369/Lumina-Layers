"""Unit tests for ``api.feedback_config`` fallback behaviour.

Covers the four env-driven knobs that tune the reproducible-bug-report
pipeline: default snapshot, valid overrides, invalid / negative / zero
handling, raw-value truncation in the WARNING log, and the
:class:`FeedbackConfig` frozen contract.

Logger propagation note: ``api.structured_logging.configure_structured_logging``
sets ``logger.propagate = False`` on the ``lumina`` logger family so records
don't bubble up to root. pytest's ``caplog`` fixture attaches to root, so we
flip propagate back on for the duration of each test that needs to observe
WARNINGs from ``lumina.api.feedback_config``, then restore the original
setting in the fixture teardown.
"""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError

import pytest

from api.feedback_config import (
    DEFAULT_MATERIALS_BUNDLE_TIMEOUT_S,
    DEFAULT_MAX_LOCAL_TICKET_MB,
    DEFAULT_TICKET_JSON_TTL_DAYS,
    DEFAULT_TICKET_TTL_DAYS,
    ENV_MATERIALS_BUNDLE_TIMEOUT_S,
    ENV_MAX_LOCAL_TICKET_MB,
    ENV_TICKET_JSON_TTL_DAYS,
    ENV_TICKET_TTL_DAYS,
    FeedbackConfig,
    load_feedback_config,
    materials_bundle_timeout_s,
    max_local_ticket_bytes,
    ticket_attachment_ttl_days,
    ticket_json_ttl_days,
)

FEEDBACK_CONFIG_LOGGER_NAME = "lumina.api.feedback_config"


# --- Fixtures --------------------------------------------------------------


@pytest.fixture
def feedback_config_caplog(caplog):
    """Route ``lumina.api.feedback_config`` WARNINGs into ``caplog``.

    The ``lumina`` logger family is configured with ``propagate=False`` so
    structured records don't leak into unrelated handlers. pytest's ``caplog``
    is attached to the root logger, so we temporarily flip propagation on for
    the duration of the test and restore the original flag afterwards.
    """
    lumina_logger = logging.getLogger("lumina")
    original_propagate = lumina_logger.propagate
    lumina_logger.propagate = True
    caplog.set_level(logging.WARNING, logger=FEEDBACK_CONFIG_LOGGER_NAME)
    try:
        yield caplog
    finally:
        lumina_logger.propagate = original_propagate


def _clear_feedback_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every feedback-config env var so the test starts from defaults."""
    for env in (
            ENV_MAX_LOCAL_TICKET_MB,
        ENV_MATERIALS_BUNDLE_TIMEOUT_S,
        ENV_TICKET_TTL_DAYS,
        ENV_TICKET_JSON_TTL_DAYS,
    ):
        monkeypatch.delenv(env, raising=False)


def _feedback_warnings(caplog) -> list[logging.LogRecord]:
    """Return WARNING-level records emitted by ``api.feedback_config``."""
    return [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == FEEDBACK_CONFIG_LOGGER_NAME
    ]


# --- Tests -----------------------------------------------------------------


def test_defaults_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no env vars set, the snapshot exactly matches the documented defaults.

    Byte-valued fields use ``MB * 1024 * 1024`` conversion:
    1024 MB → 1_073_741_824 bytes (1 GiB).
    """
    _clear_feedback_env(monkeypatch)

    snap = load_feedback_config()

    assert snap.max_local_ticket_bytes == 1_073_741_824
    assert snap.materials_bundle_timeout_s == 30
    assert snap.ticket_attachment_ttl_days == 30
    assert snap.ticket_json_ttl_days == 365


def test_valid_override_for_each_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid positive overrides flow through accessors and the snapshot."""
    monkeypatch.setenv(ENV_MAX_LOCAL_TICKET_MB, "2048")
    monkeypatch.setenv(ENV_MATERIALS_BUNDLE_TIMEOUT_S, "60")
    monkeypatch.setenv(ENV_TICKET_TTL_DAYS, "60")
    monkeypatch.setenv(ENV_TICKET_JSON_TTL_DAYS, "730")

    # Individual accessors honour the MB → bytes conversion where applicable.
    assert max_local_ticket_bytes() == 2048 * 1024 * 1024
    assert materials_bundle_timeout_s() == 60
    assert ticket_attachment_ttl_days() == 60
    assert ticket_json_ttl_days() == 730

    # Snapshot reflects the same values in one shot.
    snap = load_feedback_config()
    assert snap.max_local_ticket_bytes == 2048 * 1024 * 1024
    assert snap.materials_bundle_timeout_s == 60
    assert snap.ticket_attachment_ttl_days == 60
    assert snap.ticket_json_ttl_days == 730


def test_invalid_string_falls_back_and_logs_warning(
    monkeypatch: pytest.MonkeyPatch, feedback_config_caplog
) -> None:
    """Non-integer env value → fall back to default + WARNING record."""
    _clear_feedback_env(monkeypatch)
    monkeypatch.setenv(ENV_MAX_LOCAL_TICKET_MB, "not_a_number")
    feedback_config_caplog.clear()

    result = max_local_ticket_bytes()

    assert result == DEFAULT_MAX_LOCAL_TICKET_MB * 1024 * 1024

    warnings = _feedback_warnings(feedback_config_caplog)
    assert len(warnings) == 1, f"expected exactly one WARNING, got {warnings!r}"
    record = warnings[0]
    assert record.__dict__.get("event") == "feedback_config_invalid_env"
    assert record.__dict__.get("error_type") == "ValueError"
    assert record.__dict__.get("env_name") == ENV_MAX_LOCAL_TICKET_MB


def test_negative_falls_back_and_logs_warning(
    monkeypatch: pytest.MonkeyPatch, feedback_config_caplog
) -> None:
    """Negative env value → fall back to default + WARNING record."""
    _clear_feedback_env(monkeypatch)
    monkeypatch.setenv(ENV_MAX_LOCAL_TICKET_MB, "-10")
    feedback_config_caplog.clear()

    result = max_local_ticket_bytes()

    assert result == DEFAULT_MAX_LOCAL_TICKET_MB * 1024 * 1024

    warnings = _feedback_warnings(feedback_config_caplog)
    assert len(warnings) == 1, f"expected exactly one WARNING, got {warnings!r}"
    record = warnings[0]
    assert record.__dict__.get("event") == "feedback_config_negative_env"
    assert record.__dict__.get("error_type") == "NegativeValue"
    assert record.__dict__.get("env_name") == ENV_MAX_LOCAL_TICKET_MB


def test_zero_disallowed_for_timeout_falls_back(
    monkeypatch: pytest.MonkeyPatch, feedback_config_caplog
) -> None:
    """Zero timeout is rejected because a 0 s wall-clock would fail instantly."""
    _clear_feedback_env(monkeypatch)
    monkeypatch.setenv(ENV_MATERIALS_BUNDLE_TIMEOUT_S, "0")
    feedback_config_caplog.clear()

    assert materials_bundle_timeout_s() == DEFAULT_MATERIALS_BUNDLE_TIMEOUT_S

    warnings = _feedback_warnings(feedback_config_caplog)
    assert len(warnings) == 1, f"expected exactly one WARNING, got {warnings!r}"
    record = warnings[0]
    assert record.__dict__.get("error_type") == "ZeroDisallowed"
    assert record.__dict__.get("env_name") == ENV_MATERIALS_BUNDLE_TIMEOUT_S


def test_zero_allowed_for_ttl_days(
    monkeypatch: pytest.MonkeyPatch, feedback_config_caplog
) -> None:
    """Zero TTL is a legal "disabled" value — accessor returns 0 with no WARNING."""
    _clear_feedback_env(monkeypatch)
    monkeypatch.setenv(ENV_TICKET_TTL_DAYS, "0")
    feedback_config_caplog.clear()

    assert ticket_attachment_ttl_days() == 0

    warnings = _feedback_warnings(feedback_config_caplog)
    assert warnings == [], f"expected no WARNINGs, got {warnings!r}"


def test_very_long_raw_value_truncated_in_log(
    monkeypatch: pytest.MonkeyPatch, feedback_config_caplog
) -> None:
    """Long raw env values are truncated to ``<=80 chars + '...'`` (<= 83 total)."""
    _clear_feedback_env(monkeypatch)
    monkeypatch.setenv(ENV_MAX_LOCAL_TICKET_MB, "x" * 1000)
    feedback_config_caplog.clear()

    max_local_ticket_bytes()

    warnings = _feedback_warnings(feedback_config_caplog)
    assert len(warnings) == 1, f"expected exactly one WARNING, got {warnings!r}"
    record = warnings[0]
    raw_value = record.__dict__.get("raw_value")
    assert isinstance(raw_value, str), f"raw_value must be a string, got {raw_value!r}"
    assert len(raw_value) <= 83, (
        f"raw_value should be truncated to <= 83 chars (80 + '...'), "
        f"got len={len(raw_value)}"
    )


def test_load_feedback_config_snapshot_is_frozen() -> None:
    """:class:`FeedbackConfig` is a ``@dataclass(frozen=True)`` — mutations raise."""
    snap = FeedbackConfig(
        max_local_ticket_bytes=2,
        materials_bundle_timeout_s=3,
        ticket_attachment_ttl_days=4,
        ticket_json_ttl_days=5,
    )
    with pytest.raises((FrozenInstanceError, AttributeError)):
        snap.max_local_ticket_bytes = 10  # type: ignore[misc]
