#!/usr/bin/env python3
"""Time ``Validator.validate()`` on upstream's own benchmark corpus.

Usage::

    python benchmark/bench.py --impl baseline  --docs <overall_documents_1.json> --out benchmark/baseline.json
    python benchmark/bench.py --impl optimized --docs <overall_documents_1.json> --out benchmark/optimized.json

The ``optimized`` arm applies the runtime form of ``patch.diff``
(``benchmark/opt_patch.py``) to an unmodified upstream install.

Timing: ``time.perf_counter()``; per scale 3 warm-ups and 5 timed samples;
every sample is written to ``benchmark/raw/<impl>-<scale>-<i>.json``.
"""

import argparse
import importlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SCALES = {"small": 500, "medium": 2000, "large": 10000}
WARMUP = 3
SAMPLES = 5
SEED = 20261114  # no randomness is used; recorded for the run manifest


def cpu_model():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def mem_total():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def import_impl(impl, src):
    if src:
        sys.path.insert(0, src)
    importlib.import_module("cerberus")
    if impl == "optimized":
        import opt_patch

        opt_patch.apply()
    return importlib.import_module("cerberus_fixture")


def time_scale(fixture, validator, docs, n):
    for _ in range(WARMUP):
        for doc in docs[:n]:
            validator.validate(doc)
    samples = []
    for i in range(SAMPLES):
        start = time.perf_counter()
        for doc in docs[:n]:
            validator.validate(doc)
        samples.append(time.perf_counter() - start)
    return samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", choices=["baseline", "optimized"], required=True)
    ap.add_argument("--docs", required=True, help="path to overall_documents_1.json")
    ap.add_argument("--src", default=None, help="optional checkout of cerberus to import")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    fixture = import_impl(args.impl, args.src)
    docs = fixture.load_documents(args.docs)
    validator = fixture.init_validator()
    assert len(docs) >= max(SCALES.values()), len(docs)

    raw_dir = HERE / "raw"
    raw_dir.mkdir(exist_ok=True)
    scales = {}
    for name, n in SCALES.items():
        samples = time_scale(fixture, validator, docs, n)
        for i, s in enumerate(samples):
            (raw_dir / f"{args.impl}-{name}-{i}.json").write_text(
                json.dumps(
                    {
                        "impl": args.impl,
                        "scale": name,
                        "n_docs": n,
                        "sample": i,
                        "seconds": s,
                        "seed": SEED,
                    },
                    indent=2,
                )
                + "\n"
            )
        scales[name] = {
            "n_docs": n,
            "median": statistics.median(samples),
            "p25": statistics.quantiles(samples, n=4)[0],
            "p75": statistics.quantiles(samples, n=4)[2],
            "min": min(samples),
            "max": max(samples),
            "rel_stdev": (
                statistics.stdev(samples) / statistics.mean(samples)
                if len(samples) > 1
                else 0.0
            ),
            "samples": samples,
        }
        print(
            f"{args.impl:9s} {name:7s} n={n:6d} median={scales[name]['median']:.4f}s "
            f"p25={scales[name]['p25']:.4f}s p75={scales[name]['p75']:.4f}s"
        )

    try:
        git = subprocess.run(
            ["git", "-C", str(HERE), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except Exception:
        git = ""
    out = {
        "impl": args.impl,
        "seed": SEED,
        "warmup": WARMUP,
        "samples": SAMPLES,
        "scales": scales,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu": cpu_model(),
        "mem_total": mem_total(),
        "command": " ".join(sys.argv),
        "repo_commit": git,
        "env": {k: os.environ.get(k) for k in ("PYTHONHASHSEED",) if os.environ.get(k)},
    }
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
