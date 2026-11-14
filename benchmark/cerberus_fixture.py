"""Schema + validator fixture copied from upstream's own benchmark suite.

Source: ``cerberus/benchmarks/test_overall_performance_1.py`` in
https://github.com/pyeve/cerberus (ISC licence, see ../../LICENSE).
Only the pytest fixture glue is dropped; the schema, the ``field_3_schema``
registry entry, the ``path_rules`` registry entry and the custom
``check_with`` callback are reproduced verbatim so that the measured workload is
upstream's own.
"""

import json
from pathlib import Path

from cerberus import (
    TypeDefinition,
    Validator,
    rules_set_registry,
    schema_registry,
)

rules_set_registry.add("path_rules", {"coerce": Path, "type": "path"})

schema_registry.add(
    "field_3_schema",
    {
        "field_31": {"contains": 0, "empty": False},
        "field_32": {
            "default": [None, None, None],
            "items": [
                {"type": "integer"},
                {"type": "string"},
                {"type": ["integer", "string"]},
            ],
            "schema": {"nullable": True},
        },
    },
)


def schema_1_field_3_allow_unknown_check_with(field, value, error):
    if len(value) > 9:
        error(field, "Requires a smaller list.")


schema_1 = {
    "field_1": {
        "type": "dict",
        "required": True,
        "allow_unknown": True,
        "keysrules": {"regex": r"field_1[12345]"},
        "minlength": 3,
        "maxlength": 5,
        "schema": {
            "field_11": {
                "type": "integer",
                "allowed": list(range(100)),
                "dependencies": {"field_12": 0, "^field_1.field_13": 0},
            },
            "field_12": {
                "type": "integer",
                "default_setter": lambda _: 1,
                "forbidden": (1,),
            },
            "field_13": {"type": "integer"},
            "field_14": {"rename": "field_13"},
        },
    },
    "field_2": {
        "type": "dict",
        "allow_unknown": False,
        "schema": {
            "field_21": {
                "type": "integer",
                "coerce": [str.strip, int],
                "min": 9,
                "max": 89,
                "anyof": [{"dependencies": "field_22"}, {"dependencies": "field_23"}],
            },
            "field_22": {"excludes": "field_23", "nullable": True},
            "field_23": {"nullable": True},
        },
    },
    "field_3": {
        "allow_unknown": {"check_with": schema_1_field_3_allow_unknown_check_with},
        "valuesrules": {"type": "list"},
        "require_all": True,
        "schema": "field_3_schema",
    },
    "field_4": "path_rules",
}


def _test_validator_class():
    class TestValidator(Validator):
        types_mapping = {
            **Validator.types_mapping,
            "path": TypeDefinition("path", (Path,), ()),
        }

    return TestValidator


def make_validator(schema, **kwargs):
    return _test_validator_class()(schema, **kwargs)


def init_validator():
    return make_validator(schema_1, purge_unknown=True)


def load_documents(path):
    with open(path) as f:
        return json.load(f)
