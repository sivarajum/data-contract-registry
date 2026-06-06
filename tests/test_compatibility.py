"""Tests for all three compatibility modes.

Each class covers one mode, with at least one passing (compatible) test
and one failing (incompatible) test that asserts specific violation messages.

Rule summary tested here
------------------------
BACKWARD (new reader, old data):
  Safe:   add nullable / defaulted field, remove any field, widen type
  Unsafe: add required field, narrow type

FORWARD (old reader, new data):
  Safe:   remove nullable field, add nullable / defaulted field, widen type
  Unsafe: remove required field, add required field, narrow type

FULL (both):
  Safe:   add nullable field (only truly unambiguously safe single change)
  Unsafe: add required field (breaks both), remove required field (breaks FORWARD),
          narrow type (breaks both)
"""

from __future__ import annotations

from src.registry.compatibility import (
    _types_compatible,
    check_backward,
    check_forward,
    check_full,
)
from src.registry.models import CompatibilityMode, CompatibilityResult, FieldType, Schema, SchemaField

from tests.conftest import opt, req, with_default

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _schema(version: int, *fields: SchemaField) -> Schema:
    return Schema(name="subject", version=version, fields=list(fields))


# ---------------------------------------------------------------------------
# TestBackwardCompatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """BACKWARD: new schema must be able to read data written with old schema."""

    def test_adding_nullable_field_is_backward_compatible(self) -> None:
        """New nullable field: old data won't have it, new reader uses NULL — safe."""
        old = _schema(1, req("id"), req("price", FieldType.FLOAT))
        new = _schema(2, req("id"), req("price", FieldType.FLOAT), opt("notes"))
        result = check_backward(old, new)
        assert result.compatible is True
        assert result.violations == []

    def test_adding_required_field_breaks_backward_compat(self) -> None:
        """New required field: old data won't carry it — backward violation."""
        old = _schema(1, req("id"), req("price", FieldType.FLOAT))
        new = _schema(2, req("id"), req("price", FieldType.FLOAT), req("mandatory_new"))
        result = check_backward(old, new)
        assert result.compatible is False
        assert any("mandatory_new" in v for v in result.violations)

    def test_nullable_to_required_promotion_breaks_backward_compat(self) -> None:
        """Existing nullable field promoted to required: old data may have NULLs."""
        old = _schema(1, req("id"), opt("notes"))   # notes is nullable in old
        new = _schema(2, req("id"), req("notes"))    # notes becomes required in new
        result = check_backward(old, new)
        assert result.compatible is False
        assert any("notes" in v for v in result.violations)

    def test_required_to_nullable_demotion_is_backward_compatible(self) -> None:
        """Existing required field made nullable: new reader is more lenient — safe."""
        old = _schema(1, req("id"), req("notes"))   # notes is required in old
        new = _schema(2, req("id"), opt("notes"))    # notes becomes nullable in new
        result = check_backward(old, new)
        assert result.compatible is True

    def test_removing_field_is_backward_compatible(self) -> None:
        """Removing a field: new reader simply ignores its absence in old data — safe."""
        old = _schema(1, req("id"), req("price", FieldType.FLOAT), opt("deprecated_field"))
        new = _schema(2, req("id"), req("price", FieldType.FLOAT))
        result = check_backward(old, new)
        assert result.compatible is True
        assert result.violations == []

    def test_changing_type_int_to_float_is_backward_compatible(self) -> None:
        """Widening INTEGER → FLOAT is safe (no data loss in the new reader)."""
        old = _schema(1, req("id"), SchemaField("qty", FieldType.INTEGER, nullable=False))
        new = _schema(2, req("id"), SchemaField("qty", FieldType.FLOAT, nullable=False))
        result = check_backward(old, new)
        assert result.compatible is True

    def test_changing_type_float_to_int_breaks_backward_compat(self) -> None:
        """Narrowing FLOAT → INTEGER: old data may have fractional values."""
        old = _schema(1, req("id"), SchemaField("price", FieldType.FLOAT, nullable=False))
        new = _schema(2, req("id"), SchemaField("price", FieldType.INTEGER, nullable=False))
        result = check_backward(old, new)
        assert result.compatible is False
        assert any("price" in v for v in result.violations)

    def test_adding_field_with_default_is_backward_compatible(self) -> None:
        """New required field with a default value: old data missing it will use the default."""
        old = _schema(1, req("id"))
        new = _schema(2, req("id"), with_default("status", FieldType.STRING, "PENDING"))
        result = check_backward(old, new)
        assert result.compatible is True

    def test_no_changes_is_backward_compatible(self) -> None:
        """Identical schemas (no changes) must be backward compatible."""
        old = _schema(1, req("id"), opt("notes"))
        new = _schema(2, req("id"), opt("notes"))
        result = check_backward(old, new)
        assert result.compatible is True

    def test_result_mode_is_backward(self) -> None:
        """Result mode attribute must be BACKWARD."""
        old = _schema(1, req("id"))
        new = _schema(2, req("id"))
        result = check_backward(old, new)
        assert result.mode is CompatibilityMode.BACKWARD

    def test_multiple_required_fields_added_all_listed(self) -> None:
        """All added required fields appear in violations, not just the first."""
        old = _schema(1, req("id"))
        new = _schema(2, req("id"), req("alpha"), req("beta"))
        result = check_backward(old, new)
        assert result.compatible is False
        violation_text = " ".join(result.violations)
        assert "alpha" in violation_text
        assert "beta" in violation_text

    def test_changing_string_to_boolean_breaks_backward_compat(self) -> None:
        """Incompatible type change: STRING → BOOLEAN."""
        old = _schema(1, req("id"), SchemaField("flag", FieldType.STRING, nullable=False))
        new = _schema(2, req("id"), SchemaField("flag", FieldType.BOOLEAN, nullable=False))
        result = check_backward(old, new)
        assert result.compatible is False
        assert any("flag" in v for v in result.violations)


