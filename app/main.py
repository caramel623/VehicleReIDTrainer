import argparse
from pathlib import Path
import logging
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.append(str(root))  # Stable updater lives in installation root.
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(exist_ok=True)
    logging.basicConfig(filename=root / "logs/app.log", level=logging.INFO)
    # Exclusive lock: updates refuse while a GUI instance is alive.
    lock = root / "state/gui.lock"
    try:
        handle = lock.open("x")
    except FileExistsError:
        raise RuntimeError("GUI already running or stale state/gui.lock; verify process before removing")
    try:
        import os
        handle.write(str(os.getpid())); handle.close()
        from PySide6.QtWidgets import QApplication
        from app.gui.window import Window
        application = QApplication(sys.argv)
        window = Window(root, Path(__file__).resolve().parents[1]); window.show()
        return application.exec()
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
