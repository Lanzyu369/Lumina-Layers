"""Self-driven log quality checks for Lumina Studio workflows.

Runs a small API workflow, audits the captured structured log file, and
emits human-readable plus machine-readable governance reports.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_logs import audit_files, event_from_line, parse_json_object

Mode = Literal["fast", "full"]

DEFAULT_WORKFLOW = [
    "startup",
    "lut_list",
    "lut_colors",
    "preview",
    "generate",
    "replace",
    "extract",
]
WORKFLOW_ORDER = [
    "startup",
    "lut_list",
    "lut_colors",
    "preview",
    "generate",
    "vector",
    "replace",
    "extract",
]
WORKFLOW_STEPS = set(WORKFLOW_ORDER)
DEFAULT_MAX_INFO = 30
DEFAULT_MAX_INFO_PER_ENDPOINT = 8
DEFAULT_PORT = 18000
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_SERVER_START_TIMEOUT_SECONDS = 30.0
DEFAULT_LUT_STEM = "Aliz&PLA&4色RYBW&20260211"
DEFAULT_LUT_NAME = f"Aliz - {DEFAULT_LUT_STEM}"
DEFAULT_COLOR_MODE = "4-Color (RYBW)"
DEFAULT_MODELING_MODE = "high-fidelity"
VECTOR_MODELING_MODE = "vector"
FIXTURE_IMAGE = REPO_ROOT / "tests" / "fixtures" / "frozen_assets" / "images" / "logo.png"
VECTOR_FIXTURE_IMAGE = REPO_ROOT / "tests" / "fixtures" / "svg_alignment" / "ring_with_hole.svg"
REPLACE_COLOR_CANDIDATES = ("#ff0000", "#ffff00", "#ffffff", "#0000ff")

_CATCH_ALL_PATTERN = re.compile(r"^(.*_log|status_.*|request_.*)$")
_ALLOWED_LOG_EVENTS = {"client_log", "log_file_configured"}
_ANSI_PATTERN = re.compile(r"(?:\x1b|\\u001b)\[")
_BRACKET_TAG_PATTERN = re.compile(r"^\s*\[[A-Z][A-Z0-9_]*\]")


class QualityCheckError(RuntimeError):
    """Raised when the check cannot run to completion.

    当脚本自身无法完成检查时抛出，例如服务启动失败、fixture 缺失或请求失败。
    """


@dataclass(frozen=True)
class CheckResult:
    """One governance threshold result.
    单个治理阈值检查结果。
    """

    name: str
    passed: bool
    actual: int | float
    operator: str
    threshold: int | float
    severity: str = "error"

    @classmethod
    def evaluate(
        cls,
        *,
        name: str,
        actual: int | float,
        operator: str,
        threshold: int | float,
        severity: str = "error",
    ) -> "CheckResult":
        """Evaluate a numeric threshold.

        Args:
            name: Check name. 检查名称。
            actual: Observed value. 实测值。
            operator: ``<=`` or ``==``. 运算符。
            threshold: Expected threshold. 期望阈值。
            severity: Failure severity label. 失败级别。

        Returns:
            CheckResult: Evaluated result. 已评估结果。
        """

        if operator == "<=":
            passed = actual <= threshold
        elif operator == ">=":
            passed = actual >= threshold
        elif operator == "==":
            passed = actual == threshold
        else:
            raise ValueError(f"Unsupported check operator: {operator}")
        return cls(
            name=name,
            passed=passed,
            actual=actual,
            operator=operator,
            threshold=threshold,
            severity=severity,
        )


@dataclass(frozen=True)
class QualityReport:
    """Complete log quality report.
    完整日志质量报表。
    """

    mode: Mode
    workflow: list[str]
    timestamp: str
    log_path: str
    total_lines: int
    structured_lines: int
    unstructured_lines: int
    duplicate_event_count: int
    request_completed_count: int
    event_counts: dict[str, int]
    top_events: list[dict[str, Any]]
    total_bytes: int
    info_lines: int
    warning_lines: int
    error_lines: int
    catch_all_event_count: int
    ansi_field_count: int
    bracket_tag_message_count: int
    log_file_configured_count: int
    max_info_per_endpoint: int
    info_lines_by_endpoint: dict[str, int]
    checks: list[CheckResult]
    workflow_checks: list[CheckResult]
    overall_passed: bool
    baseline_diff: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        Returns:
            dict[str, Any]: Report dictionary. 报表字典。
        """

        return asdict(self)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Optional argument vector. 可选参数列表。

    Returns:
        argparse.Namespace: Parsed arguments. 解析后的参数。
    """

    parser = argparse.ArgumentParser(
        description="Run Lumina Studio log quality checks.",
    )
    parser.add_argument("--mode", choices=("fast", "full"), required=True)
    parser.add_argument(
        "--workflow",
        default=",".join(DEFAULT_WORKFLOW),
        help="Comma-separated workflow steps.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON report to this path.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Compare the generated report against a baseline JSON report.",
    )
    parser.add_argument(
        "--max-info",
        type=int,
        default=DEFAULT_MAX_INFO,
        help="Maximum INFO lines allowed across the whole workflow.",
    )
    parser.add_argument(
        "--max-info-per-endpoint",
        type=int,
        default=DEFAULT_MAX_INFO_PER_ENDPOINT,
        help="Maximum INFO lines allowed for one request-scoped endpoint.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port used by full mode.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP request timeout for full mode.",
    )
    return parser.parse_args(argv)


def run_fast_mode(temp_log_path: Path, workflow: list[str]) -> dict[str, Any]:
    """Run the workflow through FastAPI TestClient with mocked workers.

    Args:
        temp_log_path: Structured log path. 结构化日志路径。
        workflow: Workflow steps. 业务流步骤。

    Returns:
        dict[str, Any]: Raw audit result. 原始审计结果。
    """

    _prepare_log_environment(temp_log_path)

    import io
    import numpy as np
    from contextlib import redirect_stdout
    from fastapi.testclient import TestClient
    from PIL import Image
    from unittest.mock import AsyncMock, MagicMock, patch

    console_capture = io.StringIO()
    with redirect_stdout(console_capture):
        import api.app as api_app_module
        from api.app import app
        from api.dependencies import get_file_registry, get_session_store, get_worker_pool
        from api.file_registry import FileRegistry
        from api.session_store import SessionStore
        from api.worker_pool import WorkerPoolManager

        created_paths: list[Path] = []
        test_store = SessionStore(ttl=1800)
        test_registry = FileRegistry()
        mock_pool = MagicMock(spec=WorkerPoolManager)
        mock_pool.max_workers = 1
        mock_pool.is_alive = True
        mock_pool.submit = AsyncMock(
            side_effect=lambda worker_fn, *args: _build_mock_worker_result(
                worker_fn,
                created_paths,
                np,
                Image,
                *args,
            )
        )

        original_lifespan_pool = api_app_module.worker_pool
        app.dependency_overrides[get_session_store] = lambda: test_store
        app.dependency_overrides[get_file_registry] = lambda: test_registry
        app.dependency_overrides[get_worker_pool] = lambda: mock_pool
        api_app_module.worker_pool = mock_pool

        try:
            extract_lut_path = _make_temp_path(".json", created_paths)
            extract_lut_path.write_text("{}", encoding="utf-8")
            extract_image = np.zeros((8, 8, 3), dtype=np.uint8)
            with (
                patch("api.routers.converter.preview.generate_segmented_glb", return_value=None),
                patch(
                    "api.routers.converter.preview.recompute_gradient_groups_into_session",
                    return_value=None,
                ),
                patch(
                    "api.routers.converter.replace.schedule_glb_build",
                    return_value="mock-glb-token",
                ),
                patch(
                    "api.routers.extractor.run_extraction",
                    return_value=(
                        extract_image,
                        extract_image,
                        str(extract_lut_path),
                        "OK",
                    ),
                ),
                TestClient(app) as client,
            ):
                _execute_workflow(client, workflow)
            _flush_lumina_handlers()
        finally:
            app.dependency_overrides.clear()
            api_app_module.worker_pool = original_lifespan_pool
            test_store.clear_all()
            _remove_paths(created_paths)
            _flush_lumina_handlers()

    return audit_files([temp_log_path], label="fast")


def run_full_mode(
    temp_log_path: Path,
    workflow: list[str],
    *,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Spawn a real uvicorn server and run the workflow through HTTP.

    Args:
        temp_log_path: Structured log path. 结构化日志路径。
        workflow: Workflow steps. 业务流步骤。
        port: Non-default uvicorn port. uvicorn 非默认端口。
        timeout: HTTP timeout seconds. HTTP 超时秒数。

    Returns:
        dict[str, Any]: Raw audit result. 原始审计结果。
    """

    env = os.environ.copy()
    env["LUMINA_LOG_PATH"] = str(temp_log_path)
    env["LUMINA_LOG_LEVEL"] = "INFO"
    env["LUMINA_LOG_FORMAT"] = "json"
    env.pop("LUMINA_LOG_INIT_BY_PARENT", None)

    creationflags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if os.name == "nt"
        else 0
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_server(base_url, DEFAULT_SERVER_START_TIMEOUT_SECONDS, proc)
        _execute_http_workflow(base_url, workflow, timeout)
    finally:
        _terminate_server_process(proc)
        time.sleep(1.0)

    if not temp_log_path.exists():
        raise QualityCheckError(f"Log file was not created: {temp_log_path}")
    return audit_files([temp_log_path], label="full")


