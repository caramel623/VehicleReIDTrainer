"""Explicit, first-install-only setup. Existing runtime is never modified."""
from pathlib import Path
import subprocess
import urllib.request
from .common import digest, write_json
from .environment import manifest, check


class DependencyManager:
    def __init__(self, root: Path, source: Path, log=print, allow_cpu: bool = False):
        self.root, self.source, self.log = root, source, log
        self.allow_cpu = allow_cpu is True

    def execute(self, command):
        self.log("Installing: " + " ".join(map(str, command)))
        with subprocess.Popen(list(map(str, command)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace") as process:
            for line in process.stdout:
                self.log(line.rstrip())
            if process.wait():
                raise RuntimeError("Installer command failed; see environment log")

    def install(self):
        expected = manifest(self.source)
        runtime = self.root / "runtime"
        marker = self.root / "state/environment-installing.json"
        if runtime.exists() and not marker.exists():
            if check(self.root, self.source, self.allow_cpu)["ready"]:
                self.log("Environment already ready; no installation needed")
                return
            raise RuntimeError("Existing runtime preserved. Phase 1 repair requires a fresh portable folder; copy no runtime into it.")
        cache = self.root / "cache/packages"
        cache.mkdir(parents=True, exist_ok=True)
        installer = cache / "python-installer.exe"
        write_json(marker, {"environment_version": expected["environment_version"]})
        if not installer.exists() or digest(installer) != expected["python_sha256"]:
            self.log("Downloading managed Python")
            temporary = installer.with_suffix(".part")
            urllib.request.urlretrieve(expected["python_url"], temporary)
            if digest(temporary) != expected["python_sha256"]:
                raise ValueError("Python SHA256 mismatch")
            temporary.replace(installer)
        python = runtime / "python.exe"
        if not python.exists():
            self.execute([installer, "/quiet", "InstallAllUsers=0", "TargetDir=" + str(runtime), "PrependPath=0", "Include_launcher=0", "Include_test=0", "Include_doc=0", "Include_tcltk=0", "Include_pip=1", "AssociateFiles=0", "Shortcuts=0"])
        self.execute([python, "-m", "pip", "install", "--cache-dir", cache, "torch==" + expected["torch"], "torchvision==" + expected["torchvision"], "--index-url", expected["pytorch_index_url"]])
        self.execute([python, "-m", "pip", "install", "--cache-dir", cache, "-r", self.source / "configs/requirements.lock"])
        self.log("Verifying environment and selected-device matrix multiply")
        if not check(self.root, self.source, self.allow_cpu)["ready"]:
            raise RuntimeError("INSTALL FAILED: CUDA unavailable or version mismatch")
        report = check(self.root, self.source, self.allow_cpu)
        device = "cuda" if report["cuda_ready"] else "cpu"
        self.log("Self test device: " + device + " (CPU permission: " + str(self.allow_cpu) + ")")
        self.execute([python, "-I", "-c", f"import torch; x=torch.randn(64,64,device='{device}'); y=x@x; assert y.device.type=='{device}'; print(y.device)"])
        from .common import read_json
        settings_path = self.root / "state/settings.json"
        settings = read_json(settings_path) if settings_path.exists() else {}
        settings["allow_cpu"] = self.allow_cpu
        write_json(settings_path, settings)
        write_json(self.root / "state/environment.json", expected)
        marker.unlink(missing_ok=True)
        self.log("Environment Ready")
