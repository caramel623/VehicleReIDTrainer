from collections import Counter
from pathlib import Path
import csv
import hashlib
import json
import shutil
from .common import contained, digest


def rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def validate(root: Path) -> dict:
    from PIL import Image
    errors = []
    required = ["metadata/images.csv", "metadata/vehicles.csv", "metadata/labels.csv", "metadata/manifest.jsonl", "splits/train.csv", "splits/val.csv", "splits/test.csv"]
    missing = [p for p in required if not (root / p).is_file()]
    if missing:
        return {"valid": False, "errors": [f"Missing {p}" for p in missing]}
    try:
        images = rows(root / required[0])
        vehicles = [r["vehicle_id"] for r in rows(root / required[1])]
        labels_list = rows(root / required[2])
        labels = {r["image_id"]: r["vehicle_id"] for r in labels_list}
        manifests = [json.loads(s) for s in (root / required[3]).read_text(encoding="utf-8-sig").splitlines() if s.strip()]
        entries = {r["image_id"]: r for r in manifests}
        ids, paths, counts = set(), set(), Counter()
        fingerprint = hashlib.sha256()
        for p in required:
            fingerprint.update((p + digest(root / p)).encode())
        for row in images:
            key, relative, identity = row["image_id"], row["path"], row["vehicle_id"]
            if not key or key in ids or relative.casefold() in paths:
                errors.append("Duplicate/empty image ID or path")
            ids.add(key); paths.add(relative.casefold()); counts[identity] += 1
            if not identity.strip() or identity not in vehicles or labels.get(key) != identity:
                errors.append(f"Invalid label: {key}")
            if not row["event_id"].strip():
                errors.append(f"Missing event: {key}")
            if row["plate_masked"].lower() not in ("true", "1"):
                errors.append(f"Plate mask missing: {key}")
            path = contained(root, relative)
            if not path.is_relative_to((root / "reid_crops").resolve()):
                raise ValueError("Image outside reid_crops")
            if not path.is_file():
                errors.append(f"Missing image: {key}"); continue
            actual = digest(path)
            if entries.get(key, {}).get("sha256") != actual or entries.get(key, {}).get("path") != relative:
                errors.append(f"Manifest mismatch: {key}")
            fingerprint.update((relative + actual).encode())
            try:
                with Image.open(path) as image:
                    image.verify()
            except Exception:
                errors.append(f"Corrupt image: {key}")
        if len(labels_list) != len(labels) or set(labels) != ids or len(manifests) != len(entries) or set(entries) != ids:
            errors.append("Label/manifest coverage or duplicates")
        if len(set(vehicles)) != len(vehicles) or any(not v.strip() for v in vehicles):
            errors.append("Invalid vehicle list")
        if any(counts[v] < 2 for v in vehicles):
            errors.append("Empty class or vehicle with only one sample")
        assigned, identity_split, event_split, stats = set(), {}, {}, {}
        lookup = {r["image_id"]: r for r in images}
        for split in ("train", "val", "test"):
            part = rows(root / "splits" / f"{split}.csv")
            stats[split] = len(part)
            for item in part:
                key = item["image_id"]
                if key not in lookup or key in assigned:
                    errors.append("Split duplicate or unknown image"); continue
                assigned.add(key)
                for field, seen in (("vehicle_id", identity_split), ("event_id", event_split)):
                    value = lookup[key][field]
                    if value in seen and seen[value] != split:
                        errors.append(f"{field} leakage")
                    seen[value] = split
        if assigned != ids or not images or not stats["train"]:
            errors.append("Empty dataset/train or incomplete splits")
        return {"valid": not errors, "errors": errors, "images": len(images), "vehicles": len(vehicles), "splits": stats, "fingerprint": fingerprint.hexdigest()}
    except (KeyError, ValueError, OSError) as error:
        return {"valid": False, "errors": [str(error)]}


def prepare(source: Path, destination: Path) -> dict:
    result = validate(source)
    if not result["valid"]:
        raise ValueError(result["errors"])
    if destination.exists() or destination.resolve().is_relative_to(source.resolve()):
        raise ValueError("Choose a new cache folder outside source")
    destination.mkdir(parents=True)
    # Copy only the validated contract, never arbitrary source files.
    files = [p for p in source.glob("metadata/*") if p.name in ("images.csv", "vehicles.csv", "labels.csv", "manifest.jsonl")]
    files += list(source.glob("splits/*.csv"))
    files += [contained(source, row["path"]) for row in rows(source / "metadata/images.csv")]
    for path in files:
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    copied = validate(destination)
    if not copied["valid"] or copied["fingerprint"] != result["fingerprint"]:
        raise ValueError("Cache verification failed; incomplete cache preserved for inspection")
    return copied
