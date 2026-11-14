#!/usr/bin/env python3
"""Byte-exact differential test: upstream ``validate()`` vs ``patch.diff``.

Every case is a ``(schema, document)`` pair. Cases are generated with a single
``random.Random(20261114)`` instance created *outside* the loop, then keyed by
``sha256`` of the canonical pair so the reported number is the number of
**distinct** inputs, not the loop count.

The two paths run in the same interpreter (``benchmark/opt_patch.py`` swaps the
class method), each on its own ``Validator`` instance so schema-validation
caches never cross-contaminate. The comparison is on
``sha256(json.dumps({result, errors, document}))`` -- not on types, lengths or a
prefix.
"""

import copy
import hashlib
import json
import math
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent / "benchmark"
sys.path.insert(0, str(BENCH))
if os.environ.get("CERBERUS_SRC"):
    sys.path.insert(0, os.environ["CERBERUS_SRC"])

import opt_patch  # noqa: E402
from cerberus import Validator  # noqa: E402

SEED = 20261114
TARGET_DISTINCT = 1200

FIELDS = ["a", "b", "c", "field_1", "field_2", "na\u00efve", "\u952e", "long_" + "x" * 40]
TYPES = ["integer", "float", "string", "boolean", "list", "dict", "number"]


def rand_schema(rng, depth=0):
    schema = {}
    for _ in range(rng.randint(1, 5)):
        name = rng.choice(FIELDS)
        rules = {"type": rng.choice(TYPES)}
        if rng.random() < 0.4:
            rules["required"] = True
        if rng.random() < 0.3:
            rules["nullable"] = True
        t = rules["type"]
        if t in ("integer", "float", "number"):
            lo = rng.choice([-(10**9), 0, 5])
            rules["min"] = lo
            rules["max"] = lo + rng.randint(0, 10**9)
        elif t == "string":
            rules["minlength"] = rng.randint(0, 3)
            rules["maxlength"] = rng.randint(3, 2000)
            if rng.random() < 0.3:
                rules["regex"] = rng.choice([r"^[a-z]+$", r"^[^@]+@[^@]+$", r"^[\s\S]*$"])
        elif t == "list" and rng.random() < 0.5:
            rules["schema"] = {"type": "integer"}
        elif t == "dict" and depth < 2 and rng.random() < 0.6:
            rules["schema"] = rand_schema(rng, depth + 1)
        schema[name] = rules
    return schema


def rand_value(rng, rules):
    t = rules["type"]
    roll = rng.random()
    if roll < 0.12:
        # boundary / deliberately mismatched values
        return rng.choice([None, math.nan, math.inf, "", [], {}, True, 0, -1])
    if roll < 0.2:
        return rng.choice(["\u00e9\u00e8\u00ea", "\u4e2d\u6587\u503c", "x" * 5000, 10**18, -(10**18)])
    if t == "integer":
        return rng.randint(-(10**6), 10**6)
    if t in ("float", "number"):
        return rng.uniform(-(10**6), 10**6)
    if t == "boolean":
        return rng.random() < 0.5
    if t == "list":
        return [rng.randint(-5, 5) for _ in range(rng.randint(0, 8))]
    if t == "dict":
        return {rng.choice(FIELDS): rng.randint(-5, 5) for _ in range(rng.randint(0, 4))}
    return "".join(rng.choice("abcXYZ019 @.") for _ in range(rng.randint(0, 40)))


def rand_doc(rng, schema):
    doc = {}
    for name, rules in schema.items():
        if rng.random() < 0.85:
            doc[name] = rand_value(rng, rules)
        elif rng.random() < 0.3:
            doc[name] = None
    if rng.random() < 0.2:
        doc["unknown_" + rng.choice("abc")] = rng.choice([1, "x", None])
    return doc


def edge_cases():
    long_str = "y" * 100_000
    deep = {"l1": {"l2": {"l3": {"l4": {"l5": 1}}}}}
    return [
        ({}, {}),
        ({"x": {"type": "string"}}, {"x": ""}),
        ({"x": {"type": "string"}}, {"x": None}),
        ({"x": {"type": "string", "nullable": True}}, {"x": None}),
        ({"x": {"type": "integer", "min": 0, "max": 0}}, {"x": 0}),
        ({"x": {"type": "string"}}, {"x": long_str}),
        ({"x": {"type": "string"}}, {"x": "\u4e2d\u6587" * 1000}),
        ({"x": {"type": "number"}}, {"x": math.nan}),
        ({"x": {"type": "number"}}, {"x": math.inf}),
        ({"x": {"type": "list", "schema": {"type": "integer"}}}, {"x": []}),
        ({"x": {"type": "dict", "schema": {"y": {"type": "integer"}}}}, {"x": {}}),
        ({"x": {"type": "dict", "schema": {"y": {"type": "integer"}}}}, {"x": {"y": 1}}),
        ({"x": {"type": "dict", "schema": {}}}, deep),
        ({"x": {"type": "boolean"}}, {"x": "not-a-bool"}),
        ({"x": {"type": "integer"}}, {"x": 1.5}),
        ({"x": {"type": "string", "regex": r"^\u0000+$"}}, {"x": "\u0000\u0000"}),
        ({"x": {"type": "integer", "default": 7}}, {}),
        ({"x": {"type": "integer", "default_setter": lambda _: 3}}, {}),
        ({"x": {"type": "integer", "rename": "y"}}, {"x": 5}),
        ({"x": {"type": "integer", "coerce": str}}, {"x": 12}),
        ({"x": {"type": "integer", "readonly": True}}, {"x": 1}),
        ({"x": {"type": "integer", "allowed": list(range(50))}}, {"x": 3}),
        ({"x": {"type": ["integer", "string"]}}, {"x": "s"}),
    ]


def digest(schema, doc, patched):
    if patched:
        opt_patch.apply()
    else:
        opt_patch.use_baseline()
    validator = Validator(copy.deepcopy(schema), purge_unknown=False)
    result = validator.validate(copy.deepcopy(doc))
    payload = {
        "result": result,
        "errors": validator.errors,
        "document": validator.document,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=repr).encode()
    ).hexdigest()


def main():
    rng = random.Random(SEED)
    seen = set()
    cases = []
    for schema, doc in edge_cases():
        key = hashlib.sha256(
            json.dumps([schema, doc], sort_keys=True, default=repr).encode()
        ).hexdigest()
        seen.add(key)
        cases.append((key, schema, doc))
    while len(seen) < TARGET_DISTINCT:
        schema = rand_schema(rng)
        doc = rand_doc(rng, schema)
        key = hashlib.sha256(
            json.dumps([schema, doc], sort_keys=True, default=repr).encode()
        ).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        cases.append((key, schema, doc))

    mismatches = []
    for key, schema, doc in cases:
        base = digest(schema, doc, patched=False)
        opt = digest(schema, doc, patched=True)
        if base != opt:
            mismatches.append(key)
    opt_patch.use_baseline()

    print(f"distinct cases: {len(cases)} (dedup: sha256 of canonical (schema, document))")
    print(f"byte-identical sha256 matches: {len(cases) - len(mismatches)}/{len(cases)}")
    print(f"mismatches: {len(mismatches)}")
    for key in mismatches[:5]:
        print("  MISMATCH", key)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
