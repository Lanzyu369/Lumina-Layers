"""FatCat reads bundled resources beside its relocated native extension."""

from __future__ import annotations

import importlib
from importlib.machinery import EXTENSION_SUFFIXES
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason="FatCat's native dependency requires Python 3.12 or newer",
)


@pytest.mark.parametrize("directory_name", ["ascii", "临时"], ids=["ascii", "chinese"])
def test_metadata_resources_load_from_relocated_extension(
    tmp_path: Path, directory_name: str,
) -> None:
    fatcat = importlib.import_module("fatcat_metadata")
    module_path = Path(fatcat.__file__).resolve()
    assert any(module_path.name.endswith(suffix) for suffix in EXTENSION_SUFFIXES)

    extension_dir = tmp_path / directory_name
    extension_dir.mkdir()
    copied_module = extension_dir / module_path.name
    shutil.copy2(module_path, copied_module)
    shutil.copytree(
        module_path.parent / "fatcat_metadata_data",
        extension_dir / "fatcat_metadata_data",
    )

    child = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "import json, sys; "
            "sys.path.insert(0, sys.argv[1]); "
            "import fatcat_metadata; "
            "print(json.dumps({"
            "'module_file': fatcat_metadata.__file__, "
            "'resources': json.loads("
            "fatcat_metadata.metadata_resource_specs('BambuStudio'))}))",
            str(extension_dir),
        ],
        cwd=extension_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    payload = json.loads(child.stdout)
    assert Path(payload["module_file"]).resolve() == copied_module.resolve()
    assert isinstance(payload["resources"], list)
    assert payload["resources"]
