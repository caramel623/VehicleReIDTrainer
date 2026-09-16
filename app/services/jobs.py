from datetime import datetime
from pathlib import Path
import subprocess
import uuid
import threading
from .common import read_json, write_json
from .environment import runtime_python, check
from .processes import start_process


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
        report = check(self.root, self.source, allow_cpu)
        if not report["ready"]:
            raise RuntimeError(report.get("error", "Environment check incomplete — Training disabled"))
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
        command = [str(runtime_python(self.root)), "-E", "-s", "-u", "-m", "app.trainer.smoke", "--run", str(self.run_dir)]
        if resume_dir:
            command.append("--resume")
        with (self.run_dir / "train.log").open("a", encoding="utf-8") as log:
            self.process = start_process(command, cwd=self.source, stdout=log, stderr=subprocess.STDOUT)

    def stop(self):
        if self.run_dir:
            (self.run_dir / "stop.request").touch()

    def status(self):
        if not self.run_dir:
            return {"state": "IDLE"}
        try:
            value = read_json(self.run_dir / "status.json")
        except (OSError, ValueError) as error:
            value = {"state": "UNKNOWN", "status_read_error": str(error)}
        if self.process and self.process.poll() is not None:
            value["exit_code"] = self.process.returncode
            if self.process.returncode != 0 or value["state"] not in ("COMPLETED", "STOPPED", "FAILED"):
                value.update(state="FAILED", error=value.get("error", "Trainer exited unexpectedly"))
            # GUI observes worker-owned status; never rewrites it during polling.
        value["run_directory"] = str(self.run_dir)
        value["log_file"] = str(self.run_dir / "train.log")
        if value["state"] == "FAILED":
            try:
                with (self.run_dir / "train.log").open("rb") as log:
                    log.seek(0, 2)
                    log.seek(max(0, log.tell() - 12000))
                    value["last_logs"] = log.read().decode("utf-8", errors="replace")
            except OSError as error:
                value["last_logs"] = f"Unable to read train.log: {error}"
        return value
