"""Opt-in official-runtime installation without PyTorch or system changes."""
import os
from pathlib import Path
import subprocess
import pytest
from app.services.environment import manifest
from app.services.installer import DependencyManager
from app.services.common import digest, write_json


def test_official_runtime_install_relocation_and_retry(tmp_path, monkeypatch):
    package = os.environ.get("VEHICLE_REID_RUNTIME_PACKAGE")
    if not package or os.name != "nt":
        pytest.skip("Set VEHICLE_REID_RUNTIME_PACKAGE to verified official NuGet archive on Windows")
    source = Path(__file__).resolve().parents[2]
    expected = manifest(source)
    assert digest(Path(package)) == expected["python_sha256"]
    root = tmp_path / "portable with spaces"
    runtime = root / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "previous-file.txt").write_text("preserve")
    write_json(root / "state/environment-installing.json", {"environment_version":1})
    service = DependencyManager(root, source)
    monkeypatch.setattr(service, "download_runtime", lambda _: Path(package))
    python = service.prepare_runtime(expected)
    report = service.probe_runtime(runtime, expected)
    assert report["version"] == "3.12.10"
    service.execute([python, "-I", "-m", "pip", "--isolated", "--version"])
    assert list((root / "state").glob("runtime-incomplete-*/previous-file.txt"))
    monkeypatch.setattr(service, "download_runtime", lambda _: pytest.fail("Redownload on retry"))
    assert service.prepare_runtime(expected) == python
