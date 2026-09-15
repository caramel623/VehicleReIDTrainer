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


def capture_progress(command, timeout, on_line, on_wait, interval=10):
    """Drain child output continuously while enforcing one total deadline."""
    from collections import deque
    import queue
    import time
    messages = queue.Queue()
    tail = deque(maxlen=200)
    started = time.monotonic()
    deadline = started + timeout
    next_heartbeat = started + interval
    with start_process(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace") as process:
        def read_output():
            try:
                for line in process.stdout:
                    messages.put(line.rstrip())
            finally:
                messages.put(None)
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise subprocess.TimeoutExpired(list(map(str, command)), timeout, output="\n".join(tail))
                if now >= next_heartbeat:
                    on_wait(int(now - started))
                    next_heartbeat = now + interval
                try:
                    line = messages.get(timeout=max(0.001, min(deadline - now, next_heartbeat - now, 0.2)))
                except queue.Empty:
                    continue
                if line is None:
                    break
                tail.append(line)
                on_line(line)
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
            if process.returncode:
                raise RuntimeError(f"Verification process exited with code {process.returncode}: " + "\n".join(tail)[-4000:])
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            reader.join(timeout=2)
    return "\n".join(tail)
