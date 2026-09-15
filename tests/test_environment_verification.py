import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
from app.services import environment
from app.services.processes import capture_progress

ROOT = Path(__file__).resolve().parents[1]


def prepare_probe(monkeypatch):
    monkeypatch.setattr(environment,"installed_versions",lambda *a:environment.locked_versions(ROOT))
    monkeypatch.setattr(environment,"runtime_python",lambda *a:Path("managed/python.exe"))
    def no_driver(*a, **kw): raise FileNotFoundError("nvidia-smi")
    monkeypatch.setattr(environment.subprocess,"run",no_driver)


@pytest.mark.parametrize("allow_cpu", [False, True])
def test_timeout_is_not_cuda_unavailability(monkeypatch,tmp_path,allow_cpu):
    prepare_probe(monkeypatch)
    def probe(command,timeout,output,waiting):
        assert timeout==600
        output("PROGRESS Importing torchvision")
        waiting(70)
        raise subprocess.TimeoutExpired(command,timeout,output="stack diagnostics")
    monkeypatch.setattr(environment,"capture_progress",probe)
    logs=[]
    report=environment.check(tmp_path,ROOT,allow_cpu,log=logs.append)
    assert report["ready"] is False and report["error_code"]=="verification_timeout"
    assert report["stage"]=="Importing torchvision"
    assert "available" not in report and "selected_device" not in report
    assert any("70s" in message for message in logs)
    assert "stack diagnostics" in report["diagnostics"]


def test_import_failure_is_distinct_from_timeout(monkeypatch,tmp_path):
    prepare_probe(monkeypatch)
    def probe(command,timeout,output,waiting):
        output("PROGRESS Importing torch")
        raise RuntimeError("DLL load failed")
    monkeypatch.setattr(environment,"capture_progress",probe)
    report=environment.check(tmp_path,ROOT)
    assert report["error_code"]=="verification_failed"
    assert "DLL load failed" in report["error"]


def test_metadata_mismatch_does_not_import_or_install(monkeypatch,tmp_path):
    monkeypatch.setattr(environment,"installed_versions",lambda *a:{})
    monkeypatch.setattr(environment,"capture_progress",lambda *a:pytest.fail("Unexpected import"))
    report=environment.check(tmp_path,ROOT)
    assert report["error_code"]=="dependency_mismatch"


def test_cpu_selftest_only_when_permitted(monkeypatch,tmp_path):
    prepare_probe(monkeypatch)
    def probe(command,timeout,output,waiting):
        assert "--allow-cpu" in command and "--self-test" in command
        output("RESULT " + json.dumps(dict(python="3.12.10",torch="2.7.1+cu126",torchvision="0.22.1+cu126",cuda="12.6",available=False,selected_device="cpu",self_test="passed")))
    monkeypatch.setattr(environment,"capture_progress",probe)
    assert environment.check(tmp_path,ROOT,True,self_test=True)["ready"] is True


def test_progress_while_real_child_is_silent():
    lines=[]; waits=[]
    code="import time; print('PROGRESS importing',flush=True); time.sleep(0.4); print('RESULT done',flush=True)"
    capture_progress([sys.executable,"-I","-u","-c",code],5,lines.append,waits.append,interval=0.05)
    assert lines==["PROGRESS importing","RESULT done"] and waits


def test_real_stuck_child_is_terminated(monkeypatch):
    import app.services.processes as processes
    original=processes.start_process
    children=[]
    def start(*args,**kwargs):
        child=original(*args,**kwargs);children.append(child);return child
    monkeypatch.setattr(processes,"start_process",start)
    with pytest.raises(subprocess.TimeoutExpired):
        capture_progress([sys.executable,"-I","-c","import time;time.sleep(30)"],0.3,lambda x:None,lambda x:None,interval=0.05)
    assert children[0].poll() is not None


def test_real_child_failure_keeps_diagnostic():
    with pytest.raises(RuntimeError,match="failure detail"):
        capture_progress([sys.executable,"-I","-c","raise RuntimeError('failure detail')"],5,lambda x:None,lambda x:None)


def test_real_probe_imports_and_cpu_self_test():
    pytest.importorskip("torch")
    pytest.importorskip("torchvision")
    lines=[]
    capture_progress([sys.executable,"-I","-u",str(ROOT / "app/services/environment_probe.py"),"--allow-cpu","--self-test"],30,lines.append,lambda x:None)
    result=json.loads(next(line[len("RESULT "):] for line in lines if line.startswith("RESULT ")))
    assert result["selected_device"]=="cpu" and result["self_test"]=="passed"
    assert "PROGRESS Importing torch" in lines and "PROGRESS Importing torchvision" in lines


def test_metadata_inventory_does_not_import_torch(monkeypatch,tmp_path):
    monkeypatch.setattr(environment,"runtime_python",lambda *a:Path(sys.executable))
    versions=environment.installed_versions(tmp_path,ROOT)
    assert versions["torch"] and versions["PySide6"]
