"""Application-local Python from the official CPython NuGet distribution."""
from pathlib import Path, PurePosixPath
import json
import shutil
import stat
import subprocess
import tempfile
import urllib.request
import uuid
import zipfile
from .common import digest, write_json, read_json
from .environment import manifest, check
from .processes import start_process, capture


class DependencyManager:
    def __init__(self, root: Path, source: Path, log=print, allow_cpu: bool = False):
        self.root, self.source, self.log = root.resolve(), source.resolve(), log
        self.allow_cpu = allow_cpu is True

    def execute(self, command):
        self.log("Installing: " + subprocess.list2cmdline(list(map(str, command))))
        try:
            with start_process(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace") as process:
                for line in process.stdout:
                    self.log(line.rstrip())
                code = process.wait()
                if code:
                    raise RuntimeError(f"Installer command failed (exit code {code}); see logs/environment.log")
        except FileNotFoundError as error:
            raise RuntimeError(f"Executable missing: {command[0]}. Runtime setup did not complete; no dependency install was started.") from error

    def probe_runtime(self, runtime: Path, expected: dict) -> dict:
        python = runtime / "python.exe"
        if not python.is_file():
            raise RuntimeError(f"Managed Python missing: {python}. Dependency installation is blocked.")
        command = "import sys,struct,json,ssl,pip; print(json.dumps(dict(version='.'.join(map(str,sys.version_info[:3])),bits=struct.calcsize('P')*8,executable=sys.executable,prefix=sys.prefix,pip=pip.__file__)))"
        try:
            report = json.loads(capture([python, "-I", "-c", command]))
            if report["version"] != expected["python"] or report["bits"] != 64:
                raise ValueError("Python version/architecture mismatch")
            if Path(report["executable"]).resolve() != python.resolve() or Path(report["prefix"]).resolve() != runtime.resolve():
                raise ValueError("Python resolved outside the managed runtime")
            if not Path(report["pip"]).resolve().is_relative_to(runtime.resolve()):
                raise ValueError("pip resolved outside the managed runtime")
        except Exception as error:
            raise RuntimeError(f"Managed Python verification failed at {python}: {error}. Existing files are preserved.") from error
        self.log(f"Verified managed Python {report['version']} x64 and local pip: {python}")
        return report

    def download_runtime(self, expected: dict) -> Path:
        cache = self.root / "cache/packages"
        cache.mkdir(parents=True, exist_ok=True)
        package = cache / f"python-{expected['python']}-{expected['python_sha256'][:12]}.nupkg"
        if package.exists() and digest(package) == expected["python_sha256"]:
            self.log("Using verified cached Python package")
            return package
        self.log("Downloading managed Python (official CPython NuGet package)")
        temporary = package.with_suffix(".part-" + uuid.uuid4().hex)
        with urllib.request.urlopen(expected["python_url"], timeout=60) as response, temporary.open("wb") as stream:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > 64 * 1024 * 1024:
                    raise ValueError("Python package exceeds download limit")
                stream.write(block)
        if digest(temporary) != expected["python_sha256"]:
            raise ValueError("Python SHA256 mismatch; existing runtime untouched")
        temporary.replace(package)
        return package

    def extract_runtime(self, package: Path, destination: Path, expected: dict):
        if digest(package) != expected["python_sha256"]:
            raise ValueError("Python SHA256 mismatch")
        with zipfile.ZipFile(package) as archive:
            selected, seen = [], set()
            for member in archive.infolist():
                if not member.filename.startswith("tools/"):
                    continue  # NuGet metadata and package signature are not runtime files.
                relative = member.filename[len("tools/"):]
                if not relative or member.is_dir():
                    continue
                parts = relative.split("/")
                if ("\\" in relative or ":" in relative or PurePosixPath(relative).is_absolute()
                    or any(p in ("", ".", "..") or p.endswith((".", " ")) for p in parts)
                    or stat.S_ISLNK(member.external_attr >> 16)):
                    raise ValueError("Unsafe path in Python package")
                if relative.casefold() in seen:
                    raise ValueError("Duplicate path in Python package")
                seen.add(relative.casefold())
                target = (destination / relative).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError("Python package escapes staging")
                selected.append((member, target))
            required = {"python.exe", "python312.dll", "lib/os.py", "lib/site-packages/pip/__main__.py"}
            if not required.issubset(seen):
                raise ValueError("Python package missing interpreter, standard library, or pip")
            if sum(member.file_size for member, _ in selected) > 256 * 1024 * 1024:
                raise ValueError("Expanded Python package exceeds limit")
            for member, target in selected:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as stream, target.open("xb") as output:
                    shutil.copyfileobj(stream, output)

    def prepare_runtime(self, expected: dict | None = None) -> Path:
        expected = expected or manifest(self.source)
        runtime = self.root / "runtime"
        marker = self.root / "state/environment-installing.json"
        if runtime.is_symlink() or runtime.resolve() != runtime:
            raise ValueError("Runtime must be a direct local child of installation folder")
        if (runtime / "python.exe").is_file():
            self.probe_runtime(runtime, expected)
            return runtime / "python.exe"
        if runtime.exists() and not marker.exists():
            raise RuntimeError("Unrecognized runtime folder preserved. Use a new portable folder.")
        if runtime.is_symlink() or runtime.resolve().parent != self.root:
            raise ValueError("Runtime must be a direct local child of installation folder")
        marker.parent.mkdir(parents=True, exist_ok=True)
        write_json(marker, {"environment_version": expected["environment_version"], "phase": "runtime"})
        package = self.download_runtime(expected)
        staging = Path(tempfile.mkdtemp(prefix="runtime-staging-", dir=marker.parent))
        self.log("Extracting managed Python to staging")
        self.extract_runtime(package, staging, expected)
        self.probe_runtime(staging, expected)
        if runtime.exists():
            # The previous failed setup's files are kept; nothing is recursively deleted.
            backup = self.root / "state" / ("runtime-incomplete-" + uuid.uuid4().hex)
            if not runtime.resolve().is_relative_to(self.root) or not backup.resolve().is_relative_to(self.root):
                raise ValueError("Runtime backup escapes installation folder")
            runtime.rename(backup)
            self.log("Previous incomplete runtime preserved: " + str(backup))
        try:
            staging.rename(runtime)
        except OSError:
            if 'backup' in locals() and not runtime.exists():
                backup.rename(runtime)
            raise
        # Prove relocation works before invoking pip.
        self.probe_runtime(runtime, expected)
        return runtime / "python.exe"

    def install(self):
        expected = manifest(self.source)
        runtime = self.root / "runtime"
        marker = self.root / "state/environment-installing.json"
        if runtime.exists() and not marker.exists():
            if check(self.root, self.source, self.allow_cpu)["ready"]:
                self.log("Environment already ready; no installation needed")
                return
            raise RuntimeError("Existing runtime preserved. Use a fresh portable folder for environment changes.")
        python = self.prepare_runtime(expected)
        write_json(marker, {"environment_version": expected["environment_version"], "phase": "dependencies"})
        cache = self.root / "cache/packages"
        self.execute([python, "-I", "-m", "pip", "--isolated", "install", "--cache-dir", cache, "torch==" + expected["torch"], "torchvision==" + expected["torchvision"], "--index-url", expected["pytorch_index_url"]])
        self.execute([python, "-I", "-m", "pip", "--isolated", "install", "--cache-dir", cache, "-r", self.source / "configs/requirements.lock"])
        self.log("Verifying environment and selected-device matrix multiply")
        report = check(self.root, self.source, self.allow_cpu)
        if not report["ready"]:
            raise RuntimeError("INSTALL FAILED: CUDA unavailable or version mismatch: " + json.dumps(report))
        device = "cuda" if report["cuda_ready"] else "cpu"
        self.log("Self test device: " + device + " (CPU permission: " + str(self.allow_cpu) + ")")
        self.execute([python, "-I", "-c", f"import torch; x=torch.randn(64,64,device='{device}'); y=x@x; assert y.device.type=='{device}'; print(y.device)"])
        settings_path = self.root / "state/settings.json"
        settings = read_json(settings_path) if settings_path.exists() else {}
        settings["allow_cpu"] = self.allow_cpu
        write_json(settings_path, settings)
        write_json(self.root / "state/environment.json", expected)
        marker.unlink(missing_ok=True)
        self.log("Environment Ready")
