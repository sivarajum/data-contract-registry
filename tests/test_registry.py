"""Unit tests for SchemaRegistry.

Covers registration, retrieval, enumeration, and compatibility delegation.
"""

from __future__ import annotations

import pytest
from src.registry.models import CompatibilityMode, FieldType, Schema
from src.registry.schema_registry import SchemaRegistry

from tests.conftest import opt, req

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_new_subject_and_version(self, registry: SchemaRegistry, base_schema: Schema) -> None:
        """Registering a brand-new subject should succeed and return the schema."""
        result = registry.register("trades", 1, base_schema)
        assert result is base_schema

    def test_register_sets_registered_at(self, registry: SchemaRegistry, base_schema: Schema) -> None:
        """registered_at must be populated after registration."""
        base_schema.registered_at = None
        registry.register("trades", 1, base_schema)
        assert base_schema.registered_at is not None

    def test_register_duplicate_version_raises(self, populated_registry: SchemaRegistry, base_schema: Schema) -> None:
        """Re-registering the same (name, version) pair must raise ValueError."""
        with pytest.raises(ValueError, match="already registered"):
            populated_registry.register("test_subject", 1, base_schema)

    def test_register_zero_version_raises(self, registry: SchemaRegistry, base_schema: Schema) -> None:
        """Version 0 is not a valid version number."""
        with pytest.raises(ValueError, match="positive integer"):
            registry.register("trades", 0, base_schema)

    def test_register_negative_version_raises(self, registry: SchemaRegistry, base_schema: Schema) -> None:
        """Negative version numbers must be rejected."""
        with pytest.raises(ValueError, match="positive integer"):
            registry.register("trades", -1, base_schema)

    def test_register_multiple_versions_same_subject(self, registry: SchemaRegistry) -> None:
        """Multiple versions of the same subject should all be stored."""
        for v in (1, 2, 3):
            s = Schema(name="trades", version=v, fields=[req("id")])
            registry.register("trades", v, s)
        assert registry.list_versions("trades") == [1, 2, 3]


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


class TestRetrieval:
    def test_get_specific_version(self, populated_registry: SchemaRegistry, base_schema: Schema) -> None:
        """get() must return the exact schema registered at that version."""
        result = populated_registry.get("test_subject", 1)
        assert result is base_schema

    def test_get_unknown_subject_raises(self, populated_registry: SchemaRegistry) -> None:
        """Requesting a non-existent subject must raise KeyError."""
        with pytest.raises(KeyError, match="test_subject_x"):
            populated_registry.get("test_subject_x", 1)

    def test_get_unknown_version_raises(self, populated_registry: SchemaRegistry) -> None:
        """Requesting a registered subject but non-existent version must raise KeyError."""
        with pytest.raises(KeyError):
            populated_registry.get("test_subject", 99)

    def test_get_latest_returns_highest_version(self) -> None:
        """get_latest() should return the schema with the highest version number."""
        reg = SchemaRegistry()
        s1 = Schema(name="trades", version=1, fields=[req("id")])
        s2 = Schema(name="trades", version=2, fields=[req("id"), opt("name")])
        reg.register("trades", 1, s1)
        reg.register("trades", 2, s2)
        assert reg.get_latest("trades") is s2

    def test_get_latest_unknown_subject_raises(self, registry: SchemaRegistry) -> None:
        """get_latest() on a non-existent subject must raise KeyError."""
        with pytest.raises(KeyError, match="no_such_subject"):
            registry.get_latest("no_such_subject")


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------


class TestEnumeration:
    def test_list_versions_sorted_ascending(self) -> None:
        """list_versions() must return versions in ascending order."""
        reg = SchemaRegistry()
        for v in (3, 1, 2):
            reg.register("s", v, Schema(name="s", version=v, fields=[req("x")]))
        assert reg.list_versions("s") == [1, 2, 3]

    def test_list_versions_unknown_subject_returns_empty(self, registry: SchemaRegistry) -> None:
        """list_versions() on an unknown subject returns [] not an error."""
        assert registry.list_versions("unknown") == []

    def test_list_subjects_sorted(self) -> None:
        """list_subjects() must return alphabetically sorted subject names."""
        reg = SchemaRegistry()
        for name in ("zebra", "alpha", "mango"):
            reg.register(name, 1, Schema(name=name, version=1, fields=[req("x")]))
        assert reg.list_subjects() == ["alpha", "mango", "zebra"]

    def test_list_subjects_empty_registry(self, registry: SchemaRegistry) -> None:
        """list_subjects() on a fresh registry returns an empty list."""
        assert registry.list_subjects() == []


# ---------------------------------------------------------------------------
# Compatibility delegation
# ---------------------------------------------------------------------------


class TestCheckCompatibilityDelegation:
    """Verify that check_compatibility correctly delegates to the three modes."""

    def _make_v2_with_required_field(self) -> Schema:
        return Schema(
            name="test_subject",
            version=2,
            fields=[
                req("id", FieldType.STRING),
                req("price", FieldType.FLOAT),
                opt("description", FieldType.STRING),
                req("new_required", FieldType.INTEGER),  # breaks BACKWARD & FORWARD
            ],
        )

    def test_backward_compat_via_registry(self, populated_registry: SchemaRegistry) -> None:
        """Backward compat check via registry returns CompatibilityResult."""
        good_v2 = Schema(
            name="test_subject",
            version=2,
            fields=[
                req("id", FieldType.STRING),
                req("price", FieldType.FLOAT),
                opt("description", FieldType.STRING),
                opt("extra", FieldType.STRING),  # nullable: safe BACKWARD
            ],
        )
        result = populated_registry.check_compatibility(
            "test_subject", good_v2, CompatibilityMode.BACKWARD
        )
        assert result.compatible is True
        assert result.mode is CompatibilityMode.BACKWARD

    def test_backward_compat_violation_via_registry(self, populated_registry: SchemaRegistry) -> None:
        """Adding a required field must surface as a BACKWARD violation via registry."""
        bad_v2 = self._make_v2_with_required_field()
        result = populated_registry.check_compatibility(
            "test_subject", bad_v2, CompatibilityMode.BACKWARD
        )
        assert result.compatible is False
        assert any("new_required" in v for v in result.violations)

    def test_forward_compat_violation_via_registry(self, populated_registry: SchemaRegistry) -> None:
        """Removing a required field via registry flags FORWARD violation."""
        bad_v2 = Schema(
            name="test_subject",
            version=2,
            fields=[
                req("id", FieldType.STRING),
                opt("description", FieldType.STRING),
                # 'price' (required) removed — breaks FORWARD
            ],
        )
        result = populated_registry.check_compatibility(
            "test_subject", bad_v2, CompatibilityMode.FORWARD
        )
        assert result.compatible is False
        assert any("price" in v for v in result.violations)

    def test_full_compat_violation_via_registry(self, populated_registry: SchemaRegistry) -> None:
        """Adding a required field breaks FULL compat (fails both sub-checks)."""
        bad_v2 = self._make_v2_with_required_field()
        result = populated_registry.check_compatibility(
            "test_subject", bad_v2, CompatibilityMode.FULL
        )
        assert result.compatible is False
        assert result.mode is CompatibilityMode.FULL

    def test_check_compatibility_unknown_subject_raises(self, registry: SchemaRegistry) -> None:
        """check_compatibility on an unknown subject must raise KeyError."""
        new_s = Schema(name="missing", version=2, fields=[req("x")])
        with pytest.raises(KeyError):
            registry.check_compatibility("missing", new_s, CompatibilityMode.BACKWARD)
