"""Runtime form of ``patch.diff``.

The upstream patch replaces one line in
``cerberus/validator.py::BareValidator.__normalize_mapping``::

    schema = schema.copy()

with a branch that shallow-copies a ``DefinitionSchema`` into a plain ``dict``
instead of calling ``DefinitionSchema.copy()``, which re-runs ``expand()`` and
``validate()`` for every field on every ``validate()`` call.

This module realises exactly that difference on an unmodified upstream
install, without editing the installed package, so the benchmark and the
differential test can switch between the baseline and the patched path in the
same interpreter::

    import opt_patch
    opt_patch.apply()          # switch to the patched path
    opt_patch.use_baseline()   # switch back

The wrapped function delegates to the original implementation; only the
``DefinitionSchema`` fast copy is added, so any other code path is byte-for-byte
the upstream code.
"""

import cerberus.validator as cv
from cerberus.schema import DefinitionSchema

_TARGET = "_BareValidator__normalize_mapping"
_CLS = cv.BareValidator


def _original():
    fn = getattr(_CLS, _TARGET)
    return getattr(fn, "_opt_patch_original", fn)


def _patched(original):
    def normalized(self, mapping, schema):
        if isinstance(schema, DefinitionSchema):
            schema = dict(schema)
        return original(self, mapping, schema)

    normalized._opt_patch_original = original
    return normalized


def apply():
    """Replace the class method with the patched wrapper (idempotent)."""
    current = getattr(_CLS, _TARGET)
    if getattr(current, "_opt_patch_applied", False):
        return
    wrapper = _patched(current)
    wrapper._opt_patch_applied = True
    setattr(_CLS, _TARGET, wrapper)


def use_baseline():
    """Restore the untouched upstream class method."""
    current = getattr(_CLS, _TARGET)
    original = getattr(current, "_opt_patch_original", None)
    if original is not None:
        setattr(_CLS, _TARGET, original)


def is_patched():
    return getattr(getattr(_CLS, _TARGET), "_opt_patch_applied", False)
