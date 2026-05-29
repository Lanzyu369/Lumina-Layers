"""Preservation property tests for ``advanced_params.outline`` on the
bug-report path under the *non-bug-condition* domain.

非 bug-condition 域下，``advanced_params.outline`` 走 bug-report 链路的
保留属性测试。

Spec: ``.kiro/specs/svg-vector-outline-support`` Task 2.3 — preservation.

Domain
======

Per ``requirements.md`` §"Bug Analysis" the bug condition for this spec is::

    is_vector_input(input)
      AND enable_outline_intent(input) = true
      AND outline_width_valid(input.outline_width)

So the *non* bug-condition domain (where preservation must hold) is the
union of:

* ``modeling_mode != vector`` (any ``enable_outline`` value is fine), and
* ``modeling_mode == vector`` with ``enable_outline=false`` (vector
  without outline intent).

Both halves are sampled below — the first via two PBT functions, the
second via a dedicated PBT function so the strategies stay clean. A
plain (non-Hypothesis) anchor for ticket LUM-20260527-001's nearest
non-bug-condition cousin (``modeling_mode=high-fidelity``,
``enable_outline=true``, ``outline_width=2.0``) is also included.

What is locked
==============

Per the design document's Preservation Requirements + Testing Strategy
Test Case #3 ("Bug-report ``advanced_params.outline`` non-bug-condition
round-trip 不变"), this test pins down three layers — any one of them
breaking will fail this file:

1. **Sanitizer round-trip identity for outline group.** The dedicated
   ``api.routers.feedback._sanitize_advanced_params`` must not mutate
   ``outline.enable_outline`` / ``outline.outline_width`` on a
   non-bug-condition input. This is the cheapest, most direct contract
   to preserve and is what ``buildAdvancedParams`` -> backend round-trip
   relies on.

2. **End-to-end ticket assembly + load_bug_repro replay.** Submitting
   the bug report to ``POST /api/feedback/bug-report`` (the synchronous
   path runs ``finalize_ticket_async`` under TestClient because Starlette
   runs ``BackgroundTasks`` synchronously after the response body) must
   land an ``outline`` block in ``ticket.json`` that survives
   ``scripts.load_bug_repro.load_bug_repro`` byte-for-byte (the script
   only copies ticket.json, so ``ticket.json -> repro_dir/ticket.json``
   must be JSON-equal).

3. **Structured-logging schema invariants.** The
   ``feedback_bug_report_submitted`` canary must keep its existing field
   names on this path. The list of required fields is a frozen subset
   from ``api/routers/feedback.py``'s emitter; new field additions are
   fine, but removing or renaming any of these fields breaks the
   bug-triage tooling (``scripts/log_quality_check.py`` and the canary
   integration tests). No ``feedback_advanced_params_failed`` WARNING
   must be emitted on a healthy non-bug-condition input.

Validates: Requirements 3.4 (Unchanged Behavior — bug-report path).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from api.routers.feedback import _sanitize_advanced_params
from scripts.load_bug_repro import load_bug_repro


# ---------------------------------------------------------------------------
# Domain constants & strategies
# 域常量与策略
# ---------------------------------------------------------------------------

# Modeling modes are the canonical values from ``api.schemas.converter.ModelingMode``
# kept as plain strings here so the strategies do not import the enum (this
# also guards against a future enum rename — the wire format is what
# ``advanced_params`` persists, not the Python class).
#
# 建模模式直接使用 ``api.schemas.converter.ModelingMode`` 在 wire 格式下
# 的字符串值，避免依赖枚举类，也保护测试不被未来的枚举重命名打断。
_VECTOR_MODE = "vector"
_NON_VECTOR_MODES = ("high-fidelity", "pixel", "color-card")

# Outline width constraint matches ``api.schemas.converter.ConvertGenerateRequest``
# (``Field(2.0, ge=0.5, le=10.0)``). Sampled at low precision so shrinking
# stays fast; precision down to the third decimal is plenty for round-trip.
_outline_width_strategy = st.floats(
    min_value=0.5, max_value=10.0,
    allow_nan=False, allow_infinity=False, width=32,
)


def _non_vector_outline_strategy() -> st.SearchStrategy[dict[str, Any]]:
    """Build the outline group for the ``modeling_mode != vector`` half.

    构造 ``modeling_mode != vector`` 一半的 outline 子载荷。

    Both ``enable_outline=True`` and ``False`` are valid here — outline is
    generally allowed on raster / high-fidelity / pixel modes, so this
    half of the domain spans all four of:

    * ``(modeling_mode != vector, enable_outline=False, outline_width=null)``
    * ``(modeling_mode != vector, enable_outline=False, outline_width=<float>)``
    * ``(modeling_mode != vector, enable_outline=True,  outline_width=<float>)``

    Returns:
        A Hypothesis strategy producing dicts with keys ``modeling_mode``,
        ``enable_outline``, ``outline_width``.
    """
    return st.fixed_dictionaries(
        {
            "modeling_mode": st.sampled_from(_NON_VECTOR_MODES),
            "enable_outline": st.booleans(),
            "outline_width": st.one_of(st.none(), _outline_width_strategy),
        }
    )


def _vector_no_outline_strategy() -> st.SearchStrategy[dict[str, Any]]:
    """Build the outline group for the ``vector + enable_outline=false`` half.

    构造 ``vector + enable_outline=false`` 一半的 outline 子载荷。

    This is the second non-bug-condition shape: vector modeling but the
    user did not opt into outline. The width is allowed to be
    ``null`` *or* a valid float — preservation must hold either way.
    """
    return st.fixed_dictionaries(
        {
            "modeling_mode": st.just(_VECTOR_MODE),
            "enable_outline": st.just(False),
            "outline_width": st.one_of(st.none(), _outline_width_strategy),
        }
    )


def _build_advanced_params(case: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal grouped ``advanced_params`` payload around ``case``.

    围绕 ``case`` 构造最小化的 grouped ``advanced_params`` 载荷。

    The shape mirrors what ``frontend/src/utils/advancedParamsBuilder.ts``
    emits — only the groups required to reach the outline / generation
    fields are populated, the rest stay at sane defaults so the size
    fallback (``_size_trimmed``) never triggers.
    """
    return {
        "dimensions": {
            "target_width_mm": 100,
            "target_height_mm": 100,
        },
        "generation": {
            "structure_mode": "double-sided",
            "modeling_mode": case["modeling_mode"],
            "color_mode": "4-Color (RYBW)",
        },
        "relief": {"enable_relief": False, "color_height_map": {}},
        "outline": {
            "enable_outline": case["enable_outline"],
            "outline_width": case["outline_width"],
        },
        "cloisonne": {"enable_cloisonne": False},
        "coating": {"enable_coating": False},
        "loop": {"add_loop": False},
        "fridge_magnet": {"enable_fridge_magnet": False, "fridge_magnets": None},
        "puzzle": {"puzzleEnabled": False},
        "large_format": {"largeFormatEnabled": False},
        "color_replacement": {"replacement_regions": None},
    }


