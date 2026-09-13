import os
from pathlib import Path
import pytest

pytestmark = [pytest.mark.cuda, pytest.mark.skipif(os.environ.get("VEHICLE_REID_CUDA_TEST") != "1", reason="Run explicitly on AI01 CUDA managed runtime")]


def test_cuda_training_checkpoint_resume(tmp_path, monkeypatch):
    import torch
    from app.services.common import write_json, read_json
    from app.trainer.smoke import run
    assert torch.cuda.is_available() and torch.version.cuda
    write_json(tmp_path / "config.json", {"steps": 3, "device": 0})
    import app.trainer.smoke as smoke
    original = smoke.write_json
    def stop_after_first(path, value):
        original(path, value)
        if value.get("state") == "RUNNING" and value.get("epoch") == 1:
            (tmp_path / "stop.request").touch()
    monkeypatch.setattr(smoke, "write_json", stop_after_first)
    run(tmp_path)
    assert read_json(tmp_path / "status.json")["state"] == "STOPPED"
    monkeypatch.setattr(smoke, "write_json", original)
    (tmp_path / "stop.request").unlink()
    state=torch.load(tmp_path / "checkpoints/last.pt",map_location="cuda",weights_only=True)
    assert state["epoch"]==1
    assert next(iter(state["model"].values())).is_cuda
    run(tmp_path, resume=True)
    assert read_json(tmp_path / "status.json")["state"]=="COMPLETED"

    resumed=torch.load(tmp_path / "checkpoints/last.pt",map_location="cuda",weights_only=True)
    assert resumed["epoch"] == 3
