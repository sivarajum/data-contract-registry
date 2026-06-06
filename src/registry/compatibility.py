"""Schema compatibility checking logic.

Each public function accepts two ``Schema`` instances and returns a
``CompatibilityResult``.  The three functions implement the three
industry-standard compatibility modes used by Confluent Schema Registry
and Apache Avro.

Terminology
-----------
* **old schema** – the version already persisted / consumed by readers.
* **new schema** – the proposed next version produced by the writer.

BACKWARD
    A *new reader* must be able to deserialise data produced by an *old writer*.
    Concretely:

    * Adding a **required** field (non-nullable, no default) to the new schema
      breaks backward compat because old data records won't carry that field.
    * Removing a field is **safe**: the new reader simply won't see it.
    * Type narrowing (e.g. FLOAT → INTEGER) is unsafe because old data may
      carry fractional values the new reader cannot represent.

FORWARD
    An *old reader* must be able to deserialise data produced by a *new writer*.
    Concretely:

    * Removing a **required** field from the new schema breaks forward compat
      because the old reader expects every record to carry that field.
    * Adding any **required** field to the new schema breaks forward compat
      because the old reader does not know how to supply that field.
    * Adding a nullable / default-carrying field is **safe**: the old reader
      ignores unknown fields.
    * Type narrowing is still unsafe.

FULL
    Both BACKWARD and FORWARD must hold simultaneously.
"""

from __future__ import annotations

import logging
from typing import Set

from .models import CompatibilityMode, CompatibilityResult, FieldType, Schema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type compatibility helpers
# ---------------------------------------------------------------------------

# Directed graph: (old_type, new_type) pairs that are considered compatible.
# An integer value can widen to a float without data loss; the reverse is not
# guaranteed (0.5 cannot round-trip through INTEGER).
_COMPATIBLE_TYPE_TRANSITIONS: Set[tuple[FieldType, FieldType]] = {
    (FieldType.INTEGER, FieldType.FLOAT),   # widening — safe
    (FieldType.INTEGER, FieldType.STRING),  # widening to string repr — safe
    (FieldType.FLOAT, FieldType.STRING),    # widening to string repr — safe
    (FieldType.BOOLEAN, FieldType.STRING),  # widening to string repr — safe
    (FieldType.TIMESTAMP, FieldType.STRING),  # ISO-8601 coercion — safe
}


def _types_compatible(old_type: FieldType, new_type: FieldType) -> bool:
    """Return ``True`` when changing a field from *old_type* to *new_type* is safe.

    Same type is always compatible.  Widening numeric types (INTEGER → FLOAT)
    is allowed.  All other transitions are considered incompatible.
    """
    if old_type == new_type:
        return True
    return (old_type, new_type) in _COMPATIBLE_TYPE_TRANSITIONS


# ---------------------------------------------------------------------------
# Public compatibility checkers
# ---------------------------------------------------------------------------


def check_backward(old_schema: Schema, new_schema: Schema) -> CompatibilityResult:
    """Check BACKWARD compatibility: new reader can read data written by old writer.

    Violations
    ----------
    * New schema adds a *required* field (non-nullable, no default).
      Old data records won't have this field, so the new reader cannot
      satisfy the required constraint.
    * A field present in both schemas has its type changed to an *incompatible*
      (narrowing) type.

    Non-violations (safe changes)
    ------------------------------
    * New schema *removes* a field — new reader simply ignores its absence
      in old data.
    * New schema adds a *nullable* or *default-carrying* field — missing old
      records will use NULL / the default.
    * Widening type changes (INTEGER → FLOAT).
    """
    violations: list[str] = []

    old_fields = old_schema.field_map()
    new_fields = new_schema.field_map()

    # 1. New required fields that old data won't carry.
    for fname, nf in new_fields.items():
        if fname not in old_fields and nf.is_required():
            violations.append(
                f"BACKWARD violation: field '{fname}' added as required "
                f"(non-nullable, no default) — old data records won't carry it."
            )

    # 2. Changes on shared fields.
    for fname, of in old_fields.items():
        if fname in new_fields:
            nf = new_fields[fname]
            if not _types_compatible(of.field_type, nf.field_type):
                violations.append(
                    f"BACKWARD violation: field '{fname}' type changed from "
                    f"{of.field_type.value!r} to {nf.field_type.value!r} — "
                    f"incompatible narrowing."
                )
            # Nullability promotion: old nullable → new required breaks BACKWARD.
            # Old data records may contain NULL for this field; the new reader's
            # required constraint will reject them.
            if not of.is_required() and nf.is_required():
                violations.append(
                    f"BACKWARD violation: field '{fname}' changed from nullable "
                    f"to required — old data records may contain NULL values that "
                    f"the new schema's required constraint would reject."
                )

    compatible = len(violations) == 0
    if not compatible:
        logger.info(
            "BACKWARD check: %d violation(s) for %s v%d -> v%d",
            len(violations), old_schema.name, old_schema.version, new_schema.version,
        )
    return CompatibilityResult(
        compatible=compatible,
        mode=CompatibilityMode.BACKWARD,
        violations=violations,
    )


