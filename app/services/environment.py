from pathlib import Path
import json
import subprocess
import re
from .common import read_json


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
    if len(value["python_sha256"]) != 64:
        raise ValueError("Missing verified runtime hash")
    return value


def gpu_info() -> str:
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.used,memory.total,utilization.gpu,temperature.gpu", "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
        return result.stdout.strip() or result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "NVIDIA monitoring unavailable"


def check(root: Path, source: Path, allow_cpu: bool = False) -> dict:
    try:
        expected = manifest(source)
        command = "import torch,torchvision,json,sys; print(json.dumps(dict(python='.'.join(map(str,sys.version_info[:3])),torch=torch.__version__,torchvision=torchvision.__version__,cuda=torch.version.cuda,available=torch.cuda.is_available())))"
        result = subprocess.run([str(runtime_python(root)), "-I", "-c", command], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        info = json.loads(result.stdout)
        dependency_code = "import importlib.metadata,json; print(json.dumps({n:importlib.metadata.version(n) for n in ['PySide6','Pillow','shiboken6','PySide6_Essentials','PySide6_Addons']}))"
        dependencies = subprocess.run([str(runtime_python(root)), "-I", "-c", dependency_code], capture_output=True, text=True, timeout=30, check=True)
        installed = json.loads(dependencies.stdout)
        locked = dict(line.strip().split("==") for line in (source / "configs/requirements.lock").read_text().splitlines() if line.strip())
        info["dependencies_match"] = all(installed.get(name) == value for name, value in locked.items())
        try:
            driver = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], capture_output=True, text=True, timeout=10, check=True).stdout.splitlines()[0].strip()
            info["driver"] = driver
            info["driver_supported"] = tuple(map(int, driver.split("."))) >= tuple(map(int, expected["minimum_driver"].split(".")))
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            info["driver_supported"] = False
        info["environment_matches"] = (info["dependencies_match"] and info["python"] == expected["python"] and info["torch"] == expected["torch"] and info["torchvision"] == expected["torchvision"])
        info["cuda_ready"] = bool(info["available"] and info["cuda"] and "+cpu" not in info["torch"] and info["driver_supported"])
        info["ready"] = info["environment_matches"] and (info["cuda_ready"] or allow_cpu is True)
        info["selected_device"] = "cuda:0" if info["cuda_ready"] else ("cpu" if allow_cpu is True else None)
        return info
    except Exception as error:
        return {"ready": False, "error": str(error)}
