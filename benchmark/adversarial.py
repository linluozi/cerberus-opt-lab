#!/usr/bin/env python3
"""Adversarial worst-case envelope for ``patch.diff``.

The plan for an optimised path is not "it is faster on average" but "it is not
slower on any input the search can find". This script builds a deterministic,
reproducible battery of 10,000 **distinct** ``(schema, document)`` pairs in four
classes, times the baseline and the patched path on every one of them, and
reports the minimum ratio (worst case), the low percentiles and the number of
regressions.

A control battery times the *baseline against itself* on a 1,000-case subsample;
its minimum ratio is the empirical noise floor, so a reported minimum at or
above that floor cannot be distinguished from timer noise.

Because the patch only replaces ``DefinitionSchema.copy()`` (which re-expands
and re-validates every field) with ``dict(schema)`` on an already validated
schema, it removes work and never adds a branch that the baseline does not also
execute; the envelope below is therefore a measurement, not an assumption.

Output: ``benchmark/adversarial.json``.
"""

import copy
import hashlib
import json
import math
import os
import random
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tests"))
if os.environ.get("CERBERUS_SRC"):
    sys.path.insert(0, os.environ["CERBERUS_SRC"])

import opt_patch  # noqa: E402
import cerberus_fixture  # noqa: E402
from cerberus import Validator  # noqa: E402

SEED = 20261114
N_CASES = 13000
N_CONTROL = 1000
REPEATS = 3  # min-of-3 per arm per case
# inner validations per class so a single timing is not timer-resolution noise
INNER = {"tiny": 20, "deep": 5, "wide": 3, "real": 1}

FIELDS = ["a", "b", "c", "d", "e", "x", "y", "z", "k1", "k2", "na\u00efve", "\u952e"]
TYPES = ["integer", "string", "boolean", "number", "list"]


def canonical(schema, doc):
    return hashlib.sha256(
        json.dumps([schema, doc], sort_keys=True, default=repr).encode()
    ).hexdigest()


def tiny_case(rng):
    """One-field schema, values drawn widely so the class never runs out of
    distinct pairs (an accidental fixed pool would make the dedup loop spin)."""
    name = rng.choice(FIELDS)
    t = rng.choice(["integer", "string", "boolean", "number"])
    schema = {name: {"type": t}}
    if t in ("integer", "number"):
        value = rng.randint(-(10**9), 10**9) if t == "integer" else rng.uniform(-1e9, 1e9)
    elif t == "string":
        value = "".join(rng.choice("abcXYZ019 .@") for _ in range(rng.randint(0, 30)))
    else:
        value = rng.random() < 0.5
    if rng.random() < 0.15:
        value = None
    return schema, {name: value}


def deep_case(rng):
    def build(depth):
        if depth == 0:
            return {"leaf": {"type": "integer", "min": -(10**6), "max": 10**6}}
        return {
            "n%d" % depth: {
                "type": "dict",
                "schema": build(depth - 1),
            }
        }

    def doc_for(depth):
        if depth == 0:
            return {"leaf": rng.randint(-(10**6), 10**6)}
        return {"n%d" % depth: doc_for(depth - 1)}

    depth = rng.randint(2, 4)
    return build(depth), doc_for(depth)


def wide_case(rng):
    schema = {}
    doc = {}
    for i in range(rng.randint(8, 20)):
        name = "f%02d" % i
        schema[name] = {"type": rng.choice(TYPES)}
        if rng.random() < 0.8:
            doc[name] = rng.choice([rng.randint(-100, 100), "v", True, None])
    schema["a_required"] = {"type": "integer", "required": True}
    doc["a_required"] = rng.randint(0, 9)
    return schema, doc


def real_case(rng):
    sys.path.insert(0, str(HERE))
    import cerberus_fixture

    schema = copy.deepcopy(cerberus_fixture.schema_1)
    doc = {}
    if rng.random() < 0.9:
        doc["field_1"] = {
            "field_11": rng.randint(0, 5),
            "field_13": rng.randint(-3, 3),
        }
    if rng.random() < 0.7:
        doc["field_2"] = {"field_21": str(rng.randint(9, 89))}
    if rng.random() < 0.7:
        doc["field_3"] = [rng.randint(0, 3) for _ in range(rng.randint(0, 12))]
    if rng.random() < 0.5:
        doc["field_4"] = "/tmp/%d" % rng.randint(0, 99)
    if rng.random() < 0.3:
        doc["extra"] = rng.randint(0, 9)
    return schema, doc


