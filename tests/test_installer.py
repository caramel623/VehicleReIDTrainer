import json
from pathlib import Path
from types import SimpleNamespace
import zipfile
import pytest
from app.services.common import digest, read_json, write_json
from app.services.environment import manifest
from app.services.installer import DependencyManager
from app.services.processes import child_environment

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def package(tmp_path):
    archive = tmp_path / "python.nupkg"
    with zipfile.ZipFile(archive, "w") as output:
        for name in ("python.exe", "python312.dll", "Lib/os.py", "Lib/site-packages/pip/__main__.py"):
            output.writestr("tools/" + name, "fixture")
        output.writestr("python.nuspec", "metadata")
    expected = manifest(ROOT).copy()
    expected["python_sha256"] = digest(archive)
    return archive, expected


def manager(tmp_path):
    return DependencyManager(tmp_path / "install folder", ROOT, log=lambda text: None)


def test_hash_failure_never_executes(tmp_path, package, monkeypatch):
    archive, expected = package
    expected["python_sha256"] = "0" * 64
    service = manager(tmp_path)
    with pytest.raises(ValueError, match="SHA256"):
        service.extract_runtime(archive, tmp_path / "staging", expected)
    assert not (tmp_path / "staging").exists()


def test_missing_executable_before_pip(tmp_path):
    service = manager(tmp_path)
    with pytest.raises(RuntimeError, match="Dependency installation is blocked"):
        service.probe_runtime(tmp_path / "runtime", {"python": "3.12.10"})


def test_bad_package_no_promotion_or_dependency_install(tmp_path, monkeypatch):
    service = manager(tmp_path)
    monkeypatch.setattr(service, "download_runtime", lambda expected: tmp_path / "bad.nupkg")
    def fail(*a): raise ValueError("package missing python.exe")
    monkeypatch.setattr(service, "extract_runtime", fail)
    calls = []
    monkeypatch.setattr(service, "execute", lambda command: calls.append(command))
    with pytest.raises(ValueError): service.install()
    assert not calls and not (service.root / "runtime").exists()


def test_recovery_preserves_incomplete_runtime(tmp_path, package, monkeypatch):
    archive, expected = package
    service = manager(tmp_path)
    runtime = service.root / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "keep.txt").write_text("existing content")
    write_json(service.root / "state/environment-installing.json", {"environment_version": 1})
    monkeypatch.setattr(service, "download_runtime", lambda _: archive)
    monkeypatch.setattr(service, "probe_runtime", lambda *a: {})
    assert service.prepare_runtime(expected) == runtime / "python.exe"
    backups = list((service.root / "state").glob("runtime-incomplete-*"))
    assert len(backups) == 1 and (backups[0] / "keep.txt").read_text() == "existing content"
    assert not (runtime / "python.nuspec").exists()


def test_unowned_existing_folder_is_untouched(tmp_path, package):
    service = manager(tmp_path)
    (service.root / "runtime").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="preserved"):
        service.prepare_runtime(package[1])
    assert not (service.root / "state").exists()


def test_staging_failure_keeps_original_runtime(tmp_path, package, monkeypatch):
    archive, expected = package
    service = manager(tmp_path)
    runtime = service.root / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "keep.txt").write_text("old")
    write_json(service.root / "state/environment-installing.json", {})
    monkeypatch.setattr(service, "download_runtime", lambda _: archive)
    def fail(*a): raise RuntimeError("cannot launch python")
    monkeypatch.setattr(service, "probe_runtime", fail)
    with pytest.raises(RuntimeError): service.prepare_runtime(expected)
    assert (runtime / "keep.txt").read_text() == "old"
    assert not list((service.root / "state").glob("runtime-incomplete-*"))


def test_existing_interpreter_does_not_download(tmp_path, monkeypatch):
    service = manager(tmp_path)
    runtime = service.root / "runtime"
    runtime.mkdir(parents=True); (runtime / "python.exe").touch()
    checked = []
    monkeypatch.setattr(service, "probe_runtime", lambda path, expected: checked.append(path))
    monkeypatch.setattr(service, "download_runtime", lambda *a: pytest.fail("Unexpected download"))
    service.prepare_runtime()
    assert checked == [runtime]