# ---------------------------------------------------------------------------
# TestForwardCompatibility
# ---------------------------------------------------------------------------


class TestForwardCompatibility:
    """FORWARD: old schema must be able to read data written with new schema."""

    def test_removing_optional_field_is_forward_compatible(self) -> None:
        """Removing a nullable field: old reader copes with its absence — safe."""
        old = _schema(1, req("id"), opt("notes"))
        new = _schema(2, req("id"))
        result = check_forward(old, new)
        assert result.compatible is True
        assert result.violations == []

    def test_removing_required_field_breaks_forward_compat(self) -> None:
        """Removing a required field: old reader expects it in every new record."""
        old = _schema(1, req("id"), req("price", FieldType.FLOAT))
        new = _schema(2, req("id"))
        result = check_forward(old, new)
        assert result.compatible is False
        assert any("price" in v for v in result.violations)

    def test_adding_required_field_breaks_forward_compat(self) -> None:
        """Adding a required field to new schema: old reader can't produce/validate it."""
        old = _schema(1, req("id"))
        new = _schema(2, req("id"), req("mandatory_new"))
        result = check_forward(old, new)
        assert result.compatible is False
        assert any("mandatory_new" in v for v in result.violations)

    def test_adding_nullable_field_is_forward_compatible(self) -> None:
        """Adding a nullable field to new schema: old reader ignores unknown fields."""
        old = _schema(1, req("id"))
        new = _schema(2, req("id"), opt("extra_metric"))
        result = check_forward(old, new)
        assert result.compatible is True

    def test_required_to_nullable_demotion_breaks_forward_compat(self) -> None:
        """Required field made nullable in new schema: new writer may emit NULLs
        that the old reader's required constraint cannot accept."""
        old = _schema(1, req("id"), req("notes"))   # notes is required in old reader
        new = _schema(2, req("id"), opt("notes"))    # notes becomes nullable in new writer
        result = check_forward(old, new)
        assert result.compatible is False
        assert any("notes" in v for v in result.violations)

    def test_nullable_to_required_promotion_is_forward_compatible(self) -> None:
        """Optional field made required in new schema: new writer always provides it.
        Old reader (which expected nullable) can handle a always-present value — safe."""
        old = _schema(1, req("id"), opt("notes"))   # old reader: notes is nullable
        new = _schema(2, req("id"), req("notes"))    # new writer: notes is always present
        result = check_forward(old, new)
        assert result.compatible is True

    def test_type_narrowing_breaks_forward_compat(self) -> None:
        """FLOAT → INTEGER in new schema: old reader expecting FLOAT may choke."""
        old = _schema(1, req("id"), SchemaField("val", FieldType.FLOAT, nullable=False))
        new = _schema(2, req("id"), SchemaField("val", FieldType.INTEGER, nullable=False))
        result = check_forward(old, new)
        assert result.compatible is False
        assert any("val" in v for v in result.violations)

    def test_type_widening_is_forward_compatible(self) -> None:
        """INTEGER → FLOAT in new schema is safe for old reader."""
        old = _schema(1, SchemaField("count", FieldType.INTEGER, nullable=False))
        new = _schema(2, SchemaField("count", FieldType.FLOAT, nullable=False))
        result = check_forward(old, new)
        assert result.compatible is True

    def test_result_mode_is_forward(self) -> None:
        """Result mode attribute must be FORWARD."""
        old = _schema(1, req("id"))
        new = _schema(2, req("id"))
        result = check_forward(old, new)
        assert result.mode is CompatibilityMode.FORWARD

    def test_adding_field_with_default_is_forward_compatible(self) -> None:
        """A new field that carries a default is NOT truly required (is_required() == False).

        ``with_default`` creates ``nullable=False, default="ACTIVE"``.  Because
        ``SchemaField.is_required()`` returns ``not nullable and default is None``,
        this field evaluates as *not* required — the default value satisfies any old
        reader that encounters it.  FORWARD must therefore pass.
        """
        old = _schema(1, req("id"))
        new = _schema(2, req("id"), with_default("status", FieldType.STRING, "ACTIVE"))
        result = check_forward(old, new)
        # A field with a default is not is_required(), so old readers can tolerate
        # it being present in new data.  FORWARD is safe.
        assert result.compatible is True

    def test_no_changes_is_forward_compatible(self) -> None:
        """Identical schemas must be forward compatible."""
        old = _schema(1, req("id"), req("price", FieldType.FLOAT))
        new = _schema(2, req("id"), req("price", FieldType.FLOAT))
        result = check_forward(old, new)
        assert result.compatible is True


