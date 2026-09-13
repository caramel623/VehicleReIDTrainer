import json
import subprocess
import sys
import pytest
from app.services.common import read_json, write_json


def test_real_cpu_stop_resume(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    import app.trainer.smoke as smoke
    # Force absence of CUDA to verify the explicit permission path on any host.
    monkeypatch.setattr(torch.cuda,"is_available",lambda:False)
    write_json(tmp_path / "config.json", {"steps":3,"device":0,"allow_cpu":True})
    original=smoke.write_json
    def stop(path,value):
        original(path,value)
        if value.get("epoch")==1 and value.get("state")=="RUNNING":
            (tmp_path / "stop.request").touch()
    monkeypatch.setattr(smoke,"write_json",stop)
    smoke.run(tmp_path)
    assert read_json(tmp_path / "status.json")["state"]=="STOPPED"
    assert read_json(tmp_path / "device.json")["actual_device"]=="cpu"
    (tmp_path / "stop.request").unlink()
    monkeypatch.setattr(smoke,"write_json",original)
    smoke.run(tmp_path,resume=True)
    state=torch.load(tmp_path / "checkpoints/last.pt",weights_only=True)
    assert state["epoch"]==3
    assert len((tmp_path / "metrics.jsonl").read_text().splitlines())==3
    assert read_json(tmp_path / "status.json")["state"]=="COMPLETED"


def test_real_cpu_denied_without_permission(tmp_path,monkeypatch):
    torch=pytest.importorskip("torch")
    from app.trainer.smoke import run
    from app.services.environment import CUDARequiredError
    monkeypatch.setattr(torch.cuda,"is_available",lambda:False)
    write_json(tmp_path / "config.json",{"steps":1})
    with pytest.raises(CUDARequiredError):run(tmp_path)
    assert not (tmp_path / "checkpoints/last.pt").exists()
