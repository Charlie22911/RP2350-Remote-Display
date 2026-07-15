from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


def _load_functional_test_module():
    path = ROOT / "functional-test" / "functional_test.py"
    spec = importlib.util.spec_from_file_location("rpd_functional_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_json_report_records_release_and_tested_usb_identity(tmp_path: Path) -> None:
    functional_test = _load_functional_test_module()
    report = functional_test.Report(
        project_version="9.8.7.dev6",
        library_protocol=5,
        usb_vid=0xCAFE,
        usb_pid=0x4012,
        started_utc="2026-07-14T12:00:00Z",
    )
    report.add("TEST STAGE", 0.0, result="passed")
    path = tmp_path / "functional-report.json"

    functional_test.write_report(report, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["project_version"] == "9.8.7.dev6"
    assert payload["library_protocol"] == 5
    assert payload["usb_vid"] == 0xCAFE
    assert payload["usb_pid"] == 0x4012
    assert payload["started_utc"] == "2026-07-14T12:00:00Z"
    assert payload["finished_utc"].endswith("Z")
    assert payload["stages"][0]["name"] == "TEST STAGE"
