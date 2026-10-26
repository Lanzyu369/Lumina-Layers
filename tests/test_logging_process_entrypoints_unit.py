"""Real process entrypoints preserve shared logs and request context."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


_SPAWN_PROBE = '''
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
import sys
from api.logger import setup_file_logging
from api.worker_pool import _worker_init, _run_in_worker_with_context
from core.material_process_lifetime import MaterialProcessLifetime
from core.vector_material_meshing import _initialize_material_process

def emit_probe():
    from api.structured_logging import get_logger
    get_logger("spawn_probe").info(
        "Worker logging initialized", extra={"event": "worker_logging_probe_done"},
    )
    return os.getpid()

if __name__ == "__main__":
    setup_file_logging()
    lifetime = MaterialProcessLifetime()
    initializer, initargs = _worker_init, ()
    try:
        if sys.argv[1] == "material":
            lifetime.open()
            initializer = _initialize_material_process
            initargs = (lifetime.name, os.getpid())
        with ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn"),
            initializer=initializer, initargs=initargs,
        ) as pool:
            child_pid = pool.submit(
                _run_in_worker_with_context, emit_probe,
                "request-probe", "session-probe", None,
            ).result(timeout=30)
            assert child_pid != os.getpid()
    finally:
        lifetime.close()
'''


@pytest.mark.parametrize("worker_kind", ["api", "material"])
def test_spawned_initializer_inherits_logging_without_duplicate_bootstrap(
    tmp_path: Path, worker_kind: str,
) -> None:
    script = tmp_path / "spawn_probe.py"
    script.write_text(_SPAWN_PROBE, encoding="utf-8")
    log_path = tmp_path / "parent.jsonl"
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "LUMINA_LOG_PATH": str(log_path),
        "LUMINA_LOG_LEVEL": "INFO",
    }
    env.pop("LUMINA_LOG_INIT_BY_PARENT", None)
    result = subprocess.run(
        [sys.executable, str(script), worker_kind], env=env,
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in records] == [
        "log_file_configured", "worker_logging_probe_done",
    ]
    assert records[1]["request_id"] == "request-probe"
    assert records[1]["session_id"] == "session-probe"
    assert records[1]["module"] == "lumina.spawn_probe"
