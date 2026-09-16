import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import pytest
from app.services import common
from app.services.common import read_json,write_json
from app.services.jobs import TrainingJob


def test_atomic_write_retries_transient_permission(tmp_path,monkeypatch):
    original=common.os.replace
    calls=[]
    def replace(source,target):
        calls.append(1)
        if len(calls)<3: raise PermissionError("sharing violation")
        original(source,target)
    monkeypatch.setattr(common.os,"replace",replace)
    write_json(tmp_path / "status.json",{"state":"RUNNING"})
    assert len(calls)==3 and read_json(tmp_path / "status.json")["state"]=="RUNNING"


def test_permanent_failure_keeps_previous_json(tmp_path,monkeypatch):
    target=tmp_path / "status.json";write_json(target,{"state":"OLD"})
    def fail(*a): raise PermissionError("persistent")
    monkeypatch.setattr(common.os,"replace",fail)
    monkeypatch.setattr(common.time,"sleep",lambda _:None)
    with pytest.raises(PermissionError):write_json(target,{"state":"NEW"})
    assert read_json(target)=={"state":"OLD"}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(os.name!="nt",reason="Windows sharing semantics")
def test_real_windows_reader_lock_released(tmp_path):
    target=tmp_path / "status.json";write_json(target,{"state":"OLD"})
    reader=target.open("rb")
    thread=threading.Thread(target=lambda:(time.sleep(0.15),reader.close()))
    thread.start()
    try:write_json(target,{"state":"NEW"})
    finally:thread.join();reader.close()
    assert read_json(target)=={"state":"NEW"}


def test_traceback_survives_failed_status_write(tmp_path,monkeypatch,capsys):
    import app.trainer.smoke as smoke
    monkeypatch.setattr(sys,"argv",["smoke","--run",str(tmp_path)])
    def fail_run(*a):raise RuntimeError("original training error")
    def fail_status(*a):raise PermissionError("status denied")
    monkeypatch.setattr(smoke,"run",fail_run);monkeypatch.setattr(smoke,"write_json",fail_status)
    with pytest.raises(SystemExit) as result:smoke.main()
    assert result.value.code==1
    assert "original training error" in capsys.readouterr().err


def test_gui_poll_is_read_only_and_includes_error_log(tmp_path):
    from types import SimpleNamespace
    job=TrainingJob(tmp_path,tmp_path);job.run_dir=tmp_path
    job.process=SimpleNamespace(poll=lambda:1,returncode=1)
    write_json(tmp_path / "status.json",{"state":"RUNNING","epoch":13})
    (tmp_path / "train.log").write_text("PermissionError: status.json denied",encoding="utf-8")
    before=(tmp_path / "status.json").read_bytes()
    status=job.status()
    assert status["state"]=="FAILED" and "PermissionError" in status["last_logs"]
    assert (tmp_path / "status.json").read_bytes()==before


def test_real_training_subprocess_with_status_polling(tmp_path):
    pytest.importorskip("torch")
    write_json(tmp_path / "config.json",{"steps":20,"device":0,"allow_cpu":True})
    write_json(tmp_path / "status.json",{"state":"STARTING"})
    stop=threading.Event()
    def poll():
        while not stop.is_set():
            try:
                with (tmp_path / "status.json").open("rb") as stream:
                    stream.read()
                    stop.wait(0.002)
            except OSError:
                pass
            stop.wait(0.004)
    reader=threading.Thread(target=poll);reader.start()
    root=Path(__file__).resolve().parents[1]
    command=[sys.executable,"-E","-s","-u","-c","import torch; torch.cuda.is_available=lambda:False; from app.trainer.smoke import main; main()","--run",str(tmp_path)]
    try:
        result=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=60)
    finally:
        stop.set();reader.join()
    assert result.returncode==0,result.stderr
    assert read_json(tmp_path / "status.json")["state"]=="COMPLETED"
    assert len((tmp_path / "metrics.jsonl").read_text().splitlines())==20
