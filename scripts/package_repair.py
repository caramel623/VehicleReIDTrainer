"""Code-only repair ZIP for an existing v0.1.1 installation.

The environment manifest and all user/runtime data are deliberately excluded.
"""
from pathlib import Path
import zipfile
root=Path(__file__).resolve().parents[1]
version=(root / "VERSION").read_text().strip()
output=root / "dist" / f"VehicleReIDTrainer-repair-v{version}-win64.zip"
paths=[root / "dist/VehicleReIDTrainer.exe",root / "VERSION",root / "docs/REPAIR_INSTALL.md"]
paths+=sorted((root / "app").rglob("*.py"))
with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
    for path in paths:
        archive.write(path,"VehicleReIDTrainer.exe" if path.suffix==".exe" else path.relative_to(root).as_posix())
print(output)
