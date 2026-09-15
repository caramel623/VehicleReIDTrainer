from pathlib import Path
import json
import subprocess
import re
from .common import read_json
from .processes import capture, capture_progress


class CUDARequiredError(RuntimeError):
    pass


def require_cuda(torch, device: int = 0):
    if "+cpu" in torch.__version__ or not torch.version.cuda or not torch.cuda.is_available():
        raise CUDARequiredError("CUDA unavailable — Training disabled")
    if device < 0 or device >= torch.cuda.device_count():
        raise CUDARequiredError("Selected CUDA device unavailable")
    return torch.device(f"cuda:{device}")


def select_device(torch, device: int = 0, allow_cpu: bool = False):
    try:
        return require_cuda(torch, device)
    except CUDARequiredError:
        if allow_cpu is True:
            return torch.device("cpu")
        raise


def runtime_python(root: Path) -> Path:
    path = root.resolve() / "runtime" / "python.exe"
    if not path.is_file():
        raise FileNotFoundError("Managed Python not installed")
    return path


def manifest(root: Path) -> dict:
    value = read_json(root / "configs" / "environment.json")
    for key in ("python", "torch", "torchvision", "pytorch_index_url", "minimum_driver", "environment_version", "python_url", "python_sha256"):
        if not value.get(key):
            raise ValueError(f"Missing environment field: {key}")
    if value["pytorch_index_url"] != "https://download.pytorch.org/whl/cu126":
        raise ValueError("Unsupported CUDA index in Phase 1")
    expected_url = f"https://api.nuget.org/v3-flatcontainer/python/{value['python']}/python.{value['python']}.nupkg"
    if value.get("python_distribution") != "nuget" or value["python_url"] != expected_url:
        raise ValueError("Use the verified official Python NuGet runtime manifest")
    if not re.fullmatch(r"[0-9a-f]{64}", value["python_sha256"]):
        raise ValueError("Missing verified runtime hash")
    return value


def gpu_info() -> str:
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.used,memory.total,utilization.gpu,temperature.gpu", "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
        return result.stdout.strip() or result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "NVIDIA monitoring unavailable"


VERIFICATION_TIMEOUT = 600


def locked_versions(source: Path) -> dict:
    expected = manifest(source)
    packages = dict(line.strip().split("==") for line in (source / "configs/requirements.lock").read_text().splitlines() if line.strip())
    return {"torch": expected["torch"], "torchvision": expected["torchvision"], **packages}


def installed_versions(root: Path, source: Path) -> dict:
    # Read package metadata only; never load torch DLLs just to decide whether pip is needed.
    names = list(locked_versions(source))
    command = "import importlib.metadata as m,json; result={};\nfor n in " + repr(names) + ":\n try: result[n]=m.version(n)\n except m.PackageNotFoundError: result[n]=None\nprint(json.dumps(result))"
    return json.loads(capture([runtime_python(root), "-I", "-c", command], timeout=60))


def check(root: Path, source: Path, allow_cpu: bool = False, *, log=None,
          self_test: bool = False, timeout: float = VERIFICATION_TIMEOUT) -> dict:
    emit = log or (lambda message: None)
    stage = "Checking installed package versions"
    try:
        expected = manifest(source)
        emit(stage)
        installed = installed_versions(root, source)
        wanted = locked_versions(source)
        mismatches = {name: {"expected": value, "installed": installed.get(name)} for name, value in wanted.items() if installed.get(name) != value}
        if mismatches:
            return {"ready": False, "error_code": "dependency_mismatch", "error": "Installed package versions do not match the environment manifest", "mismatches": mismatches}
        driver, driver_supported = None, False
        try:
            driver = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], capture_output=True, text=True, timeout=10, check=True).stdout.splitlines()[0].strip()
            driver_supported = tuple(map(int, driver.split("."))) >= tuple(map(int, expected["minimum_driver"].split(".")))
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            pass
        info = None
        def output(line):
            nonlocal stage, info
            if line.startswith("PROGRESS "):
                stage = line[len("PROGRESS "):]
                emit(stage)
            elif line.startswith("RESULT "):
                info = json.loads(line[len("RESULT "):])
            else:
                emit(line)  # Includes child tracebacks/periodic stack diagnostics.
        def waiting(elapsed):
            emit(f"Still verifying: {stage} ({elapsed}s elapsed, limit {timeout:g}s). Installed packages are preserved.")
        probe = source / "app/services/environment_probe.py"
        command = [runtime_python(root), "-I", "-u", str(probe)]
        if allow_cpu is True:
            command.append("--allow-cpu")
        if driver_supported:
            command.append("--driver-supported")
        if self_test:
            command.append("--self-test")
        stage = "Starting import verification"
        emit(f"Verifying imports (up to {timeout:g}s); progress is reported every 10 seconds")
        capture_progress(command, timeout, output, waiting)
        if info is None:
            raise RuntimeError("Verification process did not return a result")
        info["driver"], info["driver_supported"] = driver, driver_supported
        info["dependencies_match"] = True
        info["environment_matches"] = (info["python"] == expected["python"] and info["torch"] == expected["torch"] and info["torchvision"] == expected["torchvision"])
        info["cuda_ready"] = bool(info["available"] and info["cuda"] and "+cpu" not in info["torch"] and driver_supported)
        info["ready"] = info["environment_matches"] and (info["cuda_ready"] or allow_cpu is True) and (not self_test or info["self_test"] == "passed")
        if not info["ready"]:
            info["error_code"] = "device_unavailable" if info["environment_matches"] else "version_mismatch"
            info["error"] = "CUDA unavailable or driver unsupported; CPU requires explicit permission" if info["environment_matches"] else "Imported Python/package version mismatch"
        return info
    except subprocess.TimeoutExpired as error:
        return {"ready": False, "error_code": "verification_timeout", "stage": stage,
                "error": f"Verification timed out while {stage}; this does not establish CUDA availability. Installed packages are preserved; retry verification.",
                "diagnostics": str(error.output or "")[-4000:]}
    except Exception as error:
        return {"ready": False, "error_code": "verification_failed", "stage": stage, "error": str(error)}
