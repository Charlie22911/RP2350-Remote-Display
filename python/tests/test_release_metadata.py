from __future__ import annotations

from importlib.metadata import version as installed_version
from pathlib import Path
import re

import rp2350_remote_display as rpd


ROOT = Path(__file__).resolve().parents[2]


def test_python_package_release_metadata_matches_repository_version() -> None:
    repository_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    pyproject = (ROOT / "python" / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version\s*=\s*"([^"]+)"\s*$', pyproject, re.MULTILINE)

    assert declared is not None
    assert repository_version == declared.group(1)
    assert repository_version == rpd.__version__
    assert repository_version == installed_version("rp2350-remote-display")