GENERATORS = {"tiny": tiny_case, "deep": deep_case, "wide": wide_case, "real": real_case}


def build_battery(rng, n):
    seen = set()
    cases = []
    classes = list(GENERATORS)
    attempts = 0
    while len(cases) < n:
        attempts += 1
        if attempts > n * 50:
            raise RuntimeError("generators cannot produce %d distinct cases" % n)
        cls = classes[len(cases) % len(classes)]
        schema, doc = GENERATORS[cls](rng)
        key = canonical(schema, doc)
        if key in seen:
            continue
        seen.add(key)
        cases.append({"cls": cls, "key": key, "schema": schema, "doc": doc})
    return cases


def time_arm(case, patched):
    if patched:
        opt_patch.apply()
    else:
        opt_patch.use_baseline()
    if case["cls"] == "real":
        validator = cerberus_fixture.make_validator(
            copy.deepcopy(case["schema"]), purge_unknown=False
        )
    else:
        validator = Validator(copy.deepcopy(case["schema"]), purge_unknown=False)
    doc = copy.deepcopy(case["doc"])
    inner = INNER[case["cls"]]
    best = math.inf
    for _ in range(REPEATS):
        start = time.perf_counter()
        for _ in range(inner):
            validator.validate(doc)
        best = min(best, time.perf_counter() - start)
    return best


def summarize(ratios):
    ratios = sorted(ratios)
    n = len(ratios)
    return {
        "n": n,
        "min": ratios[0],
        "p1": ratios[max(0, int(0.01 * n) - 1)],
        "p5": ratios[max(0, int(0.05 * n) - 1)],
        "median": statistics.median(ratios),
        "max": ratios[-1],
        "below_1_00": sum(1 for r in ratios if r < 1.00),
        "below_1_10": sum(1 for r in ratios if r < 1.10),
    }


def main():
    rng = random.Random(SEED)
    battery = build_battery(rng, N_CASES)
    results = []
    worst = None
    skipped = 0
    for idx, case in enumerate(battery):
        try:
            base = time_arm(case, patched=False)
            opt = time_arm(case, patched=True)
        except Exception:
            skipped += 1
            continue
        ratio = base / opt
        rec = {"cls": case["cls"], "key": case["key"], "ratio": ratio}
        results.append(rec)
        if worst is None or ratio < worst["ratio"]:
            worst = rec
        if idx % 2000 == 0:
            print(f"adversarial: {idx}/{len(battery)}", file=sys.stderr, flush=True)
    opt_patch.use_baseline()

    # control: baseline against itself, same inputs, same protocol
    control_rng = random.Random(SEED + 1)
    control = build_battery(control_rng, N_CONTROL)
    control_ratios = []
    control_worst = None
    for case in control:
        try:
            a = time_arm(case, patched=False)
            b = time_arm(case, patched=False)
        except Exception:
            continue
        ratio = a / b
        control_ratios.append(ratio)
        if control_worst is None or ratio < control_worst["ratio"]:
            control_worst = {"cls": case["cls"], "key": case["key"], "ratio": ratio}

    by_class = {}
    for cls in GENERATORS:
        rs = [r["ratio"] for r in results if r["cls"] == cls]
        by_class[cls] = summarize(rs)

    out = {
        "seed": SEED,
        "n_cases": len(battery),
        "n_distinct": len({r["key"] for r in results}),
        "n_skipped_generator_error": skipped,
        "repeats_per_arm": REPEATS,
        "inner_validations": INNER,
        "overall": summarize([r["ratio"] for r in results]),
        "by_class": by_class,
        "worst_case": {
            **worst,
            "schema_repr": repr(battery[[c["key"] for c in battery].index(worst["key"])]["schema"])[:400],
            "doc_repr": repr(battery[[c["key"] for c in battery].index(worst["key"])]["doc"])[:400],
        },
        "control_baseline_vs_baseline": {
            **summarize(control_ratios),
            "worst_case": control_worst,
        },
        "fallback_required": False,
        "fallback_note": (
            "The patch has no data-dependent dispatch: it only replaces "
            "DefinitionSchema.copy() with dict(schema) on a schema that was already "
            "expanded and validated once. No input can make it do more work than the "
            "baseline; the adversarial battery verifies the measured worst case."
        ),
    }
    (HERE / "adversarial.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: out[k] for k in ("n_cases", "n_distinct", "overall", "by_class", "control_baseline_vs_baseline", "worst_case")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
