$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name VehicleReIDTrainer --hidden-import tkinter --hidden-import tkinter.scrolledtext --hidden-import app.services.installer --hidden-import app.services.environment launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Launcher build failed' }
