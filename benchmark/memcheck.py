#!/usr/bin/env python3
"""Peak-RSS probe for gate G5.

Validates the first ``n`` documents of upstream's benchmark corpus once and
prints a checksum so a crashed/empty run is obvious. Run under
``/usr/bin/time -v`` for both arms::

    /usr/bin/time -v python benchmark/memcheck.py --impl baseline  --docs ... 
    /usr/bin/time -v python benchmark/memcheck.py --impl optimized --docs ...
"""

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", choices=["baseline", "optimized"], required=True)
    ap.add_argument("--docs", required=True)
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--src", default=None)
    args = ap.parse_args()

    if args.src:
        sys.path.insert(0, args.src)
    importlib.import_module("cerberus")
    if args.impl == "optimized":
        import opt_patch

        opt_patch.apply()
    fixture = importlib.import_module("cerberus_fixture")

    docs = fixture.load_documents(args.docs)[: args.n]
    validator = fixture.init_validator()
    accepted = 0
    for doc in docs:
        if validator.validate(doc):
            accepted += 1
    digest = hashlib.sha256(
        json.dumps([accepted, len(docs)], sort_keys=True).encode()
    ).hexdigest()[:16]
    print(f"accepted={accepted} n={len(docs)} digest={digest}")


if __name__ == "__main__":
    main()