@pytest.mark.parametrize("name", ["tools/../escape", "tools/C:/escape", "tools/dir/../../escape"])
def test_archive_escape_rejected(tmp_path, package, name):
    archive, expected = package
    with zipfile.ZipFile(archive, "a") as output: output.writestr(name, "bad")
    expected["python_sha256"] = digest(archive)
    with pytest.raises(ValueError, match="Unsafe"):
        manager(tmp_path).extract_runtime(archive, tmp_path / "staging", expected)
    assert not (tmp_path / "staging").exists()


def test_runtime_probe_rejects_external_pip(tmp_path, monkeypatch):
    import app.services.installer as module
    runtime = tmp_path / "runtime"; runtime.mkdir(); (runtime / "python.exe").touch()
    report = {"version":"3.12.10", "bits":64, "executable":str(runtime / "python.exe"), "prefix":str(runtime), "pip":str(tmp_path / "outside/pip.py")}
    monkeypatch.setattr(module, "capture", lambda *a: json.dumps(report))
    with pytest.raises(RuntimeError, match="pip resolved outside"):
        manager(tmp_path).probe_runtime(runtime, {"python":"3.12.10"})


def test_child_environment_isolates_python(monkeypatch):
    monkeypatch.setenv("PYTHONHOME", "outside")
    monkeypatch.setenv("PYTHONPATH", "outside")
    monkeypatch.setenv("PYTHONUSERBASE", "outside")
    env = child_environment()
    assert not {"PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE"}.intersection(env)


def test_dependencies_only_after_verification(tmp_path, monkeypatch):
    import app.services.installer as module
    service = manager(tmp_path)
    (service.root / "state").mkdir(parents=True)
    calls=[]
    def prepare(expected):
        calls.append("verified")
        return service.root / "runtime/python.exe"
    monkeypatch.setattr(service, "prepare_runtime", prepare)
    monkeypatch.setattr(service, "execute", lambda cmd: calls.append(list(map(str,cmd))))
    monkeypatch.setattr(module, "installed_versions", lambda *a: {})
    monkeypatch.setattr(module, "check", lambda *a, **kw: {"ready":True,"cuda_ready":True,"selected_device":"cuda:0"})
    service.install()
    assert calls[0] == "verified"
    assert all(cmd[0] == str(service.root / "runtime/python.exe") for cmd in calls[1:])
    assert calls[1][1:5] == ["-I", "-m", "pip", "--isolated"]
    assert not (service.root / "state/environment-installing.json").exists()


def test_retry_skips_all_installs_when_versions_match(tmp_path, monkeypatch):
    import app.services.installer as module
    service = manager(tmp_path)
    write_json(service.root / "state/environment-installing.json", {"phase":"dependencies"})
    monkeypatch.setattr(service, "prepare_runtime", lambda _: service.root / "runtime/python.exe")
    monkeypatch.setattr(module, "installed_versions", lambda *a: module.locked_versions(ROOT))
    monkeypatch.setattr(service, "execute", lambda *a: pytest.fail("No pip or second self-test process on verification retry"))
    calls=[]
    def check(*args, **kwargs):
        calls.append(kwargs)
        return {"ready":True, "selected_device":"cuda:0", "self_test":"passed"}
    monkeypatch.setattr(module, "check", check)
    service.install()
    assert calls[0]["self_test"] is True
    assert read_json(service.root / "state/environment-verification.json")["ready"]
    assert not (service.root / "state/environment-installing.json").exists()


def test_timeout_retains_installed_runtime_and_retry_marker(tmp_path, monkeypatch):
    import app.services.installer as module
    service = manager(tmp_path)
    runtime=service.root / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "keep.txt").write_text("installed")
    write_json(service.root / "state/environment-installing.json", {})
    monkeypatch.setattr(service, "prepare_runtime", lambda _: runtime / "python.exe")
    monkeypatch.setattr(module, "installed_versions", lambda *a: module.locked_versions(ROOT))
    monkeypatch.setattr(service, "execute", lambda *a: pytest.fail("Unexpected install"))
    monkeypatch.setattr(module, "check", lambda *a, **kw: {"ready":False,"error_code":"verification_timeout","error":"Import timed out"})
    with pytest.raises(RuntimeError, match="Import timed out"):
        service.install()
    assert (runtime / "keep.txt").read_text()=="installed"
    assert (service.root / "state/environment-installing.json").exists()
    assert read_json(service.root / "state/environment-verification.json")["error_code"]=="verification_timeout"
