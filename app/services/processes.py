"""Launch managed Python without inheriting the frozen launcher's DLLs."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import threading

_DLL_LOCK = threading.RLock()


def child_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.upper() in {"PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE"}:
            env.pop(key)
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        base = Path(bundle).resolve()
        env["PATH"] = os.pathsep.join(
            part for part in env.get("PATH", "").split(os.pathsep)
            if part and not Path(part).resolve().is_relative_to(base)
        )
    env["PYTHONUTF8"] = "1"
    return env


@contextmanager
def external_dll_search():
    with _DLL_LOCK:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            yield
            return
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        setter = kernel.SetDllDirectoryW
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_int
        getter = kernel.GetDllDirectoryW
        getter.argtypes = [ctypes.c_uint, ctypes.c_wchar_p]
        getter.restype = ctypes.c_uint
        buffer = ctypes.create_unicode_buffer(32768)
        getter(len(buffer), buffer)
        if not setter(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            if not setter(buffer.value or None):
                raise ctypes.WinError(ctypes.get_last_error())


def start_process(command, **kwargs):
    kwargs.setdefault("env", child_environment())
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    with external_dll_search():
        return subprocess.Popen(list(map(str, command)), **kwargs)


def capture(command, timeout=60):
    with start_process(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", errors="replace") as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        if process.returncode:
            raise RuntimeError(f"Managed Python exited with code {process.returncode}: {stderr[-2000:]}")
        return stdout
