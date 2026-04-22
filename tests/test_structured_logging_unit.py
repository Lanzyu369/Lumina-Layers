from __future__ import annotations

import json
import logging

from api.structured_logging import _JsonFormatter


def test_json_formatter_preserves_custom_extra_fields() -> None:
    formatter = _JsonFormatter()
    record = logging.makeLogRecord(
        {
            "name": "lumina.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "Client log received",
            "args": (),
            "event": "client_log",
            "client_label": "preview: request sent",
            "client_scope": "preview",
            "client_phase": "request-sent",
            "client_details": {
                "quantize_colors": 256,
                "selected_material_count": 4,
                "flags": ["cleanup", "preview-glb"],
            },
        }
    )

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "client_log"
    assert payload["client_label"] == "preview: request sent"
    assert payload["client_scope"] == "preview"
    assert payload["client_phase"] == "request-sent"
    assert payload["client_details"] == {
        "quantize_colors": 256,
        "selected_material_count": 4,
        "flags": ["cleanup", "preview-glb"],
    }
