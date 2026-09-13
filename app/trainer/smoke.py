"""Synthetic training process with explicit CPU opt-in; not a Re-ID accuracy trainer."""
import argparse
import json
from pathlib import Path
import traceback
from app.services.common import read_json, write_json
from app.services.environment import select_device


def run(run_dir: Path, resume: bool = False):
    import torch
    config = read_json(run_dir / "config.json")
    device = select_device(torch, config.get("device", 0), config.get("allow_cpu", False))
    write_json(run_dir / "device.json", {"actual_device": str(device), "allow_cpu": config.get("allow_cpu", False)})
    steps = config.get("steps", 20)
    if not isinstance(steps, int) or not 1 <= steps <= 10000:
        raise ValueError("steps must be 1..10000")
    torch.manual_seed(42)
    model = torch.nn.Sequential(torch.nn.Linear(16, 32), torch.nn.ReLU(), torch.nn.Linear(32, 4)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=10)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    start, best = 0, float("inf")
    checkpoint = run_dir / "checkpoints/last.pt"
    checkpoint.parent.mkdir(exist_ok=True)
    if resume:
        state = torch.load(checkpoint, map_location=device, weights_only=True)
        if state["dataset_fingerprint"] != "synthetic-v1" or state["config"] != config:
            raise ValueError("Checkpoint/config mismatch")
        model.load_state_dict(state["model"]); optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"]); scaler.load_state_dict(state["scaler"])
        start, best = state["epoch"], state["best_metric"]
    for epoch in range(start, steps):
        if (run_dir / "stop.request").exists():
            write_json(run_dir / "status.json", {"state": "STOPPED", "epoch": epoch}); return
        x = torch.randn(32, 16, device=device)
        y = torch.randint(0, 4, (32,), device=device)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            loss = torch.nn.functional.cross_entropy(model(x), y)
        scaler.scale(loss).backward(); scaler.step(optimizer); scaler.update(); scheduler.step()
        value = loss.item(); best = min(best, value)
        torch.save(dict(model=model.state_dict(), optimizer=optimizer.state_dict(), scheduler=scheduler.state_dict(), scaler=scaler.state_dict(), epoch=epoch+1, best_metric=best, config=config, dataset_fingerprint="synthetic-v1"), checkpoint.with_suffix(".tmp"))
        checkpoint.with_suffix(".tmp").replace(checkpoint)
        with (run_dir / "metrics.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"epoch": epoch+1, "loss": value}) + "\n")
        write_json(run_dir / "status.json", {"state": "RUNNING", "epoch": epoch+1, "loss": value})
    write_json(run_dir / "status.json", {"state": "COMPLETED", "epoch": steps})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        run(args.run, args.resume)
    except Exception as error:
        import sys
        oom = "out of memory" in str(error).lower()
        write_json(args.run / "status.json", {"state": "FAILED", "error": "CUDA OUT OF MEMORY: reduce batch/input size or enable gradient accumulation" if oom else str(error)})
        traceback.print_exc(); sys.exit(1)


if __name__ == "__main__":
    main()
