"""Release staging and atomic activation; no live app replacement."""
from pathlib import Path
import argparse
import json
import re
import sys
import urllib.request
import zipfile

# Executable script must work from either the installation or a release directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.common import contained, digest, read_json, write_json


def version(value: str):
    if not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("Only stable semantic versions supported")
    return tuple(map(int, value.lstrip("v").split(".")))


def latest(repo: str):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid GitHub repository")
    request = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest", headers={"Accept": "application/vnd.github+json", "User-Agent": "VehicleReIDTrainer"})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    version(release["tag_name"])
    return release


def download(repo: str, release: dict, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    for name in ("VehicleReIDTrainer-update.zip", "manifest.json", "SHA256SUMS"):
        url = assets[name]
        if not url.startswith(f"https://github.com/{repo}/releases/download/"):
            raise ValueError("Unexpected release asset origin")
        with urllib.request.urlopen(url, timeout=60) as response, (destination / (name + ".part")).open("wb") as stream:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > 100 * 1024 * 1024:
                    raise ValueError("Update exceeds Phase 1 size limit")
                stream.write(block)
        (destination / (name + ".part")).replace(destination / name)
    sums = dict(line.split(maxsplit=1)[::-1] for line in (destination / "SHA256SUMS").read_text().splitlines())
    for name in ("VehicleReIDTrainer-update.zip", "manifest.json"):
        if digest(destination / name) != sums.get(name):
            raise ValueError("Release SHA256 mismatch")
    metadata = read_json(destination / "manifest.json")
    if version(metadata["version"]) != version(release["tag_name"]):
        raise ValueError("Release version mismatch")
    return destination / "VehicleReIDTrainer-update.zip", metadata


def stage(root: Path, package: Path, metadata: dict) -> Path:
    version(metadata["version"])
    if digest(package) != metadata["package_sha256"]:
        raise ValueError("Package SHA256 mismatch")
    target = root / "releases" / metadata["version"]
    if target.exists():
        raise ValueError("Release directory already exists")
    allowed = metadata["files"]
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != len(set(n.casefold() for n in names)) or set(names) != set(allowed):
            raise ValueError("Archive/manifest mismatch")
        if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
            raise ValueError("Expanded update too large")
        for info in archive.infolist():
            name = info.filename
            contained(target, name)
            if not (name.startswith("app/") or name.startswith("configs/") or name == "VERSION"):
                raise ValueError("Payload outside app/config allowlist")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Symlink forbidden")
        for name in names:
            output = contained(target, name)
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, output.open("wb") as sink:
                import shutil
                shutil.copyfileobj(source, sink)
            if digest(output) != allowed[name]:
                raise ValueError("File hash mismatch; active version unchanged")
    if (target / "VERSION").read_text().strip() != metadata["version"]:
        raise ValueError("Version file mismatch")
    return target


def activate(root: Path, target: Path, verify=lambda p: None):
    target = target.resolve()
    if target.parent != (root / "releases").resolve():
        raise ValueError("Invalid release target")
    active_path = root / "state/active.json"
    old = read_json(active_path) if active_path.exists() else {"path": "."}
    current = root if old["path"] == "." else contained(root, old["path"])
    if read_json(current / "configs/environment.json") != read_json(target / "configs/environment.json") or (current / "configs/requirements.lock").read_bytes() != (target / "configs/requirements.lock").read_bytes():
        raise ValueError("Environment changes require Phase 4 isolated runtime migration")
    verify(target)  # Exceptions leave the old active pointer untouched.
    write_json(root / "state/previous.json", old)
    write_json(active_path, {"path": target.relative_to(root.resolve()).as_posix()})


def rollback(root: Path):
    previous = read_json(root / "state/previous.json")
    target = root if previous["path"] == "." else contained(root, previous["path"])
    if not (target / "app/main.py").is_file():
        raise ValueError("Previous release missing")
    write_json(root / "state/active.json", previous)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    # GUI does not expose installation until an exit/wait handshake is implemented.
    if (args.root / "state/gui.lock").exists():
        raise RuntimeError("Close GUI before update; remove stale lock only after verifying GUI exited")
    (args.root / "logs").mkdir(exist_ok=True)
    import logging
    logging.basicConfig(filename=args.root / "logs/updater.log", level=logging.INFO)
    try:
        if args.rollback:
            rollback(args.root)
        else:
            target = stage(args.root, args.package, read_json(args.manifest))
            def verify(path):
                import subprocess
                subprocess.run([str(args.root / "runtime/python.exe"), "-m", "compileall", "-q", str(path / "app")], check=True)
            activate(args.root, target, verify)
        logging.info("Update transaction completed")
    except Exception:
        logging.exception("Update failed; inspect active pointer")
        raise


if __name__ == "__main__":
    main()
