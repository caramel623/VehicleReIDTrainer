from pathlib import Path
import json
from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QStackedWidget, QLabel, QPushButton, QPlainTextEdit, QFileDialog, QLineEdit, QCheckBox)
from app.services import environment, dataset
from app.services.common import read_json, write_json
from app.services.jobs import TrainingJob
from updater.updater import latest, version


class Worker(QThread):
    result = Signal(str)
    def __init__(self, task):
        super().__init__(); self.task = task
    def run(self):
        try:
            self.result.emit(json.dumps(self.task(), ensure_ascii=False, indent=2))
        except Exception as error:
            self.result.emit("FAILED: " + str(error))


class Window(QMainWindow):
    def __init__(self, root: Path, source: Path):
        super().__init__()
        self.root, self.source, self.workers = root, source, []
        self.job = TrainingJob(root, source)
        self.setWindowTitle("VehicleReIDTrainer " + (source / "VERSION").read_text().strip())
        self.resize(1060, 720)
        holder = QWidget(); self.setCentralWidget(holder); layout = QHBoxLayout(holder)
        nav = QListWidget(); self.stack = QStackedWidget(); layout.addWidget(nav, 1); layout.addWidget(self.stack, 4)
        names = ["Dashboard", "Environment", "Dataset", "Training", "Runs", "Evaluation", "Settings", "Logs", "Updates"]
        self.pages = {}
        for name in names:
            nav.addItem(name); page = QWidget(); box = QVBoxLayout(page); box.addWidget(QLabel(name)); self.stack.addWidget(page); self.pages[name] = box
        nav.currentRowChanged.connect(self.stack.setCurrentIndex); nav.setCurrentRow(0)
        self.dashboard = QLabel("Checking environment…"); self.pages["Dashboard"].addWidget(self.dashboard)
        self.env_output = self.output("Environment")
        self.button("Environment", "Check environment / GPU", self.check_environment)
        self.pages["Environment"].addWidget(QLabel("Install via launcher on a fresh portable folder. Existing runtime is preserved. Dependency migration: Phase 4."))
        self.path = QLineEdit(); self.pages["Dataset"].addWidget(self.path)
        self.button("Dataset", "Select Dataset", self.select_dataset)
        self.data_output = self.output("Dataset")
        self.button("Dataset", "Validate", lambda: self.background(lambda: dataset.validate(Path(self.path.text())), self.data_output))
        self.button("Dataset", "Prepare Local Cache", self.prepare)
        self.pages["Training"].addWidget(QLabel("Phase 1: synthetic smoke only · CUDA preferred / CPU by permission · 20 steps · tiny model · device 0"))
        self.start_button = self.button("Training", "Start Training Smoke", lambda: self.start())
        self.start_button.setEnabled(False)
        self.button("Training", "Stop", self.job.stop)
        self.button("Training", "Resume checkpoint", self.resume)
        self.run_output = self.output("Runs")
        self.pages["Evaluation"].addWidget(QLabel("Phase 2/3: Re-ID metrics and gallery are not implemented in this phase."))
        self.allow_cpu = QCheckBox("允許在 CUDA 無法使用時以 CPU 訓練（速度較慢）")
        self.pages["Settings"].addWidget(self.allow_cpu)
        self.repo = QLineEdit("caramel623/VehicleReIDTrainer"); self.pages["Settings"].addWidget(QLabel("GitHub repository")); self.pages["Settings"].addWidget(self.repo)
        self.button("Settings", "Save Settings", self.save_settings)
        settings = root / "state/settings.json"
        if settings.exists():
            value = read_json(settings); self.path.setText(value.get("dataset_root", "")); self.repo.setText(value.get("github_repository", self.repo.text()))
            self.allow_cpu.setChecked(value.get("allow_cpu", False) is True)
        self.allow_cpu.toggled.connect(self.permission_changed)
        self.log_output = self.output("Logs")
        self.button("Logs", "Read local app log", lambda: self.log_output.setPlainText((root / "logs/app.log").read_text(encoding="utf-8")[-20000:] if (root / "logs/app.log").exists() else "No logs"))
        self.update_output = self.output("Updates")
        self.button("Updates", "Check Release", self.check_updates)
        self.pages["Updates"].addWidget(QLabel("Phase 1: release check + tested staging/rollback CLI. Automatic GUI install arrives in Phase 4."))
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh_run); self.timer.start(1000)
        self.check_environment()

    def output(self, page):
        widget = QPlainTextEdit(); widget.setReadOnly(True); self.pages[page].addWidget(widget); return widget

    def button(self, page, label, action):
        button = QPushButton(label); button.clicked.connect(action); self.pages[page].addWidget(button); return button

    def background(self, task, output, after=None):
        worker = Worker(task); self.workers.append(worker)
        worker.result.connect(output.setPlainText)
        if after: worker.result.connect(after)
        worker.finished.connect(lambda: self.workers.remove(worker))
        worker.start()

    def check_environment(self):
        allow_cpu = self.allow_cpu.isChecked()
        def task():
            result = environment.check(self.root, self.source, allow_cpu); result["gpu"] = environment.gpu_info(); return result
        def done(text):
            try: ready = json.loads(text).get("ready", False)
            except ValueError: ready = False
            self.start_button.setEnabled(ready)
            self.dashboard.setText(("Environment Ready · " + str(json.loads(text).get("selected_device", "cuda"))) if ready else "CUDA unavailable / environment incomplete — Training disabled (CPU requires explicit permission)")
        self.background(task, self.env_output, done)

    def select_dataset(self):
        path = QFileDialog.getExistingDirectory(self, "Dataset")
        if path: self.path.setText(path)

    def prepare(self):
        parent = QFileDialog.getExistingDirectory(self, "Choose local cache parent")
        if parent:
            import uuid
            target = Path(parent) / ("dataset-" + uuid.uuid4().hex[:8])
            source = Path(self.path.text())
            self.background(lambda: {"cache": str(target), **dataset.prepare(source, target)}, self.data_output)

    def start(self, resume=None):
        self.background(lambda: self.job.start(resume) or {"run": str(self.job.run_dir)}, self.run_output)

    def resume(self):
        path = QFileDialog.getExistingDirectory(self, "Existing smoke run", str(self.root / "runs"))
        if path: self.start(Path(path))

    def refresh_run(self):
        if self.job.run_dir:
            try: self.run_output.setPlainText(json.dumps(self.job.status(), indent=2))
            except (OSError, ValueError): pass

    def save_settings(self):
        write_json(self.root / "state/settings.json", {"dataset_root": self.path.text(), "github_repository": self.repo.text(), "training_cache": str(self.root / "cache/datasets"), "model_directory": str(self.root / "models"), "runs_directory": str(self.root / "runs"), "update_channel": "stable", "gpu_device": 0, "environment_version": environment.manifest(self.source)["environment_version"], "allow_cpu": self.allow_cpu.isChecked()})

    def permission_changed(self):
        self.save_settings()
        self.check_environment()

    def check_updates(self):
        repo = self.repo.text()
        def task():
            release = latest(repo)
            return {"current": (self.source / "VERSION").read_text().strip(), "latest": release["tag_name"], "notes": release.get("body", ""), "newer": version(release["tag_name"]) > version((self.source / "VERSION").read_text().strip())}
        self.background(task, self.update_output)

    def closeEvent(self, event):
        if self.workers or (self.job.process and self.job.process.poll() is None):
            self.job.stop(); self.dashboard.setText("Waiting for background work / training to stop; close again afterward."); event.ignore()
        else: event.accept()
