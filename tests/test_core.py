from pathlib import Path
from types import SimpleNamespace
import csv
import json
import zipfile
import pytest
from app.services.common import contained, digest, read_json, write_json
from app.services.environment import CUDARequiredError, require_cuda, runtime_python, manifest, check
from app.services.dataset import validate, prepare
from scripts.package_update import build
from updater.updater import stage, activate, rollback, version


def test_atomic_json(tmp_path):
    path = tmp_path / "state.json"
    write_json(path, {"state": "READY"}); assert read_json(path)["state"] == "READY"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("relative", ["../secret", "C:/secret", "a/../../secret", "a\\b"])
def test_paths_reject_escape(tmp_path, relative):
    with pytest.raises(ValueError): contained(tmp_path, relative)


@pytest.mark.parametrize("cpu,available,cuda", [(True,True,"12.6"),(False,False,"12.6"),(False,True,None)])
def test_cuda_rejection(cpu, available, cuda):
    fake = SimpleNamespace(__version__="2.7.1+cpu" if cpu else "2.7.1+cu126", version=SimpleNamespace(cuda=cuda), cuda=SimpleNamespace(is_available=lambda: available))
    with pytest.raises(CUDARequiredError): require_cuda(fake)


def test_runtime_not_system(tmp_path):
    with pytest.raises(FileNotFoundError): runtime_python(tmp_path)
    (tmp_path / "runtime").mkdir(); (tmp_path / "runtime/python.exe").touch()
    assert runtime_python(tmp_path) == tmp_path / "runtime/python.exe"


def test_manifest():
    assert manifest(Path(__file__).resolve().parents[1])["torch"].endswith("+cu126")


def test_missing_runtime_detection(tmp_path):
    assert check(tmp_path, Path(__file__).resolve().parents[1])["ready"] is False


@pytest.mark.parametrize("bad", ["1.0", "1.2.3rc1", "01.2.3", "../../1"])
def test_version_reject(bad):
    with pytest.raises(ValueError): version(bad)


def test_version_numeric():
    assert version("v1.10.0") > version("1.9.9")


def csv_write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer=csv.DictWriter(stream, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)