def build_quality_report(
    *,
    mode: Mode,
    workflow: list[str],
    log_path: Path,
    audit_result: Mapping[str, Any],
    max_info: int,
    max_info_per_endpoint: int,
    baseline_path: Path | None = None,
) -> QualityReport:
    """Combine audit output with governance metrics and threshold checks.

    Args:
        mode: Execution mode. 执行模式。
        workflow: Workflow steps. 业务流步骤。
        log_path: Captured log path. 捕获日志路径。
        audit_result: Raw ``audit_files`` result. 原始审计结果。
        max_info: Whole-workflow INFO budget. 全流程 INFO 预算。
        max_info_per_endpoint: Per-request INFO budget. 单请求 INFO 预算。
        baseline_path: Optional baseline path. 可选 baseline 路径。

    Returns:
        QualityReport: Scored report. 评分报表。
    """

    metrics = _scan_log_file_for_governance_metrics(log_path)
    info_by_endpoint = _count_info_lines_by_request_id(log_path)
    max_endpoint_info = max(info_by_endpoint.values(), default=0)
    event_counts = {
        str(key): int(value)
        for key, value in dict(audit_result.get("event_counts", {})).items()
    }
    checks = [
        CheckResult.evaluate(
            name="info_lines_within_budget",
            actual=metrics["info_lines"],
            operator="<=",
            threshold=max_info,
        ),
        CheckResult.evaluate(
            name="info_per_endpoint_within_budget",
            actual=max_endpoint_info,
            operator="<=",
            threshold=max_info_per_endpoint,
        ),
        CheckResult.evaluate(
            name="no_request_completed_catchall",
            actual=int(audit_result.get("request_completed_count", 0)),
            operator="==",
            threshold=0,
        ),
        CheckResult.evaluate(
            name="no_unstructured_lines",
            actual=int(audit_result.get("unstructured_lines", 0)),
            operator="==",
            threshold=0,
        ),
        CheckResult.evaluate(
            name="no_catch_all_events",
            actual=metrics["catch_all_event_count"],
            operator="==",
            threshold=0,
        ),
        CheckResult.evaluate(
            name="no_ansi_escape",
            actual=metrics["ansi_field_count"],
            operator="==",
            threshold=0,
        ),
        CheckResult.evaluate(
            name="no_bracket_tag_message",
            actual=metrics["bracket_tag_message_count"],
            operator="==",
            threshold=0,
        ),
        CheckResult.evaluate(
            name="log_file_configured_once",
            actual=metrics["log_file_configured_count"],
            operator="==",
            threshold=1,
        ),
    ]
    workflow_checks = _workflow_required_event_checks(
        mode=mode,
        workflow=workflow,
        event_counts=event_counts,
    )
    report = QualityReport(
        mode=mode,
        workflow=workflow,
        timestamp=datetime.now(timezone.utc).isoformat(),
        log_path=str(log_path),
        total_lines=int(audit_result.get("total_lines", 0)),
        structured_lines=int(audit_result.get("structured_lines", 0)),
        unstructured_lines=int(audit_result.get("unstructured_lines", 0)),
        duplicate_event_count=int(audit_result.get("duplicate_event_count", 0)),
        request_completed_count=int(audit_result.get("request_completed_count", 0)),
        event_counts=event_counts,
        top_events=list(audit_result.get("top_events", [])),
        total_bytes=int(audit_result.get("total_bytes", 0)),
        info_lines=metrics["info_lines"],
        warning_lines=metrics["warning_lines"],
        error_lines=metrics["error_lines"],
        catch_all_event_count=metrics["catch_all_event_count"],
        ansi_field_count=metrics["ansi_field_count"],
        bracket_tag_message_count=metrics["bracket_tag_message_count"],
        log_file_configured_count=metrics["log_file_configured_count"],
        max_info_per_endpoint=max_endpoint_info,
        info_lines_by_endpoint=info_by_endpoint,
        checks=checks,
        workflow_checks=workflow_checks,
        overall_passed=all(check.passed for check in checks)
        and all(check.passed for check in workflow_checks),
        baseline_diff=(
            _build_baseline_diff(event_counts, report_total_lines=int(audit_result.get("total_lines", 0)), baseline_path=baseline_path)
            if baseline_path is not None
            else None
        ),
    )
    return report