# ---------------------------------------------------------------------------
# TestFullCompatibility
# ---------------------------------------------------------------------------


class TestFullCompatibility:
    """FULL: both BACKWARD and FORWARD must hold simultaneously."""

    def test_adding_nullable_field_is_fully_compatible(self) -> None:
        """Only truly safe change under FULL: add nullable/optional field."""
        old = _schema(1, req("id"), req("price", FieldType.FLOAT))
        new = _schema(2, req("id"), req("price", FieldType.FLOAT), opt("tag"))
        result = check_full(old, new)
        assert result.compatible is True
        assert result.violations == []

    def test_adding_required_field_breaks_full_compat(self) -> None:
        """Adding a required field violates both BACKWARD and FORWARD."""
        old = _schema(1, req("id"))
        new = _schema(2, req("id"), req("new_required"))
        result = check_full(old, new)
        assert result.compatible is False
        # Both backward AND forward violations should reference new_required
        violation_text = " ".join(result.violations)
        assert "new_required" in violation_text

    def test_removing_required_field_breaks_full_compat(self) -> None:
        """Removing a required field violates FORWARD (old reader expects it)."""
        old = _schema(1, req("id"), req("price", FieldType.FLOAT))
        new = _schema(2, req("id"))
        result = check_full(old, new)
        assert result.compatible is False
        assert any("price" in v for v in result.violations)

    def test_only_adding_nullable_with_default_is_full_compat(self) -> None:
        """Adding a nullable field (no default needed): both modes pass."""
        old = _schema(1, req("id"), req("amount", FieldType.FLOAT))
        new = _schema(2, req("id"), req("amount", FieldType.FLOAT), opt("currency"))
        result = check_full(old, new)
        assert result.compatible is True

    def test_type_narrowing_breaks_full_compat(self) -> None:
        """Type narrowing violates both sub-checks, violations accumulate in FULL result."""
        old = _schema(1, SchemaField("score", FieldType.FLOAT, nullable=False))
        new = _schema(2, SchemaField("score", FieldType.INTEGER, nullable=False))
        result = check_full(old, new)
        assert result.compatible is False
        assert len(result.violations) >= 2  # one from each sub-check

    def test_result_mode_is_full(self) -> None:
        """Result mode attribute must be FULL."""
        old = _schema(1, req("id"))
        new = _schema(2, req("id"))
        result = check_full(old, new)
        assert result.mode is CompatibilityMode.FULL

    def test_full_passes_when_both_sub_checks_pass(self) -> None:
        """FULL passes only if BACKWARD and FORWARD both pass."""
        old = _schema(1, req("id"), opt("notes"))
        new = _schema(2, req("id"), opt("notes"), opt("extra"))
        result = check_full(old, new)
        assert result.compatible is True
        assert result.violations == []

    def test_removing_optional_field_is_full_compatible(self) -> None:
        """Removing a nullable field: BACKWARD passes but FORWARD might flag it
        if the old reader has it as required.  Here old reader has it nullable,
        so FORWARD is actually fine — FULL should pass."""
        old = _schema(1, req("id"), opt("metadata"))
        new = _schema(2, req("id"))
        # BACKWARD: fine (new reader ignores absent nullable field)
        # FORWARD: fine (old reader has metadata as nullable, so tolerates its absence)
        result = check_full(old, new)
        # metadata is optional in old — removing it only breaks FORWARD if it was required
        # It's nullable (is_required() == False), so FORWARD is not violated.
        assert result.compatible is True


