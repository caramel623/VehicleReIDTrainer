from pathlib import Path
import hashlib
import json
import zipfile


def build(root: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    version = (root / "VERSION").read_text().strip()
    paths = [root / "VERSION", root / "configs/environment.json", root / "configs/requirements.lock"]
    paths += sorted((root / "app").rglob("*.py"))
    files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    package = output / "VehicleReIDTrainer-update.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(root).as_posix())
    metadata = dict(version=version, package_sha256=hashlib.sha256(package.read_bytes()).hexdigest(), files=files)
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (output / "SHA256SUMS").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in (package, manifest)), encoding="utf-8")
    return package, metadata


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    build(root, root / "dist/update")
