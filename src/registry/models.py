"""Domain models for the in-process schema registry."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


class CompatibilityMode(Enum):
    """Schema compatibility modes, mirroring Confluent Schema Registry semantics."""

    BACKWARD = "BACKWARD"
    """New schema can read data written with the old schema."""

    FORWARD = "FORWARD"
    """Old schema can read data written with the new schema."""

    FULL = "FULL"
    """Both BACKWARD and FORWARD compatibility must hold."""


class FieldType(Enum):
    """Supported field types for schema fields."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    TIMESTAMP = "timestamp"
    ARRAY = "array"
    OBJECT = "object"


@dataclass
class SchemaField:
    """A single field in a schema definition."""

    name: str
    """Canonical field name."""

    field_type: FieldType
    """Data type of the field."""

    nullable: bool = True
    """Whether the field may be NULL / absent."""

    description: str = ""
    """Human-readable documentation string."""

    default: Optional[Any] = None
    """Default value used when the field is absent in old data."""

    def is_required(self) -> bool:
        """Return True when the field is non-nullable and has no default."""
        return not self.nullable and self.default is None


@dataclass
class Schema:
    """A versioned, named schema composed of typed fields."""

    name: str
    """Subject name — the logical stream this schema describes."""

    version: int
    """Monotonically increasing version number (starts at 1)."""

    fields: List[SchemaField]
    """Ordered list of field definitions."""

    registered_at: Optional[datetime] = None
    """Wall-clock time when this version was registered."""

    description: str = ""
    """Human-readable description of the schema."""

    def field_map(self) -> dict[str, SchemaField]:
        """Return a ``{field_name: SchemaField}`` lookup dict."""
        return {f.name: f for f in self.fields}


@dataclass
class CompatibilityResult:
    """The outcome of a schema compatibility check."""

    compatible: bool
    """True if the schemas are compatible under the requested mode."""

    mode: CompatibilityMode
    """The mode that was evaluated."""

    violations: List[str] = field(default_factory=list)
    """Human-readable descriptions of each violation found."""

    def __bool__(self) -> bool:
        """Allow truthiness tests: ``if result: ...``."""
        return self.compatible
