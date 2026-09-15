"""Standalone isolated import probe, with progress and timed stack diagnostics."""
import argparse
import faulthandler
import json
import sys


def progress(stage):
    print("PROGRESS " + stage, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--driver-supported", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    faulthandler.enable()
    faulthandler.dump_traceback_later(60, repeat=True)
    try:
        progress("Importing torch")
        import torch
        progress("Importing torchvision")
        import torchvision
        progress("Checking CUDA availability")
        available = torch.cuda.is_available()
        cuda_ready = bool(available and torch.version.cuda and "+cpu" not in torch.__version__ and args.driver_supported)
        device = "cuda:0" if cuda_ready else ("cpu" if args.allow_cpu else None)
        report = dict(python=".".join(map(str, sys.version_info[:3])), torch=torch.__version__,
                      torchvision=torchvision.__version__, cuda=torch.version.cuda,
                      available=available, selected_device=device)
        if args.self_test and device:
            progress("Matrix multiply self test on " + device)
            x = torch.randn(64, 64, device=device)
            y = x @ x
            if device.startswith("cuda"):
                torch.cuda.synchronize()
            if str(y.device) != device or not torch.isfinite(y).all().item():
                raise RuntimeError("Selected-device self test failed")
            report["self_test"] = "passed"
        else:
            report["self_test"] = "not_run"
        print("RESULT " + json.dumps(report), flush=True)
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
