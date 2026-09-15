import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from pathlib import Path
from PySide6.QtWidgets import QApplication
from app.gui.window import Window


def test_gui_no_cuda_stays_responsive(tmp_path, monkeypatch):
    from app.services import environment
    monkeypatch.setattr(environment,"check",lambda *a, **kw: {"ready":False})
    monkeypatch.setattr(environment,"gpu_info",lambda: "Unavailable")
    application=QApplication.instance() or QApplication([])
    window=Window(tmp_path,Path(__file__).resolve().parents[1])
    for worker in list(window.workers):worker.wait(5000)
    application.processEvents()
    assert window.stack.count()==9
    assert not window.start_button.isEnabled()
    assert "disabled" in window.dashboard.text()
    window.close()