# ---------------------------------------------------------------------------
# TestTypesCompatible helper
# ---------------------------------------------------------------------------


class TestTypesCompatibleHelper:
    def test_same_type_always_compatible(self) -> None:
        for ft in FieldType:
            assert _types_compatible(ft, ft) is True

    def test_integer_to_float_compatible(self) -> None:
        assert _types_compatible(FieldType.INTEGER, FieldType.FLOAT) is True

    def test_float_to_integer_incompatible(self) -> None:
        assert _types_compatible(FieldType.FLOAT, FieldType.INTEGER) is False

    def test_string_to_integer_incompatible(self) -> None:
        assert _types_compatible(FieldType.STRING, FieldType.INTEGER) is False

    def test_integer_to_string_compatible(self) -> None:
        assert _types_compatible(FieldType.INTEGER, FieldType.STRING) is True

    def test_boolean_to_string_compatible(self) -> None:
        assert _types_compatible(FieldType.BOOLEAN, FieldType.STRING) is True

    def test_timestamp_to_string_compatible(self) -> None:
        assert _types_compatible(FieldType.TIMESTAMP, FieldType.STRING) is True

    def test_bool_result_of_compatibility_result(self) -> None:
        """CompatibilityResult should evaluate truthily based on .compatible."""
        passing = CompatibilityResult(compatible=True, mode=CompatibilityMode.BACKWARD)
        failing = CompatibilityResult(compatible=False, mode=CompatibilityMode.BACKWARD)
        assert bool(passing) is True
        assert bool(failing) is False