def _workflow_required_event_checks(
    *,
    mode: Mode,
    workflow: Sequence[str],
    event_counts: Mapping[str, int],
) -> list[CheckResult]:
    required_events: list[str] = []
    if "replace" in workflow:
        required_events.append("converter_region_replace_timing")
        if mode == "full":
            required_events.append("vector_matched_rgb_overrides_applied")
    if "extract" in workflow:
        required_events.append("extractor_extract_done")

    return [
        CheckResult.evaluate(
            name=f"workflow_event_{event}",
            actual=int(event_counts.get(event, 0)),
            operator=">=",
            threshold=1,
        )
        for event in required_events
    ]


def write_report(report: QualityReport, output_path: Path) -> None:
    """Write the report JSON to disk.

    Args:
        report: Report to serialize. 待序列化报表。
        output_path: Destination JSON path. 目标 JSON 路径。
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the log quality check command.

    Args:
        argv: Optional CLI argument vector. 可选 CLI 参数列表。

    Returns:
        int: Process exit code. 进程退出码。
    """

    try:
        args = parse_args(argv)
        mode: Mode = args.mode
        workflow = _parse_workflow(args.workflow)
        output_path = _default_output_path(mode) if args.output is None else args.output
        output_path = (REPO_ROOT / output_path).resolve() if not output_path.is_absolute() else output_path
        log_path = output_path.with_suffix(".log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists():
            log_path.unlink()

        if mode == "fast":
            audit_result = run_fast_mode(log_path, workflow)
        else:
            audit_result = run_full_mode(
                log_path,
                workflow,
                port=args.port,
                timeout=args.timeout,
            )

        report = build_quality_report(
            mode=mode,
            workflow=workflow,
            log_path=log_path,
            audit_result=audit_result,
            max_info=args.max_info,
            max_info_per_endpoint=args.max_info_per_endpoint,
            baseline_path=args.baseline,
        )
        write_report(report, output_path)
        sys.stdout.write(_format_stdout_summary(report, output_path))
        return 0 if report.overall_passed else 1
    except QualityCheckError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2
    except Exception as exc:
        sys.stderr.write(f"ERROR: {type(exc).__name__}: {exc}\n")
        return 2


def _prepare_log_environment(log_path: Path) -> None:
    os.environ["LUMINA_LOG_PATH"] = str(log_path)
    os.environ["LUMINA_LOG_LEVEL"] = "INFO"
    os.environ["LUMINA_LOG_FORMAT"] = "json"
    os.environ.pop("LUMINA_LOG_INIT_BY_PARENT", None)


def _build_mock_worker_result(
    worker_fn: Callable[..., Any],
    created_paths: list[Path],
    np_module: Any,
    image_cls: Any,
    *worker_args: Any,
) -> dict[str, Any]:
    name = getattr(worker_fn, "__name__", "")
    if name == "worker_generate_preview":
        if _is_vector_preview_worker_args(worker_args):
            return _build_mock_vector_preview_result(created_paths, np_module, image_cls)
        return _build_mock_preview_result(created_paths, np_module, image_cls)
    if name == "worker_generate_model":
        return _build_mock_generate_result(created_paths)
    raise QualityCheckError(f"Unexpected worker submitted in fast mode: {name}")


def _is_vector_preview_worker_args(worker_args: Sequence[Any]) -> bool:
    if len(worker_args) < 7:
        return False
    image_path = str(worker_args[0])
    modeling_mode = str(worker_args[6])
    return image_path.lower().endswith(".svg") and modeling_mode == VECTOR_MODELING_MODE


def _build_mock_preview_result(
    created_paths: list[Path],
    np_module: Any,
    image_cls: Any,
) -> dict[str, Any]:
    import pickle

    preview = np_module.zeros((8, 8, 3), dtype=np_module.uint8)
    preview[:4, :, :] = [255, 0, 0]
    preview[4:, :, :] = [255, 255, 255]
    mask_solid = np_module.ones((8, 8), dtype=bool)
    material_matrix = np_module.zeros((8, 8, 5), dtype=np_module.int16)

    png_path = _make_temp_path(".png", created_paths)
    image_cls.fromarray(preview).save(png_path)

    cache = {
        "target_w": 8,
        "target_h": 8,
        "target_width_mm": 60.0,
        "color_palette": [
            {"hex": "#ff0000", "color": (255, 0, 0), "count": 32, "percentage": 50.0},
            {"hex": "#ffffff", "color": (255, 255, 255), "count": 32, "percentage": 50.0},
        ],
        "matched_rgb": preview.copy(),
        "mask_solid": mask_solid,
        "quantized_image": preview.copy(),
        "material_matrix": material_matrix,
    }
    cache_path = _make_temp_path(".pkl", created_paths)
    with cache_path.open("wb") as handle:
        pickle.dump(cache, handle)

    return {
        "status_msg": "Preview OK",
        "preview_png_path": str(png_path),
        "cache_data_path": str(cache_path),
    }


def _build_mock_vector_preview_result(
    created_paths: list[Path],
    np_module: Any,
    image_cls: Any,
) -> dict[str, Any]:
    import pickle

    preview = np_module.zeros((10, 10, 3), dtype=np_module.uint8)
    preview[:, :, :] = [0, 128, 255]
    mask_solid = np_module.ones((10, 10), dtype=bool)
    material_matrix = np_module.zeros((10, 10, 5), dtype=np_module.int16)
    preview_rgba = np_module.zeros((10, 10, 4), dtype=np_module.uint8)
    preview_rgba[:, :, :3] = preview
    preview_rgba[:, :, 3] = 255

    png_path = _make_temp_path(".png", created_paths)
    image_cls.fromarray(preview).save(png_path)

    cache = {
        "target_w": 10,
        "target_h": 10,
        "target_width_mm": 60.0,
        "color_palette": [
            {"hex": "#0080ff", "color": (0, 128, 255), "count": 100, "percentage": 100.0},
        ],
        "matched_rgb": preview.copy(),
        "mask_solid": mask_solid,
        "quantized_image": preview.copy(),
        "material_matrix": material_matrix,
        "preview_rgba": preview_rgba,
        "color_conf": {
            "slots": ["White", "Red", "Yellow", "Blue"],
            "preview": {
                0: [255, 255, 255, 255],
                1: [255, 0, 0, 255],
                2: [255, 255, 0, 255],
                3: [0, 128, 255, 255],
            },
        },
        "preview_colors": {
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            2: [255, 255, 0, 255],
            3: [0, 128, 255, 255],
        },
        "slot_names": ["White", "Red", "Yellow", "Blue"],
        "color_contours": {},
        "lut_match_info": {"match_mode": "mock-vector"},
    }
    cache_path = _make_temp_path(".pkl", created_paths)
    with cache_path.open("wb") as handle:
        pickle.dump(cache, handle)

    return {
        "status_msg": "Vector Preview OK",
        "preview_png_path": str(png_path),
        "cache_data_path": str(cache_path),
    }


def _build_mock_generate_result(created_paths: list[Path]) -> dict[str, Any]:
    threemf_path = _make_temp_path(".3mf", created_paths)
    threemf_path.write_bytes(b"mock 3mf")
    glb_path = _make_temp_path(".glb", created_paths)
    glb_path.write_bytes(b"mock glb")
    return {
        "threemf_path": str(threemf_path),
        "glb_path": str(glb_path),
        "status_msg": "Model OK",
    }


def _make_temp_path(suffix: str, created_paths: list[Path]) -> Path:
    fd, raw_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    path = Path(raw_path)
    created_paths.append(path)
    return path


def _execute_http_workflow(base_url: str, workflow: list[str], timeout: float) -> None:
    import httpx

    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        _execute_workflow(client, workflow)


def _execute_workflow(client: Any, workflow: list[str]) -> None:
    lut_name = DEFAULT_LUT_NAME
    session_id: str | None = None
    for step in WORKFLOW_ORDER:
        if step not in workflow or step == "startup":
            continue
        if step == "lut_list":
            response = client.get("/api/lut/list")
            _raise_for_status(response.status_code, response.text, step)
            lut_name = _select_lut_name(response.json(), fallback=lut_name)
        elif step == "lut_colors":
            response = client.get(_lut_colors_path(lut_name))
            _raise_for_status(response.status_code, response.text, step)
        elif step == "preview":
            session_id = _post_preview(client, lut_name)
        elif step == "generate":
            if session_id is None:
                raise QualityCheckError("Workflow step 'generate' requires 'preview'")
            _post_generate(client, session_id, lut_name)
        elif step == "vector":
            _execute_vector_workflow(client, lut_name)
        elif step == "replace":
            _execute_replace_workflow(client, lut_name)
        elif step == "extract":
            _execute_extract_workflow(client)


def _execute_vector_workflow(client: Any, lut_name: str) -> None:
    session_id = _post_vector_preview(client, lut_name)
    _post_vector_generate(client, session_id, lut_name)


def _execute_replace_workflow(client: Any, lut_name: str) -> None:
    """Exercise vector preview, click region replace, then cached vector generate."""

    # Use the same click-detect path as the frontend so the endpoint owns
    # selected_region_mask population before /region-replace mutates cache.
    preview_payload = _post_vector_preview_payload(client, lut_name)
    session_id = _extract_session_id(preview_payload, "Vector preview")
    click_x, click_y = _select_replace_click(preview_payload)
    detected_region = _post_region_detect(client, session_id, click_x, click_y)
    replacement_color = _choose_replacement_color(detected_region)
    _post_region_replace(client, session_id, replacement_color)
    _post_vector_generate(
        client,
        session_id,
        lut_name,
        use_cached_matched_rgb=True,
    )


def _execute_extract_workflow(client: Any) -> None:
    from io import BytesIO

    import numpy as np
    from PIL import Image

    image = np.zeros((100, 100, 3), dtype=np.uint8)
    image[:50, :50] = [255, 255, 255]
    image[:50, 50:] = [255, 0, 0]
    image[50:, :50] = [255, 255, 0]
    image[50:, 50:] = [0, 0, 255]
    buffer = BytesIO()
    Image.fromarray(image, mode="RGB").save(buffer, format="PNG")
    buffer.seek(0)

    response = client.post(
        "/api/extractor/extract",
        files={"image": ("extract.png", buffer, "image/png")},
        data={
            "corner_points": "[[5,5],[95,5],[95,95],[5,95]]",
            "color_mode": DEFAULT_COLOR_MODE,
            "page": "0",
            "eight_color_full_export": "false",
            "offset_x": "0",
            "offset_y": "0",
            "zoom": "1.0",
            "distortion": "0",
            "vignette_correction": "false",
            "auto_wb": "false",
        },
    )
    _raise_for_status(response.status_code, response.text, "extract")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Extract response was not an object")
    if not payload.get("lut_download_url"):
        raise QualityCheckError("Extract response did not include lut_download_url")


def _post_preview(client: Any, lut_name: str) -> str:
    _require_fixture(FIXTURE_IMAGE)
    with FIXTURE_IMAGE.open("rb") as handle:
        response = client.post(
            "/api/convert/preview",
            files={"image": ("logo.png", handle, "image/png")},
            data=_preview_form_data(lut_name),
        )
    _raise_for_status(response.status_code, response.text, "preview")
    return _extract_session_id(response.json(), "Preview")


def _post_vector_preview(client: Any, lut_name: str) -> str:
    return _extract_session_id(
        _post_vector_preview_payload(client, lut_name),
        "Vector preview",
    )


def _post_vector_preview_payload(client: Any, lut_name: str) -> Mapping[str, Any]:
    _require_fixture(VECTOR_FIXTURE_IMAGE)
    with VECTOR_FIXTURE_IMAGE.open("rb") as handle:
        response = client.post(
            "/api/convert/preview",
            files={"image": (VECTOR_FIXTURE_IMAGE.name, handle, "image/svg+xml")},
            data=_preview_form_data(lut_name, modeling_mode=VECTOR_MODELING_MODE),
        )
    _raise_for_status(response.status_code, response.text, "vector preview")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Vector preview response was not an object")
    return payload


def _extract_session_id(payload: Mapping[str, Any], label: str) -> str:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise QualityCheckError(f"{label} response did not include session_id")
    return session_id


def _select_replace_click(preview_payload: Mapping[str, Any]) -> tuple[int, int]:
    dimensions = preview_payload.get("dimensions")
    width = (
        int(dimensions.get("width", 10))
        if isinstance(dimensions, Mapping)
        else 10
    )
    height = (
        int(dimensions.get("height", 10))
        if isinstance(dimensions, Mapping)
        else 10
    )
    if width <= 0 or height <= 0:
        raise QualityCheckError("Vector preview did not include positive dimensions")

    # For ring_with_hole.svg the one-quarter-width point can land just
    # outside the rasterized fill after scaling; one-third width at
    # mid-height lands in the filled band in the real 600x600 preview.
    return max(0, width // 3), max(0, height // 2)


def _post_region_detect(
    client: Any,
    session_id: str,
    x: int,
    y: int,
) -> Mapping[str, Any]:
    response = client.post(
        "/api/convert/region-detect",
        json={"session_id": session_id, "x": x, "y": y},
    )
    _raise_for_status(response.status_code, response.text, "region detect")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise QualityCheckError("Region detect response was not an object")
    if int(payload.get("pixel_count", 0)) <= 0:
        raise QualityCheckError("Region detect returned no pixels")
    return payload


def _choose_replacement_color(region_payload: Mapping[str, Any]) -> str:
    current_color = str(region_payload.get("color_hex") or "").lower()
    for candidate in REPLACE_COLOR_CANDIDATES:
        if candidate.lower() != current_color:
            return candidate
    raise QualityCheckError("No replacement color differed from detected region color")


def _post_region_replace(
    client: Any,
    session_id: str,
    replacement_color: str,
) -> None:
    response = client.post(
        "/api/convert/region-replace",
        json={"session_id": session_id, "replacement_color": replacement_color},
    )
    _raise_for_status(response.status_code, response.text, "region replace")


def _post_generate(client: Any, session_id: str, lut_name: str) -> None:
    response = client.post(
        "/api/convert/generate",
        json=_generate_payload(session_id, lut_name),
    )
    _raise_for_status(response.status_code, response.text, "generate")


def _post_vector_generate(
    client: Any,
    session_id: str,
    lut_name: str,
    *,
    use_cached_matched_rgb: bool = False,
) -> None:
    response = client.post(
        "/api/convert/generate",
        json=_generate_payload(
            session_id,
            lut_name,
            modeling_mode=VECTOR_MODELING_MODE,
            use_cached_matched_rgb=use_cached_matched_rgb,
        ),
    )
    _raise_for_status(response.status_code, response.text, "vector generate")


def _preview_form_data(
    lut_name: str,
    *,
    modeling_mode: str = DEFAULT_MODELING_MODE,
) -> dict[str, str]:
    return {
        "source_kind": "legacy_single",
        "lut_name": lut_name,
        "color_mode": DEFAULT_COLOR_MODE,
        "modeling_mode": modeling_mode,
        "target_width_mm": "60.0",
        "auto_bg": "false",
        "bg_tol": "40",
        "quantize_colors": "48",
        "enable_cleanup": "true",
    }


def _generate_payload(
    session_id: str,
    lut_name: str,
    *,
    modeling_mode: str = DEFAULT_MODELING_MODE,
    use_cached_matched_rgb: bool = False,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "params": {
            "source_kind": "legacy_single",
            "lut_name": lut_name,
            "color_mode": DEFAULT_COLOR_MODE,
            "modeling_mode": modeling_mode,
            "target_width_mm": 60.0,
            "auto_bg": False,
            "bg_tol": 40,
            "quantize_colors": 48,
            "enable_cleanup": True,
            "use_cached_matched_rgb": use_cached_matched_rgb,
        },
    }


def _require_fixture(path: Path) -> None:
    if not path.is_file():
        raise QualityCheckError(f"Fixture image missing: {path}")


def _raise_for_status(status_code: int, text: str, label: str) -> None:
    if status_code >= 400:
        snippet = text[:800].replace("\n", "\\n")
        raise QualityCheckError(f"{label} request failed: HTTP {status_code}: {snippet}")


def _select_lut_name(payload: Mapping[str, Any], *, fallback: str) -> str:
    entries = payload.get("luts")
    if not isinstance(entries, list):
        return fallback
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if isinstance(name, str) and DEFAULT_LUT_STEM in name:
            return name
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        color_mode = item.get("color_mode")
        if isinstance(name, str) and color_mode == DEFAULT_COLOR_MODE:
            return name
    return fallback


def _lut_colors_path(lut_name: str) -> str:
    return f"/api/lut/{quote(lut_name, safe='')}/colors"


def _wait_for_server(
    base_url: str,
    timeout: float,
    proc: subprocess.Popen[Any],
) -> None:
    import httpx

    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise QualityCheckError(
                f"Server process exited before becoming ready, code={proc.returncode}"
            )
        try:
            response = httpx.get(f"{base_url}/api/health", timeout=2.0)
            if response.status_code < 500:
                return
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    raise QualityCheckError(
        f"Server at {base_url} did not start within {timeout}s"
        + (f" (last error: {last_error})" if last_error else "")
    )


def _terminate_server_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return

    if os.name == "nt":
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
            proc.wait(timeout=10)
            return
        except (OSError, subprocess.TimeoutExpired):
            _kill_windows_process_tree(proc.pid)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            proc.kill()

    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _kill_windows_process_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _scan_log_file_for_governance_metrics(log_path: Path) -> dict[str, int]:
    info_lines = 0
    warning_lines = 0
    error_lines = 0
    catch_all = 0
    ansi = 0
    bracket = 0
    log_file_configured = 0

    if not log_path.exists():
        raise QualityCheckError(f"Log file missing: {log_path}")

    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if _ANSI_PATTERN.search(line):
                ansi += 1

            event, _structured = event_from_line(line)
            payload = parse_json_object(line)
            if payload is None:
                continue

            level = str(payload.get("level", "")).upper()
            payload_event = payload.get("event")
            if isinstance(payload_event, str) and payload_event:
                event = payload_event
            message = payload.get("message", "")

            if level == "INFO":
                info_lines += 1
            elif level == "WARNING":
                warning_lines += 1
            elif level == "ERROR":
                error_lines += 1

            if event == "log_file_configured":
                log_file_configured += 1

            if _CATCH_ALL_PATTERN.match(event) and event not in _ALLOWED_LOG_EVENTS:
                catch_all += 1

            if isinstance(message, str) and _BRACKET_TAG_PATTERN.match(message):
                bracket += 1

    return {
        "info_lines": info_lines,
        "warning_lines": warning_lines,
        "error_lines": error_lines,
        "catch_all_event_count": catch_all,
        "ansi_field_count": ansi,
        "bracket_tag_message_count": bracket,
        "log_file_configured_count": log_file_configured,
    }


def _count_info_lines_by_request_id(log_path: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            payload = parse_json_object(line)
            if payload is None:
                continue
            if str(payload.get("level", "")).upper() != "INFO":
                continue
            request_id = payload.get("request_id")
            if isinstance(request_id, str) and request_id:
                counts[request_id] += 1
    return dict(sorted(counts.items()))


def _build_baseline_diff(
    current_events: Mapping[str, int],
    *,
    report_total_lines: int,
    baseline_path: Path | None,
) -> dict[str, Any]:
    if baseline_path is None:
        return {}
    resolved = (REPO_ROOT / baseline_path).resolve() if not baseline_path.is_absolute() else baseline_path
    try:
        baseline = json.loads(resolved.read_text(encoding="utf-8"))
    except OSError as exc:
        raise QualityCheckError(f"Baseline report cannot be read: {resolved}: {exc}") from exc
    old_events = {
        str(key): int(value)
        for key, value in dict(baseline.get("event_counts", {})).items()
    }
    old_total_lines = int(baseline.get("total_lines", 0))
    added = {
        event: count
        for event, count in current_events.items()
        if event not in old_events
    }
    removed = {
        event: count
        for event, count in old_events.items()
        if event not in current_events
    }
    changed = {
        event: {
            "before": old_events[event],
            "after": current_events[event],
            "delta": current_events[event] - old_events[event],
        }
        for event in current_events.keys() & old_events.keys()
        if current_events[event] != old_events[event]
    }
    return {
        "baseline_path": str(resolved),
        "new_events": dict(sorted(added.items())),
        "removed_events": dict(sorted(removed.items())),
        "changed_events": dict(sorted(changed.items())),
        "line_count": report_total_lines,
        "baseline_line_count": old_total_lines,
        "line_count_delta": report_total_lines - old_total_lines,
    }


def _parse_workflow(raw_workflow: str) -> list[str]:
    workflow = [item.strip() for item in raw_workflow.split(",") if item.strip()]
    if not workflow:
        raise QualityCheckError("Workflow must include at least one step")
    unknown = sorted(set(workflow) - WORKFLOW_STEPS)
    if unknown:
        raise QualityCheckError(f"Unknown workflow step(s): {', '.join(unknown)}")
    if "generate" in workflow and "preview" not in workflow:
        raise QualityCheckError("Workflow step 'generate' requires 'preview'")
    if "vector" in workflow and "replace" in workflow:
        raise QualityCheckError(
            "Workflow steps 'vector' and 'replace' should not be combined; "
            "'replace' is the canonical vector region-replace superset."
        )
    return workflow


def _default_output_path(mode: Mode) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return REPO_ROOT / "progress" / f"log_audit_{mode}_{timestamp}.json"


def _format_stdout_summary(report: QualityReport, output_path: Path) -> str:
    lines = [
        (
            "=== Lumina Log Quality Check "
            f"(mode={report.mode}, workflow={','.join(report.workflow)}) ==="
        ),
        (
            f"Log: {Path(report.log_path).relative_to(REPO_ROOT)} "
            f"({_format_bytes(report.total_bytes)}, {report.total_lines} lines)"
        ),
        f"JSON: {output_path.relative_to(REPO_ROOT)}",
        "",
        "LEVEL DISTRIBUTION",
        f"  INFO    : {report.info_lines}",
        f"  WARNING : {report.warning_lines}",
        f"  ERROR   : {report.error_lines}",
        "",
        "TOP EVENTS",
    ]
    if report.top_events:
        for entry in report.top_events:
            event = str(entry.get("event", "?"))
            count = int(entry.get("count", 0))
            lines.append(f"  {event:<32}: {count}")
    else:
        lines.append("  none")

    lines.extend(
        [
            "",
            "GOVERNANCE CHECKS",
        ]
    )
    for check in report.checks:
        label = "PASS" if check.passed else "FAIL"
        lines.append(
            f"  [{label}] {check.name:<34} "
            f"{check.actual} {check.operator} {check.threshold}"
        )

    if report.workflow_checks:
        lines.extend(["", "WORKFLOW CHECKS"])
        for check in report.workflow_checks:
            label = "PASS" if check.passed else "FAIL"
            lines.append(
                f"  [{label}] {check.name:<34} "
                f"{check.actual} {check.operator} {check.threshold}"
            )

    lines.append("")
    lines.append(f"RESULT: {'PASS' if report.overall_passed else 'FAIL'}")

    if report.baseline_diff:
        lines.extend(["", _format_baseline_diff(report)])

    return "\n".join(lines) + "\n"


def _format_baseline_diff(report: QualityReport) -> str:
    diff = report.baseline_diff or {}
    baseline_path = str(diff.get("baseline_path", "baseline"))
    lines = [f"=== DIFF vs {baseline_path} ==="]
    new_events = diff.get("new_events") or {}
    removed_events = diff.get("removed_events") or {}

    lines.append("+ NEW EVENTS:")
    if new_events:
        for event, count in new_events.items():
            lines.append(f"  {event:<32} ({count})")
    else:
        lines.append("  none")

    lines.append("- REMOVED EVENTS:")
    if removed_events:
        for event, count in removed_events.items():
            lines.append(f"  {event:<32} ({count})")
    else:
        lines.append("  none")

    lines.append(
        "+ LINE COUNT: "
        f"{diff.get('line_count', 0)} "
        f"(was {diff.get('baseline_line_count', 0)}, "
        f"delta {diff.get('line_count_delta', 0):+})"
    )
    lines.append(f"RESULT: {'NO REGRESSION' if report.overall_passed else 'CHECK FAILED'}")
    return "\n".join(lines)


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    return f"{size / 1024:.1f} KB"


def _flush_lumina_handlers() -> None:
    for logger_name in ("lumina", ""):
        for handler in logging.getLogger(logger_name).handlers:
            try:
                handler.flush()
            except Exception:
                continue


def _remove_paths(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