@pytest.fixture
def dataset_root(tmp_path):
    from PIL import Image
    root=tmp_path / "source"; (root / "reid_crops").mkdir(parents=True)
    records=[]; manifests=[]
    for i in range(4):
        relative=f"reid_crops/{i}.png"; Image.new("RGB", (16,16)).save(root / relative)
        records.append(dict(image_id=str(i), path=relative, vehicle_id=str(i//2), event_id=str(i//2), plate_masked="true"))
        manifests.append(dict(image_id=str(i), path=relative, sha256=digest(root / relative)))
    csv_write(root / "metadata/images.csv", records)
    csv_write(root / "metadata/vehicles.csv", [dict(vehicle_id="0"),dict(vehicle_id="1")])
    csv_write(root / "metadata/labels.csv", [dict(image_id=r["image_id"],vehicle_id=r["vehicle_id"]) for r in records])
    (root / "metadata/manifest.jsonl").write_text("\n".join(json.dumps(r) for r in manifests))
    csv_write(root / "splits/train.csv", [dict(image_id="0"),dict(image_id="1")])
    csv_write(root / "splits/val.csv", [dict(image_id="2"),dict(image_id="3")])
    (root / "splits/test.csv").write_text("image_id\n")
    return root


def test_dataset_valid_and_copy(dataset_root,tmp_path):
    result=validate(dataset_root); assert result["valid"],result
    assert prepare(dataset_root,tmp_path / "cache")["fingerprint"] == result["fingerprint"]


def test_dataset_missing(tmp_path):
    assert not validate(tmp_path)["valid"]


def test_dataset_leakage(dataset_root):
    csv_write(dataset_root / "splits/train.csv",[dict(image_id="0"),dict(image_id="2")])
    csv_write(dataset_root / "splits/val.csv",[dict(image_id="1"),dict(image_id="3")])
    assert any("leakage" in e for e in validate(dataset_root)["errors"])


def test_dataset_corrupt_and_fingerprint(dataset_root):
    before=validate(dataset_root)["fingerprint"]
    (dataset_root / "reid_crops/0.png").write_bytes(b"broken")
    after=validate(dataset_root)
    assert not after["valid"] and after["fingerprint"] != before
    assert any("Corrupt" in e for e in after["errors"])


def test_mask_required(dataset_root):
    p=dataset_root / "metadata/images.csv"; p.write_text(p.read_text().replace("true","false"))
    assert any("mask" in e for e in validate(dataset_root)["errors"])


@pytest.fixture
def payload(tmp_path):
    root=tmp_path / "installation"; root.mkdir()
    (root / "app").mkdir(); (root / "app/main.py").write_text("pass\n")
    (root / "configs").mkdir(); (root / "configs/environment.json").write_text('{"environment_version":1}')
    (root / "configs/requirements.lock").write_text("demo==1")
    (root / "VERSION").write_text("0.1.0")
    package,meta=build(root,tmp_path / "output")
    return root,package,meta


def test_update_and_rollback(payload):
    root,package,meta=payload
    target=stage(root,package,meta);activate(root,target)
    assert read_json(root / "state/active.json")["path"]=="releases/0.1.0"
    rollback(root);assert read_json(root / "state/active.json")["path"]=="."


def test_update_corruption(payload):
    root,package,meta=payload;package.write_bytes(b"tampered")
    with pytest.raises(ValueError,match="SHA256"):stage(root,package,meta)
    assert not (root / "state/active.json").exists()


def test_verification_failure_preserves_active(payload):
    root,package,meta=payload;target=stage(root,package,meta)
    write_json(root / "state/active.json",{"path":"."})
    def fail(path):raise RuntimeError("migration failed")
    with pytest.raises(RuntimeError):activate(root,target,fail)
    assert read_json(root / "state/active.json")=={"path":"."}


def test_dependency_change_refused(payload):
    root,package,meta=payload;target=stage(root,package,meta)
    (target / "configs/requirements.lock").write_text("demo==2")
    with pytest.raises(ValueError,match="Environment"):activate(root,target)
    assert not (root / "state/active.json").exists()


def test_zip_escape(payload):
    root,package,meta=payload
    with zipfile.ZipFile(package,"w") as archive:archive.writestr("../escape.py","pass")
    meta.update(package_sha256=digest(package),files={"../escape.py":"ignored"})
    with pytest.raises(ValueError):stage(root,package,meta)
    assert not (root.parent / "escape.py").exists()


def test_oom_status(tmp_path,monkeypatch):
    import sys
    import app.trainer.smoke as smoke
    monkeypatch.setattr(sys,"argv",["smoke","--run",str(tmp_path)])
    def fail(*args): raise RuntimeError("CUDA out of memory")
    monkeypatch.setattr(smoke,"run",fail)
    with pytest.raises(SystemExit): smoke.main()
    assert "CUDA OUT OF MEMORY" in read_json(tmp_path / "status.json")["error"]


def test_job_crash_report(tmp_path):
    from app.services.jobs import TrainingJob
    job=TrainingJob(tmp_path,tmp_path); job.run_dir=tmp_path
    job.process=SimpleNamespace(poll=lambda: 9,returncode=9)
    write_json(tmp_path / "status.json",{"state":"RUNNING"})
    result=job.status()
    assert result["state"]=="FAILED" and result["exit_code"]==9


@pytest.mark.parametrize("permission", [False, None, "true", 1])
def test_cpu_requires_explicit_boolean(permission):
    from app.services.environment import select_device
    fake=SimpleNamespace(__version__="2.7.1+cpu",version=SimpleNamespace(cuda=None))
    with pytest.raises(CUDARequiredError): select_device(fake, allow_cpu=permission)


def test_cpu_explicit_permission():
    from app.services.environment import select_device
    fake=SimpleNamespace(__version__="2.7.1+cpu",version=SimpleNamespace(cuda=None),device=lambda value:value)
    assert select_device(fake,allow_cpu=True)=="cpu"
