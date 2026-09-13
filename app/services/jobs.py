from datetime import datetime
from pathlib import Path
import subprocess
import uuid
import threading
from .common import read_json, write_json
from .environment import runtime_python, check


class TrainingJob:
    def __init__(self, root: Path, source: Path):
        self.root, self.source = root, source
        self.process = None
        self.run_dir = None
        self._start_lock = threading.Lock()

    def start(self, resume_dir: Path | None = None):
        if not self._start_lock.acquire(blocking=False):
            raise RuntimeError("Training start is already pending")
        try:
            return self._start(resume_dir)
        finally:
            self._start_lock.release()

    def _start(self, resume_dir: Path | None = None):
        if self.process and self.process.poll() is None:
            raise RuntimeError("A training job is already running")
        settings_path = self.root / "state/settings.json"
        allow_cpu = read_json(settings_path).get("allow_cpu", False) is True if settings_path.exists() else False
        if not check(self.root, self.source, allow_cpu)["ready"]:
            raise RuntimeError("CUDA unavailable or environment mismatch — Training disabled")
        self.run_dir = resume_dir or self.root / "runs" / (datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6])
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if not resume_dir:
            write_json(self.run_dir / "config.json", {"steps": 20, "device": 0, "allow_cpu": allow_cpu})
            write_json(self.run_dir / "environment.json", read_json(self.source / "configs/environment.json"))
        if resume_dir:
            saved = read_json(self.run_dir / "config.json")
            if saved.get("allow_cpu", False) and not allow_cpu:
                raise RuntimeError("CPU permission was revoked; enable it before resuming this run")
        (self.run_dir / "stop.request").unlink(missing_ok=True)
        write_json(self.run_dir / "status.json", {"state": "STARTING"})
        command = [str(runtime_python(self.root)), "-m", "app.trainer.smoke", "--run", str(self.run_dir)]
        if resume_dir:
            command.append("--resume")
        with (self.run_dir / "train.log").open("a", encoding="utf-8") as log:
            self.process = subprocess.Popen(command, cwd=self.source, stdout=log, stderr=subprocess.STDOUT)

    def stop(self):
        if self.run_dir:
            (self.run_dir / "stop.request").touch()

    def status(self):
        if not self.run_dir:
            return {"state": "IDLE"}
        value = read_json(self.run_dir / "status.json")
        if self.process and self.process.poll() is not None:
            value["exit_code"] = self.process.returncode
            if value["state"] not in ("COMPLETED", "STOPPED", "FAILED"):
                value.update(state="FAILED", error="Trainer exited unexpectedly")
            write_json(self.run_dir / "status.json", value)
        return value
