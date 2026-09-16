import csv
import json
from pathlib import Path
import pytest
from PIL import Image
from app.services.dataset import validate, prepare


def write_csv(path, records, fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields or list(records[0]))
        writer.writeheader();writer.writerows(records)


@pytest.fixture
def exported(tmp_path):
    root=tmp_path / "export"; (root / "reid_crops").mkdir(parents=True)
    records=[]
    for i in range(4):
        relative=f"reid_crops/{i:08}.png"
        Image.new("RGB",(20,20)).save(root / relative)
        records.append(dict(image_id=i,vehicle_id=i//2,reid_crop=relative,plate_mask_bbox={"x1":2,"y1":2,"x2":8,"y2":8},sha256="original-image-hash",split="train" if i<2 else "val"))
    write_csv(root / "metadata/images.csv",[{**r,"plate_mask_bbox":json.dumps(r["plate_mask_bbox"])} for r in records])
    write_csv(root / "metadata/vehicles.csv",[{"vehicle_id":0},{"vehicle_id":1}])
    write_csv(root / "metadata/labels.csv",[{"image_id":r["image_id"],"vehicle_id":r["vehicle_id"]} for r in records])
    (root / "metadata/manifest.jsonl").write_text("\n".join(json.dumps(r) for r in records),encoding="utf-8")
    for split in ("train","val","test"):
        write_csv(root / "splits" / f"{split}.csv",[{k:r[k] for k in ("image_id","vehicle_id","reid_crop")} for r in records if r["split"]==split],fields=["image_id","vehicle_id","reid_crop"])
    (root / "export_state.json").write_text('{"complete":true}')
    return root


def test_exporter_schema_and_original_hash(exported,tmp_path):
    before=(exported / "metadata/images.csv").read_bytes()
    report=validate(exported)
    assert report["valid"],report
    assert report["schema"]=="DatasetManager"
    assert not report["event_leakage_checked"] and not report["training_ready"]
    assert report["warnings"]
    assert prepare(exported,tmp_path / "cache")["fingerprint"]==report["fingerprint"]
    assert (exported / "metadata/images.csv").read_bytes()==before


def test_mask_bounds_rejected(exported):
    p=exported / "metadata/images.csv";p.write_text(p.read_text(encoding="utf-8-sig").replace('""x2"": 8','""x2"": 99'),encoding="utf-8-sig")
    assert not validate(exported)["valid"]


def test_incomplete_export_rejected(exported):
    (exported / "export_state.json").write_text('{"complete":false}')
    assert "Dataset export is incomplete" in validate(exported)["errors"]


def test_missing_schema_field_is_actionable(exported):
    p=exported / "metadata/images.csv"
    p.write_text(p.read_text(encoding="utf-8-sig").replace("reid_crop,","unknown_column,"),encoding="utf-8-sig")
    report=validate(exported)
    assert not report["valid"] and "metadata/images.csv" in report["errors"][0]
    assert "path" in report["errors"][0]


def test_split_path_mismatch_rejected(exported):
    p=exported / "splits/train.csv";p.write_text(p.read_text(encoding="utf-8-sig").replace("reid_crops/","vehicle_crops/"),encoding="utf-8-sig")
    assert any("Split metadata mismatch" in error for error in validate(exported)["errors"])
