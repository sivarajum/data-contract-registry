"""Shared pytest fixtures for POC-11 tests.

All fixtures return new instances per test so that no test bleeds state
into another.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.contracts.validator import DataContractValidator
from src.registry.models import (
    FieldType,
    Schema,
    SchemaField,
)
from src.registry.schema_registry import SchemaRegistry

# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------


def make_field(
    name: str,
    field_type: FieldType = FieldType.STRING,
    nullable: bool = True,
    default=None,
) -> SchemaField:
    """Convenience factory for ``SchemaField`` instances."""
    return SchemaField(name=name, field_type=field_type, nullable=nullable, default=default)


def req(name: str, field_type: FieldType = FieldType.STRING) -> SchemaField:
    """Create a required (non-nullable, no-default) field."""
    return SchemaField(name=name, field_type=field_type, nullable=False, default=None)


def opt(name: str, field_type: FieldType = FieldType.STRING) -> SchemaField:
    """Create an optional (nullable) field."""
    return SchemaField(name=name, field_type=field_type, nullable=True, default=None)


def with_default(name: str, field_type: FieldType, default) -> SchemaField:
    """Create a required-but-defaulted field."""
    return SchemaField(name=name, field_type=field_type, nullable=False, default=default)


# ---------------------------------------------------------------------------
# Schema fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_schema() -> Schema:
    """A simple two-field schema (v1) used as the 'old' schema in compat tests."""
    return Schema(
        name="test_subject",
        version=1,
        fields=[
            req("id", FieldType.STRING),
            req("price", FieldType.FLOAT),
            opt("description", FieldType.STRING),
        ],
    )


@pytest.fixture
def registry() -> SchemaRegistry:
    """A fresh, empty ``SchemaRegistry``."""
    return SchemaRegistry()


@pytest.fixture
def populated_registry(base_schema: Schema) -> SchemaRegistry:
    """A ``SchemaRegistry`` with *test_subject* v1 pre-loaded."""
    reg = SchemaRegistry()
    reg.register("test_subject", 1, base_schema)
    return reg


@pytest.fixture
def validator(populated_registry: SchemaRegistry) -> DataContractValidator:
    """A ``DataContractValidator`` backed by the populated registry."""
    return DataContractValidator(populated_registry)


# ---------------------------------------------------------------------------
# Contracts directory
# ---------------------------------------------------------------------------


@pytest.fixture
def contracts_dir() -> Path:
    """Absolute path to the real contracts/ directory."""
    return Path(__file__).parent.parent / "contracts"
