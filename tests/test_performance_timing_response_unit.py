from api.schemas.responses import GenerateResponse, PreviewResponse


def test_preview_response_includes_performance_timing() -> None:
    response = PreviewResponse(
        session_id="session-1",
        status="ok",
        message="Preview generated",
        preview_url="/api/files/preview",
        preview_glb_url="/api/files/preview.glb",
        palette=[],
        dimensions={"width": 16, "height": 16},
        performance_timing={
            "total_ms": 12.3,
            "upload_ms": 1.1,
            "worker_ms": 8.2,
            "endpoint_to_enqueue_ms": 0.8,
            "queue_wait_ms": 1.5,
            "worker_execution_ms": 6.2,
            "result_delivery_ms": 0.5,
            "endpoint_post_worker_ms": 3.3,
            "pickle_load_ms": 0.4,
            "segmented_glb_ms": 2.0,
            "palette_ms": 0.6,
        },
    )

    data = response.model_dump()

    assert data["performance_timing"]["total_ms"] == 12.3
    assert data["performance_timing"]["queue_wait_ms"] == 1.5
    assert data["performance_timing"]["endpoint_post_worker_ms"] == 3.3
    assert data["performance_timing"]["segmented_glb_ms"] == 2.0
    assert data["preview_url"] == "/api/files/preview"


def test_generate_response_includes_performance_timing() -> None:
    response = GenerateResponse(
        status="ok",
        message="Model generated",
        download_url="/api/files/model.3mf",
        preview_3d_url="/api/files/model.glb",
        threemf_disk_path="G:/tmp/model.3mf",
        performance_timing={
            "total_ms": 20.5,
            "worker_ms": 18.0,
            "endpoint_to_enqueue_ms": 0.7,
            "queue_wait_ms": 2.0,
            "worker_execution_ms": 15.0,
            "result_delivery_ms": 1.0,
            "endpoint_post_worker_ms": 1.8,
            "overhead_ms": 2.5,
        },
    )

    data = response.model_dump()

    assert data["performance_timing"]["total_ms"] == 20.5
    assert data["performance_timing"]["worker_ms"] == 18.0
    assert data["performance_timing"]["worker_execution_ms"] == 15.0
    assert data["performance_timing"]["result_delivery_ms"] == 1.0
    assert data["download_url"] == "/api/files/model.3mf"
    assert data["threemf_disk_path"] is None


def test_generate_response_includes_wipe_tower_manual_warning_codes() -> None:
    response = GenerateResponse(
        status="ok",
        message="Model generated",
        download_url="/api/files/model.3mf",
        warnings=["wipe_tower_manual_adjustment_required"],
    )

    assert response.model_dump()["warnings"] == [
        "wipe_tower_manual_adjustment_required"
    ]