# ---------------------------------------------------------------------------
# Required structured-logging schema for ``feedback_bug_report_submitted``.
# ``feedback_bug_report_submitted`` 结构化事件的字段不变量。
# ---------------------------------------------------------------------------
#
# Locking the field names that bug-triage tooling relies on. Adding new
# fields is fine; removing or renaming any of these breaks downstream
# consumers (``scripts/log_quality_check.py``, canary tests).
#
# 锁定 bug-triage 工具链依赖的字段名集合。新增字段没问题；删除 / 重命名
# 任何字段都会破坏下游消费方。
_REQUIRED_CANARY_FIELDS = (
    "ticket_id",
    "session_id",
    "session_id_converter",
    "session_id_single_stage",
    "description_length",
    "has_screenshot",
    "language",
    "active_tab",
    "source_version",
    "color_mode",
    "lut_name",
    "email_status",
    "relay_available",
    "recent_client_log_count",
)


# ---------------------------------------------------------------------------
# HTTP / fixture helpers
# HTTP 与夹具辅助
# ---------------------------------------------------------------------------


def _capture_feedback_logger(
    caplog: pytest.LogCaptureFixture,
    level: int,
) -> logging.Logger:
    """Attach caplog to ``lumina.api.routers.feedback`` so we can read events.

    将 caplog 接到 ``lumina.api.routers.feedback`` logger，便于断言结构化事件。
    """
    target_logger = logging.getLogger("lumina.api.routers.feedback")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(level, logger=target_logger.name)
    return target_logger