def check_forward(old_schema: Schema, new_schema: Schema) -> CompatibilityResult:
    """Check FORWARD compatibility: old reader can read data written by new writer.

    Violations
    ----------
    * New schema *removes* a field that the old schema declared as *required*.
      The old reader expects that field to be present in every record.
    * New schema *adds* a *required* field.  The old reader has no knowledge
      of this field and cannot provide or validate it.
    * A shared field undergoes an incompatible (narrowing) type change.

    Non-violations (safe changes)
    ------------------------------
    * New schema *removes* a nullable / optional field — old reader may miss
      it but can tolerate its absence.
    * New schema *adds* a nullable or default-carrying field — old reader
      ignores unknown fields.
    * Widening type changes (INTEGER → FLOAT).
    """
    violations: list[str] = []

    old_fields = old_schema.field_map()
    new_fields = new_schema.field_map()

    # 1. Fields removed from new schema that were required in old schema.
    for fname, of in old_fields.items():
        if fname not in new_fields and of.is_required():
            violations.append(
                f"FORWARD violation: required field '{fname}' removed from new schema — "
                f"old reader expects it to be present in every record."
            )

    # 2. New required fields added — old reader won't know how to handle them.
    for fname, nf in new_fields.items():
        if fname not in old_fields and nf.is_required():
            violations.append(
                f"FORWARD violation: field '{fname}' added as required "
                f"(non-nullable, no default) — old reader cannot supply or validate it."
            )

    # 3. Changes on shared fields.
    for fname, of in old_fields.items():
        if fname in new_fields:
            nf = new_fields[fname]
            if not _types_compatible(of.field_type, nf.field_type):
                violations.append(
                    f"FORWARD violation: field '{fname}' type changed from "
                    f"{of.field_type.value!r} to {nf.field_type.value!r} — "
                    f"incompatible narrowing."
                )
            # Nullability demotion: old required → new nullable breaks FORWARD.
            # The new writer may now emit NULLs for this field; the old reader,
            # which declared it required, cannot handle NULL values it never
            # expected to receive.
            if of.is_required() and not nf.is_required():
                violations.append(
                    f"FORWARD violation: field '{fname}' changed from required "
                    f"to nullable — new writer may produce NULLs that the old "
                    f"reader's required constraint cannot accept."
                )

    compatible = len(violations) == 0
    if not compatible:
        logger.info(
            "FORWARD check: %d violation(s) for %s v%d -> v%d",
            len(violations), old_schema.name, old_schema.version, new_schema.version,
        )
    return CompatibilityResult(
        compatible=compatible,
        mode=CompatibilityMode.FORWARD,
        violations=violations,
    )


def check_full(old_schema: Schema, new_schema: Schema) -> CompatibilityResult:
    """Check FULL compatibility: both BACKWARD and FORWARD must hold.

    The violations list is the union of violations from both checks, each
    prefixed with its source mode for traceability.
    """
    backward = check_backward(old_schema, new_schema)
    forward = check_forward(old_schema, new_schema)

    combined_violations = backward.violations + forward.violations
    compatible = backward.compatible and forward.compatible

    return CompatibilityResult(
        compatible=compatible,
        mode=CompatibilityMode.FULL,
        violations=combined_violations,
    )
