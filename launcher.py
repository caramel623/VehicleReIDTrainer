"""Stable launcher: never uses sys.executable as the managed interpreter."""
from pathlib import Path
import json
import subprocess
import sys


def installation_root():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def main():
    root = installation_root()
    source = root
    pointer = root / "state/active.json"
    if pointer.exists():
        relative = json.loads(pointer.read_text())["path"]
        source = (root / relative).resolve()
        if not source.is_relative_to(root) or (source != root and source.parent != root / "releases"):
            raise ValueError("Invalid active release")
    python = root / "runtime/python.exe"
    if not python.exists() or (root / "state/environment-installing.json").exists():
        # tkinter belongs to the small frozen launcher; GUI dependencies need not exist yet.
        import tkinter as tk
        from tkinter import scrolledtext
        import queue
        import threading
        sys.path.insert(0, str(source))
        from app.services.installer import DependencyManager
        from app.services.environment import gpu_info
        window = tk.Tk(); window.title("VehicleReIDTrainer — Environment Setup"); window.geometry("780x500")
        tk.Label(window, text="Managed Python / CUDA PyTorch setup\n" + gpu_info()).pack()
        output = scrolledtext.ScrolledText(window); output.pack(fill="both", expand=True)
        events = queue.Queue()
        cpu_permission = tk.BooleanVar(value=False)
        consent = tk.Checkbutton(window, text="允許在 CUDA 無法使用時以 CPU 訓練（速度較慢）", variable=cpu_permission)
        consent.pack()
        def install():
            button.config(state="disabled")
            consent.config(state="disabled")
            allow_cpu = bool(cpu_permission.get())
            def work():
                try:
                    (root / "logs").mkdir(exist_ok=True)
                    with (root / "logs/environment.log").open("a", encoding="utf-8") as log:
                        def emit(message):
                            log.write(message + "\n"); log.flush(); events.put(message)
                        DependencyManager(root, source, emit, allow_cpu=allow_cpu).install()
                    events.put("Setup complete. Close this window and launch again.")
                except Exception as error:
                    events.put("FAILED: " + str(error))
                events.put(None)
            threading.Thread(target=work, daemon=True).start()
        button = tk.Button(window, text="Install Environment", command=install); button.pack()
        def poll():
            while not events.empty():
                message = events.get()
                if message is None: button.config(state="normal"); consent.config(state="normal")
                else: output.insert("end", message + "\n"); output.see("end")
            window.after(100, poll)
        window.protocol("WM_DELETE_WINDOW", lambda: window.destroy() if str(button['state']) != 'disabled' else None)
        poll(); window.mainloop(); return
    subprocess.Popen([str(python), "-m", "app.main", "--root", str(root)], cwd=source)


if __name__ == "__main__":
    main()
