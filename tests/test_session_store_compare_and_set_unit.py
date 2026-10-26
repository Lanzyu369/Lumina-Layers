"""Atomic compare-and-set coverage for preview revision publication."""

from api.session_store import SessionStore


def test_compare_and_set_replaces_value_when_revision_matches() -> None:
    store = SessionStore()
    session_id = store.create()
    store.put(
        session_id,
        "preview_cache",
        {"glb_job_token": "current", "glb_url": None},
    )

    committed = store.compare_and_set(
        session_id,
        "preview_cache",
        {"glb_job_token": "current", "glb_url": "/api/files/ready"},
        revision_path=("glb_job_token",),
        expected_revision="current",
    )

    assert committed is True
    assert store.get(session_id)["preview_cache"]["glb_url"] == "/api/files/ready"


def test_compare_and_set_preserves_newer_revision_on_mismatch() -> None:
    store = SessionStore()
    session_id = store.create()
    newer_cache = {"glb_job_token": "newer", "glb_url": None}
    store.put(session_id, "preview_cache", newer_cache)

    committed = store.compare_and_set(
        session_id,
        "preview_cache",
        {"glb_job_token": "older", "glb_url": "/api/files/stale"},
        revision_path=("glb_job_token",),
        expected_revision="older",
    )

    assert committed is False
    assert store.get(session_id)["preview_cache"] == newer_cache


def test_compare_and_set_supports_nested_artifact_revision_path() -> None:
    store = SessionStore()
    session_id = store.create()
    store.put(
        session_id,
        "preview_artifact",
        {
            "url": None,
            "metadata": {"glb_job_token": "current"},
        },
    )

    committed = store.compare_and_set(
        session_id,
        "preview_artifact",
        {
            "url": "/api/files/ready",
            "metadata": {"glb_job_token": "current"},
        },
        revision_path=("metadata", "glb_job_token"),
        expected_revision="current",
    )

    assert committed is True
    assert store.get(session_id)["preview_artifact"]["url"] == "/api/files/ready"


def test_compare_and_set_does_not_recreate_closed_session() -> None:
    store = SessionStore()
    session_id = store.create()
    store.put(session_id, "preview_cache", {"glb_job_token": "current"})
    store.close(session_id)

    committed = store.compare_and_set(
        session_id,
        "preview_cache",
        {"glb_job_token": "current", "glb_url": "/api/files/stale"},
        revision_path=("glb_job_token",),
        expected_revision="current",
    )

    assert committed is False
    assert store.get(session_id) is None
