"""Bounded offline regression: packaged launcher -> private Python -> pip.

Requires a built bootstrap ZIP and the pinned NuGet package in cache/packages.
All generated data stays in a fresh cache/frozen-check-* folder.
"""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import zipfile
import shutil

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text().strip()
manifest = json.loads((root / "configs/environment.json").read_text())
package_name = f"python-{manifest['python']}-{manifest['python_sha256'][:12]}.nupkg"
package = root / "cache/packages" / package_name
if not package.is_file():
    raise RuntimeError("Run scripts/check_runtime_package.py first")
target = Path(tempfile.mkdtemp(prefix="frozen-check-", dir=root / "cache")) / "portable with spaces"
with zipfile.ZipFile(root / "dist" / f"VehicleReIDTrainer-bootstrap-v{version}-win64.zip") as archive:
    archive.extractall(target)
(target / "cache/packages").mkdir(parents=True)
shutil.copyfile(package, target / "cache/packages" / package_name)
(target / "runtime").mkdir()
(target / "runtime/keep.txt").write_text("previous failed installation")
(target / "state").mkdir()
(target / "state/environment-installing.json").write_text('{"environment_version":1}')
env = os.environ.copy()
env["PYTHONHOME"] = str(target / "nonexistent-python")
env["PYTHONPATH"] = str(target / "nonexistent-modules")
# No network is necessary: the package is already hash-verified in cache.
for attempt in range(2):
    result = subprocess.run([str(target / "VehicleReIDTrainer.exe"), "--prepare-runtime-only"], cwd=target, env=env, timeout=120)
    report = json.loads((target / "state/runtime-probe.json").read_text())
    if result.returncode or not report["ready"]:
        raise RuntimeError((target / "logs/environment.log").read_text(encoding="utf-8"))
python = target / "runtime/python.exe"
result = subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "--version"], capture_output=True, text=True, check=True)
assert str(target / "runtime").casefold() in result.stdout.casefold()
assert list((target / "state").glob("runtime-incomplete-*/keep.txt"))
print(json.dumps({"ready":True, "version":version,"pip":result.stdout.strip(),"log":str(target / "logs/environment.log")}, indent=2))