def _payload(advanced_params: dict[str, Any]) -> dict[str, Any]:
    """Build a complete ``/api/feedback/bug-report`` request body.

    构造完整的 ``/api/feedback/bug-report`` 请求体。

    The shape mirrors the existing ``test_feedback_router_unit._payload``
    helper — only ``advanced_params`` varies between cases so we can
    isolate the field under test.
    """
    return {
        "description": "preservation: non-bug-condition outline round-trip",
        "user_email": None,
        "context": {
            "url": "http://localhost:5174/",
            "user_agent": "pytest",
            "screen_width": 1280,
            "screen_height": 720,
            "device_pixel_ratio": 1.0,
            "app_version": "2.0.0",
            "language": "en",
            "theme": "light",
            "active_tab": "converter",
            "active_session_ids": {
                "converter": "sess-preserve",
                "single_stage": None,
            },
            "color_mode": "4-Color (RYBW)",
            "lut_name": None,
            "source_version": "legacy",
            "selected_native_brand_key": None,
            "selected_native_db_names": [],
            "selected_material_dir_names": [],
            "material_layer_count": None,
            "material_layer_height_mm": None,
            "material_backing_material_dir_name": None,
            "recent_client_logs": [],
            "action_history": [],
            "session_history": [],
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
            "advanced_params": advanced_params,
        },
        "screenshot_data_url": None,
    }


def _read_ticket_json(feedback_root: Path, ticket_id: str) -> dict[str, Any]:
    """Locate ``feedback/<YYYY-MM>/<ticket_id>/ticket.json`` and decode it."""
    for month_dir in feedback_root.iterdir():
        if not month_dir.is_dir():
            continue
        candidate = month_dir / ticket_id / "ticket.json"
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise AssertionError(
        f"ticket.json for {ticket_id} not found under {feedback_root}",
    )


@pytest.fixture()
def feedback_root(tmp_path: Path) -> Path:
    """Fresh feedback root for each test, isolated under tmp_path.

    每个测试独享的 feedback 根目录。
    """
    root = tmp_path / "feedback_root"
    root.mkdir()
    return root


