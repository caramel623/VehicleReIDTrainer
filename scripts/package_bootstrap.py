from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text().strip()
output = root / "dist" / f"VehicleReIDTrainer-bootstrap-v{version}-win64.zip"
paths = [root / "dist/VehicleReIDTrainer.exe", root / "VERSION", root / "README.md", root / "configs/environment.json", root / "configs/requirements.lock"]
paths += list((root / "app").rglob("*.py")) + list((root / "updater").rglob("*.py")) + list((root / "docs").glob("*.md"))
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in paths:
        archive.write(path, "VehicleReIDTrainer.exe" if path.suffix == ".exe" else path.relative_to(root).as_posix())
print(output)
