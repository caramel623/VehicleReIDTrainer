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


def require_fields(record: dict, fields, context: str):
    missing = [key for key in fields if key not in record or record[key] is None]
    if missing:
        raise ValueError(f"{context}: missing required columns/fields: {', '.join(missing)}")


def load_images(root: Path):
    source = rows(root / "metadata/images.csv")
    if not source:
        raise ValueError("metadata/images.csv: no image records")
    exporter = "reid_crop" in source[0] and "path" not in source[0]
    result = []
    for index, record in enumerate(source, 2):
        fields = ("image_id", "vehicle_id", "reid_crop", "plate_mask_bbox", "split") if exporter else ("image_id", "vehicle_id", "path", "plate_masked", "event_id")
        require_fields(record, fields, f"metadata/images.csv row {index}")
        item = dict(record)
        if exporter:
            item["path"] = record["reid_crop"]
            try:
                bbox = json.loads(record["plate_mask_bbox"] or "null")
            except ValueError as error:
                raise ValueError(f"metadata/images.csv row {index}: invalid plate_mask_bbox JSON") from error
            item["_bbox"] = bbox
            item["plate_masked"] = "true" if isinstance(bbox, dict) and all(k in bbox for k in ("x1","y1","x2","y2")) else "false"
            item["event_id"] = record.get("event_id", "")
        result.append(item)
    return result, exporter


def validate(root: Path) -> dict:
    from PIL import Image
    errors = []
    required = ["metadata/images.csv", "metadata/vehicles.csv", "metadata/labels.csv", "metadata/manifest.jsonl", "splits/train.csv", "splits/val.csv", "splits/test.csv"]
    missing = [p for p in required if not (root / p).is_file()]
    if missing:
        return {"valid": False, "errors": [f"Missing {p}" for p in missing]}
    try:
        images, exporter = load_images(root)
        warnings = []
        event_available = all(row.get("event_id", "").strip() for row in images)
        if exporter:
            warnings.append("Exporter sha256 describes original images; crop hashes are computed locally for fingerprinting, not compared to original hashes.")
            if not event_available:
                warnings.append("event_id unavailable: adjacent-event leakage is not verified. Identity split leakage is still checked.")
        for optional in ("export_config.json", "export_state.json"):
            if (root / optional).is_file():
                required.append(optional)
        if (root / "export_state.json").is_file():
            state = json.loads((root / "export_state.json").read_text(encoding="utf-8-sig"))
            if state.get("complete") is not True:
                errors.append("Dataset export is incomplete")
        vehicles = [r["vehicle_id"] for r in rows(root / required[1])]
        labels_list = rows(root / required[2])
        labels = {r["image_id"]: r["vehicle_id"] for r in labels_list}
        manifests = [json.loads(s) for s in (root / required[3]).read_text(encoding="utf-8-sig").splitlines() if s.strip()]
        for record in manifests:
            require_fields(record, ("image_id", "reid_crop", "vehicle_id", "plate_mask_bbox", "split") if exporter else ("image_id", "path", "sha256"), "metadata/manifest.jsonl")
        entries = {str(r["image_id"]): r for r in manifests}
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
            if not exporter and not row["event_id"].strip():
                errors.append(f"Missing event: {key}")
            if row["plate_masked"].lower() not in ("true", "1"):
                errors.append(f"Plate mask missing: {key}")
            path = contained(root, relative)
            if not path.is_relative_to((root / "reid_crops").resolve()):
                raise ValueError("Image outside reid_crops")
            if not path.is_file():
                errors.append(f"Missing image: {key}"); continue
            actual = digest(path)
            entry = entries.get(key, {})
            if exporter:
                if (entry.get("reid_crop") != relative or str(entry.get("vehicle_id")) != identity
                    or entry.get("plate_mask_bbox") != row["_bbox"] or entry.get("split") != row["split"]):
                    errors.append(f"Manifest mismatch: {key}")
            elif entry.get("sha256") != actual or entry.get("path") != relative:
                errors.append(f"Manifest mismatch: {key}")
            fingerprint.update((relative + actual).encode())
            try:
                with Image.open(path) as image:
                    if exporter and row["plate_masked"] == "true":
                        box = row["_bbox"]
                        coordinates = [box[k] for k in ("x1","y1","x2","y2")]
                        if (any(type(v) not in (int, float) for v in coordinates)
                            or not (0 <= coordinates[0] < coordinates[2] <= image.width and 0 <= coordinates[1] < coordinates[3] <= image.height)):
                            errors.append(f"Invalid plate mask bounding box: {key}")
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
                if exporter and (lookup[key]["split"] != split or item.get("reid_crop") != lookup[key]["path"] or item.get("vehicle_id") != lookup[key]["vehicle_id"]):
                    errors.append(f"Split metadata mismatch: {key}")
                for field, seen in (("vehicle_id", identity_split), ("event_id", event_split)):
                    value = lookup[key][field]
                    if field == "event_id" and not value:
                        continue
                    if value in seen and seen[value] != split:
                        errors.append(f"{field} leakage")
                    seen[value] = split
        if assigned != ids or not images or not stats["train"]:
            errors.append("Empty dataset/train or incomplete splits")
        return {"valid": not errors, "errors": errors, "images": len(images), "vehicles": len(vehicles), "splits": stats, "fingerprint": fingerprint.hexdigest(), "schema": "DatasetManager" if exporter else "trainer-v1", "warnings": warnings, "event_leakage_checked": event_available, "training_ready": not errors and event_available}
    except KeyError as error:
        return {"valid": False, "errors": [f"Dataset metadata is missing required field: {error.args[0]}"]}
    except (ValueError, OSError, TypeError) as error:
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
    files += [contained(source, row["path"]) for row in load_images(source)[0]]
    files += [source / name for name in ("export_config.json", "export_state.json") if (source / name).is_file()]
    for path in files:
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    copied = validate(destination)
    if not copied["valid"] or copied["fingerprint"] != result["fingerprint"]:
        raise ValueError("Cache verification failed; incomplete cache preserved for inspection")
    return copied
