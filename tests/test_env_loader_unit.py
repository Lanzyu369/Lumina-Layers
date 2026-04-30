"""Unit tests for the ``api.env_loader`` module."""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_env(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_load_env_local_populates_os_environ_from_simple_pairs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.env_loader import load_env_local

    env_file = tmp_path / ".env.local"
    _write_env(
        env_file,
        "LUMINA_FEEDBACK_SMTP_HOST=smtp.gmail.com\n"
        "LUMINA_FEEDBACK_SMTP_PORT=587\n"
        "LUMINA_FEEDBACK_TO=dev@example.com\n",
    )
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_HOST", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_PORT", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_TO", raising=False)

    parsed = load_env_local(env_file)

    assert parsed == {
        "LUMINA_FEEDBACK_SMTP_HOST": "smtp.gmail.com",
        "LUMINA_FEEDBACK_SMTP_PORT": "587",
        "LUMINA_FEEDBACK_TO": "dev@example.com",
    }
    import os

    assert os.environ["LUMINA_FEEDBACK_SMTP_HOST"] == "smtp.gmail.com"
    assert os.environ["LUMINA_FEEDBACK_SMTP_PORT"] == "587"
    assert os.environ["LUMINA_FEEDBACK_TO"] == "dev@example.com"


def test_load_env_local_does_not_override_existing_env_vars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.env_loader import load_env_local

    env_file = tmp_path / ".env.local"
    _write_env(env_file, "LUMINA_FEEDBACK_SMTP_HOST=smtp.gmail.com\n")
    monkeypatch.setenv("LUMINA_FEEDBACK_SMTP_HOST", "shell.set")

    parsed = load_env_local(env_file)

    import os

    assert parsed == {"LUMINA_FEEDBACK_SMTP_HOST": "smtp.gmail.com"}
    assert os.environ["LUMINA_FEEDBACK_SMTP_HOST"] == "shell.set"


def test_load_env_local_override_existing_when_explicitly_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.env_loader import load_env_local

    env_file = tmp_path / ".env.local"
    _write_env(env_file, "LUMINA_FEEDBACK_SMTP_HOST=file.host\n")
    monkeypatch.setenv("LUMINA_FEEDBACK_SMTP_HOST", "shell.set")

    load_env_local(env_file, override_existing=True)

    import os

    assert os.environ["LUMINA_FEEDBACK_SMTP_HOST"] == "file.host"


def test_load_env_local_skips_comments_blanks_and_malformed_lines(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.env_loader import load_env_local

    env_file = tmp_path / ".env.local"
    _write_env(
        env_file,
        "# Bug report email\n"
        "\n"
        "LUMINA_FEEDBACK_SMTP_HOST=smtp.gmail.com\n"
        "no_equals_sign_here\n"
        "=missing_key\n"
        "  =empty_key\n"
        "  # leading spaces on comment\n"
        "LUMINA_FEEDBACK_TO=dev@example.com  \n",
    )
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_HOST", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_TO", raising=False)

    parsed = load_env_local(env_file)

    assert parsed == {
        "LUMINA_FEEDBACK_SMTP_HOST": "smtp.gmail.com",
        "LUMINA_FEEDBACK_TO": "dev@example.com",
    }


def test_load_env_local_strips_one_pair_of_matched_quotes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.env_loader import load_env_local

    env_file = tmp_path / ".env.local"
    _write_env(
        env_file,
        "DOUBLE_QUOTED=\"hello world\"\n"
        "SINGLE_QUOTED='alpha-beta'\n"
        "MIXED_QUOTES=\"unmatched'\n"
        "NESTED=\"  outer  \"\n"
        "BARE=plain-value\n",
    )
    for key in ("DOUBLE_QUOTED", "SINGLE_QUOTED", "MIXED_QUOTES", "NESTED", "BARE"):
        monkeypatch.delenv(key, raising=False)

    parsed = load_env_local(env_file)

    assert parsed == {
        "DOUBLE_QUOTED": "hello world",
        "SINGLE_QUOTED": "alpha-beta",
        "MIXED_QUOTES": "\"unmatched'",
        "NESTED": "  outer  ",
        "BARE": "plain-value",
    }


def test_load_env_local_preserves_equals_inside_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.env_loader import load_env_local

    env_file = tmp_path / ".env.local"
    _write_env(env_file, "LUMINA_FEEDBACK_SMTP_PASSWORD=ab=cd=ef\n")
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_PASSWORD", raising=False)

    parsed = load_env_local(env_file)

    assert parsed == {"LUMINA_FEEDBACK_SMTP_PASSWORD": "ab=cd=ef"}


def test_load_env_local_returns_empty_dict_when_file_missing(
    tmp_path: Path,
) -> None:
    from api.env_loader import load_env_local

    missing = tmp_path / "does_not_exist.env"

    assert load_env_local(missing) == {}


def test_load_env_local_resolves_default_path_via_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.env_loader import load_env_local

    env_file = tmp_path / "shadow.env"
    _write_env(env_file, "LUMINA_FEEDBACK_TO=alt@example.com\n")
    monkeypatch.setenv("LUMINA_ENV_LOCAL_PATH", str(env_file))
    monkeypatch.delenv("LUMINA_FEEDBACK_TO", raising=False)

    parsed = load_env_local()

    assert parsed == {"LUMINA_FEEDBACK_TO": "alt@example.com"}


def test_load_env_local_silently_skips_invalid_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.env_loader import load_env_local

    env_file = tmp_path / ".env.local"
    _write_env(
        env_file,
        "VALID_KEY=ok\n"
        "INVALID-KEY-WITH-DASH=skipped\n"
        "WITH SPACES=skipped\n"
        "1numeric=skipped\n"
        "_underscore_only=ok\n",
    )
    for key in ("VALID_KEY", "INVALID-KEY-WITH-DASH", "WITH SPACES", "1numeric", "_underscore_only"):
        monkeypatch.delenv(key, raising=False)

    parsed = load_env_local(env_file)

    assert "VALID_KEY" in parsed
    assert "_underscore_only" in parsed
    assert "INVALID-KEY-WITH-DASH" not in parsed
    assert "WITH SPACES" not in parsed