@pytest.fixture()
def repro_root(tmp_path: Path) -> Path:
    """Fresh reproduction-session root for each test.

    每个测试独享的复现目录根。
    """
    root = tmp_path / "repro_sessions"
    root.mkdir()
    return root


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    feedback_root: Path,
) -> TestClient:
    """TestClient with feedback config pinned to the test feedback_root.

    TestClient，将 feedback 路径配置固定到测试目录。
    """
    from api.app import create_app
    import api.feedback_email as feedback_email
    import api.routers.feedback as feedback_router

    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(feedback_root))
    monkeypatch.setenv("LUMINA_FEEDBACK_STARTUP_CLEANUP", "false")
    # Disable the per-client feedback rate limiter for property-based runs.
    # Hypothesis dispatches 50 examples through a single TestClient (which
    # all share ``client_key="testclient"``), and the production default of
    # 30 / 300s would trip mid-run with ``HTTP 429``. Setting the cap to 0
    # follows the documented disable contract in
    # ``api.routers.feedback._enforce_feedback_rate_limit``.
    # 关闭基于客户端的反馈限流：Hypothesis 在同一个 TestClient（共享
    # ``client_key="testclient"``）下连发 50 个样本，生产默认 30 / 300s 会
    # 在中途触发 ``HTTP 429``。把上限设为 0 即按
    # ``_enforce_feedback_rate_limit`` 的关停约定旁路。
    monkeypatch.setenv("LUMINA_FEEDBACK_RATE_LIMIT_MAX", "0")
    monkeypatch.delenv("LUMINA_FEEDBACK_SMTP_HOST", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_TO", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RATE_LIMIT_WINDOW_S", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RELAY_URL", raising=False)
    monkeypatch.delenv("LUMINA_FEEDBACK_RELAY_TOKEN", raising=False)
    feedback_email.is_email_configured.cache_clear()
    feedback_router._clear_feedback_rate_limit_state()
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Layer 1: sanitizer round-trip identity for outline group
# 第 1 层：sanitizer 对 outline 组的 round-trip 身份不变性
# ---------------------------------------------------------------------------


def _assert_outline_round_trip_identity(
    advanced_params: dict[str, Any],
) -> None:
    """Sanitizer must not mutate ``outline`` for non-bug-condition inputs.

    非 bug-condition 输入下，sanitizer 不得修改 ``outline`` 任何字段。
    """
    sanitized = _sanitize_advanced_params(advanced_params)
    assert isinstance(sanitized, dict), (
        "sanitizer must return a dict; got %r" % type(sanitized)
    )
    outline_in = advanced_params["outline"]
    outline_out = sanitized.get("outline")
    assert isinstance(outline_out, dict), (
        "sanitized payload must keep an 'outline' dict; got %r" % outline_out
    )
    # Schema-level shape stability: same key set, no additions / drops.
    assert set(outline_out.keys()) == set(outline_in.keys()), (
        "outline key set drifted: in=%s out=%s"
        % (sorted(outline_in.keys()), sorted(outline_out.keys()))
    )
    assert outline_out["enable_outline"] == outline_in["enable_outline"], (
        "enable_outline mutated by sanitizer: in=%r out=%r"
        % (outline_in["enable_outline"], outline_out["enable_outline"])
    )
    assert outline_out["outline_width"] == outline_in["outline_width"], (
        "outline_width mutated by sanitizer: in=%r out=%r"
        % (outline_in["outline_width"], outline_out["outline_width"])
    )


@given(case=_non_vector_outline_strategy())
@settings(max_examples=50, deadline=None)
def test_sanitizer_preserves_outline_for_non_vector_modes(
    case: dict[str, Any],
) -> None:
    """Property: sanitizer round-trip identity on ``modeling_mode != vector``.

    属性：``modeling_mode != vector`` 下，sanitizer 对 outline 字段保持身份。

    Validates: Requirements 3.4 (Unchanged Behavior — bug-report path).
    """
    advanced_params = _build_advanced_params(case)
    _assert_outline_round_trip_identity(advanced_params)


@given(case=_vector_no_outline_strategy())
@settings(max_examples=50, deadline=None)
def test_sanitizer_preserves_outline_for_vector_without_outline_intent(
    case: dict[str, Any],
) -> None:
    """Property: sanitizer round-trip identity on ``vector + enable_outline=false``.

    属性：``vector + enable_outline=false`` 下，sanitizer 对 outline 字段
    保持身份。

    Validates: Requirements 3.4 (Unchanged Behavior — bug-report path).
    """
    advanced_params = _build_advanced_params(case)
    _assert_outline_round_trip_identity(advanced_params)


# ---------------------------------------------------------------------------
# Layer 2: full submit -> finalize -> load_bug_repro round-trip
# 第 2 层：submit -> finalize -> load_bug_repro 的端到端 round-trip
# ---------------------------------------------------------------------------


def _assert_end_to_end_round_trip(
    client: TestClient,
    feedback_root: Path,
    repro_root: Path,
    advanced_params: dict[str, Any],
) -> dict[str, Any]:
    """Submit -> assemble -> replay -> assert outline byte-equality.

    提交 -> 装配 -> 复现 -> 断言 outline 字节一致。

    Returns:
        The decoded ``ticket.json`` payload from the original feedback dir,
        for callers that want to do further structural assertions on it.
        返回原始 feedback 目录里 ``ticket.json`` 的解码后载荷，便于调用方
        附加额外结构断言。
    """
    response = client.post(
        "/api/feedback/bug-report",
        json=_payload(advanced_params),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    ticket_id = body["ticket_id"]
    # TestClient runs BackgroundTasks synchronously after the response; by
    # this point ``finalize_ticket_async`` has rewritten ``ticket.json`` and
    # produced ``index.md`` / ``summary.txt``.
    # TestClient 在响应后同步执行 BackgroundTasks，此时
    # ``finalize_ticket_async`` 已经重写过 ``ticket.json`` 并生成
    # ``index.md`` / ``summary.txt``。
    ticket_json = _read_ticket_json(feedback_root, ticket_id)
    assert ticket_json["assembly_status"] in ("done", "partial_failed"), (
        "assembly never converged: status=%r" % ticket_json.get("assembly_status")
    )

    # Layer 2a: ticket.json mirrors the input outline group exactly.
    # 第 2a 层：ticket.json 完整保留输入 outline 组。
    persisted_outline = ticket_json["context"]["advanced_params"]["outline"]
    assert persisted_outline == advanced_params["outline"], (
        "ticket.json outline drifted: in=%r out=%r"
        % (advanced_params["outline"], persisted_outline)
    )

    # Layer 2b: scripts.load_bug_repro round-trip preserves the outline group.
    # 第 2b 层：scripts.load_bug_repro round-trip 保留 outline 组。
    result = load_bug_repro(
        ticket_id,
        feedback_root=feedback_root,
        repro_root=repro_root,
    )
    replayed_path = result.repro_dir / "ticket.json"
    assert replayed_path.exists(), (
        "load_bug_repro must copy ticket.json into the repro dir"
    )
    replayed_json = json.loads(replayed_path.read_text(encoding="utf-8"))
    replayed_outline = replayed_json["context"]["advanced_params"]["outline"]
    assert replayed_outline == advanced_params["outline"], (
        "replayed outline drifted from input: in=%r replay=%r"
        % (advanced_params["outline"], replayed_outline)
    )
    # Stronger byte-equality: the entire ticket.json must round-trip JSON-equal.
    # 更强的字节一致性：整个 ticket.json 必须 JSON 等价。
    assert replayed_json == ticket_json, (
        "load_bug_repro mutated ticket.json beyond pure copy"
    )

    return ticket_json


def _build_non_bug_condition_advanced_params(
    case: dict[str, Any],
) -> dict[str, Any]:
    """Wrap a domain ``case`` into a full grouped ``advanced_params`` payload.

    将域 case 包装为完整 grouped ``advanced_params`` 载荷。
    """
    return _build_advanced_params(case)


@given(case=_non_vector_outline_strategy())
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_round_trip_non_vector_outline_preservation(
    case: dict[str, Any],
    client: TestClient,
    feedback_root: Path,
    repro_root: Path,
) -> None:
    """Property: full submit -> finalize -> load_bug_repro round-trip is
    identity-on-outline for the ``modeling_mode != vector`` half of the
    non-bug-condition domain.

    属性：``modeling_mode != vector`` 半域下，submit -> finalize ->
    load_bug_repro 的完整 round-trip 对 outline 组保持身份。

    Validates: Requirements 3.4 (Unchanged Behavior — bug-report path).
    """
    advanced_params = _build_non_bug_condition_advanced_params(case)
    _assert_end_to_end_round_trip(
        client, feedback_root, repro_root, advanced_params,
    )


@given(case=_vector_no_outline_strategy())
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_round_trip_vector_without_outline_preservation(
    case: dict[str, Any],
    client: TestClient,
    feedback_root: Path,
    repro_root: Path,
) -> None:
    """Property: full round-trip is identity-on-outline for the
    ``vector + enable_outline=false`` half of the non-bug-condition domain.

    属性：``vector + enable_outline=false`` 半域下，完整 round-trip 对
    outline 组保持身份。

    Validates: Requirements 3.4 (Unchanged Behavior — bug-report path).
    """
    advanced_params = _build_non_bug_condition_advanced_params(case)
    _assert_end_to_end_round_trip(
        client, feedback_root, repro_root, advanced_params,
    )


# ---------------------------------------------------------------------------
# Layer 3: structured-logging schema invariants
# 第 3 层：结构化日志 schema 不变量
# ---------------------------------------------------------------------------


def test_feedback_bug_report_submitted_event_schema_unchanged(
    client: TestClient,
    feedback_root: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The ``feedback_bug_report_submitted`` canary keeps its existing fields
    on a healthy non-bug-condition input. No
    ``feedback_advanced_params_failed`` WARNING is emitted.

    非 bug-condition 健康输入下，``feedback_bug_report_submitted`` canary
    仍带原有字段；不会触发 ``feedback_advanced_params_failed`` WARNING。

    Validates: Requirements 3.4, 3.5 (structured-event invariants on the
    bug-report path).
    """
    _capture_feedback_logger(caplog, logging.INFO)
    advanced_params = _build_advanced_params(
        {
            "modeling_mode": "high-fidelity",
            "enable_outline": True,
            "outline_width": 2.0,
        }
    )

    response = client.post(
        "/api/feedback/bug-report",
        json=_payload(advanced_params),
    )
    assert response.status_code == 200, response.text

    canaries = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_submitted"
    ]
    assert len(canaries) == 1, (
        "expected exactly one feedback_bug_report_submitted record; got %d"
        % len(canaries)
    )
    canary = canaries[0]
    missing = [
        field for field in _REQUIRED_CANARY_FIELDS if not hasattr(canary, field)
    ]
    assert not missing, (
        "feedback_bug_report_submitted lost required field(s): %s" % missing
    )

    # No advanced-params sanitizer failure WARNING on a healthy input.
    # 健康输入不应触发 advanced-params sanitizer failure WARNING。
    failures = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "feedback_advanced_params_failed"
    ]
    assert failures == [], (
        "did not expect any feedback_advanced_params_failed WARNING for "
        "healthy non-bug-condition input; got %d" % len(failures)
    )


# ---------------------------------------------------------------------------
# Anchor: deterministic non-bug-condition cousin of LUM-20260527-001
# 锚点：工单 LUM-20260527-001 的非 bug-condition 同源场景
# ---------------------------------------------------------------------------


def test_round_trip_anchor_high_fidelity_outline_enabled(
    client: TestClient,
    feedback_root: Path,
    repro_root: Path,
) -> None:
    """Deterministic anchor: ``modeling_mode=high-fidelity``,
    ``enable_outline=true``, ``outline_width=2.0`` is *not* bug-condition
    (the bug condition requires vector input), and its full ticket
    round-trip must preserve the outline group exactly.

    确定性锚点：``modeling_mode=high-fidelity``、``enable_outline=true``、
    ``outline_width=2.0`` 不是 bug condition（需要 vector 输入），其完整
    工单 round-trip 必须精确保留 outline 组。

    Validates: Requirements 3.4 (Unchanged Behavior — bug-report path).
    """
    advanced_params = _build_advanced_params(
        {
            "modeling_mode": "high-fidelity",
            "enable_outline": True,
            "outline_width": 2.0,
        }
    )
    ticket_json = _assert_end_to_end_round_trip(
        client, feedback_root, repro_root, advanced_params,
    )
    # Spot-check that the persisted outline group is exactly two keys with
    # the expected types — guards against schema bumps that silently add or
    # drop fields under ``outline``.
    # 额外断言持久化后的 outline 组恰好包含两个键且类型正确，防止 schema
    # 隐式增删字段。
    persisted_outline = ticket_json["context"]["advanced_params"]["outline"]
    assert set(persisted_outline.keys()) == {"enable_outline", "outline_width"}
    assert persisted_outline["enable_outline"] is True
    assert persisted_outline["outline_width"] == 2.0
