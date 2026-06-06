"""Contract YAML loader.

Reads contract definition files from a directory and registers them in a
``SchemaRegistry``.  Contract files use a human-friendly YAML format that
maps 1:1 to the ``Schema`` / ``SchemaField`` domain model.

YAML contract format
--------------------
.. code-block:: yaml

    name: raw_trades
    version: 1
    description: "Raw trade events"
    fields:
      - name: trade_id
        type: string
        nullable: false
        description: "UUID"
      - name: strategy_id
        type: string
        nullable: true

All fields are optional except ``name``, ``version``, and ``fields[].name``
plus ``fields[].type``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from src.registry.models import FieldType, Schema, SchemaField
from src.registry.schema_registry import SchemaRegistry

logger = logging.getLogger(__name__)

# Mapping from YAML type strings to FieldType enum values.
_TYPE_MAP: dict[str, FieldType] = {ft.value: ft for ft in FieldType}


class ContractLoader:
    """Loads contract YAML files and registers them in a ``SchemaRegistry``.

    Parameters
    ----------
    contracts_dir:
        Path to the directory containing ``*.yaml`` contract files.
    registry:
        The ``SchemaRegistry`` instance to populate.

    Example
    -------
    >>> from pathlib import Path
    >>> from src.registry.schema_registry import SchemaRegistry
    >>> from src.contracts.loader import ContractLoader
    >>>
    >>> registry = SchemaRegistry()
    >>> loader = ContractLoader(Path("contracts"), registry)
    >>> count = loader.load_all()
    >>> print(f"Loaded {count} contracts")
    """

    def __init__(self, contracts_dir: Path, registry: SchemaRegistry) -> None:
        self.contracts_dir = contracts_dir
        self.registry = registry

    def load_all(self) -> int:
        """Load all ``.yaml`` files in ``contracts_dir``.

        Files are processed in alphabetical order for deterministic
        registration sequences.

        Returns
        -------
        int
            Number of contracts successfully loaded and registered.

        Notes
        -----
        Errors in individual files are logged and skipped so that a single
        malformed contract does not prevent the remainder from loading.
        """
        yaml_files = sorted(self.contracts_dir.glob("*.yaml"))
        loaded = 0

        for path in yaml_files:
            try:
                self.load_file(path)
                loaded += 1
                logger.info("Loaded contract: %s", path.name)
            except yaml.YAMLError as exc:
                logger.error("YAML parse error in contract %s: %s", path.name, exc)
            except (KeyError, ValueError) as exc:
                logger.error("Invalid contract %s: %s", path.name, exc)
            except OSError as exc:
                logger.error("I/O error reading contract %s: %s", path.name, exc)

        return loaded

    def load_file(self, path: Path) -> Schema:
        """Load a single contract YAML file and register it.

        Parameters
        ----------
        path:
            Absolute or relative path to the YAML file.

        Returns
        -------
        Schema
            The ``Schema`` object that was registered.

        Raises
        ------
        ValueError
            If required keys are missing or the YAML is malformed.
        KeyError
            If the schema version is already registered (duplicate file).
        """
        with path.open("r", encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh)

        if not isinstance(data, dict):
            raise ValueError(f"{path.name}: top-level YAML must be a mapping.")

        schema = self._parse_schema(data)
        self.registry.register(schema.name, schema.version, schema)
        return schema

    @staticmethod
    def _parse_schema(data: dict[str, Any]) -> Schema:
        """Parse a contract YAML dict into a ``Schema`` object.

        Parameters
        ----------
        data:
            Parsed YAML document as a Python dict.

        Returns
        -------
        Schema

        Raises
        ------
        ValueError
            If ``name``, ``version``, or ``fields`` are missing or invalid.
        """
        missing = [key for key in ("name", "version", "fields") if key not in data]
        if missing:
            raise ValueError(f"Contract YAML missing required keys: {missing}")

        name: str = str(data["name"])
        version: int = int(data["version"])
        description: str = str(data.get("description", ""))

        raw_fields = data["fields"]
        if not isinstance(raw_fields, list):
            raise ValueError(f"Contract '{name}': 'fields' must be a list.")

        fields: list[SchemaField] = []
        for raw in raw_fields:
            if not isinstance(raw, dict):
                raise ValueError(
                    f"Contract '{name}': each field entry must be a mapping."
                )
            field_name = raw.get("name")
            field_type_str = raw.get("type")

            if not field_name:
                raise ValueError(f"Contract '{name}': field entry missing 'name'.")
            if not field_type_str:
                raise ValueError(
                    f"Contract '{name}', field '{field_name}': missing 'type'."
                )

            if field_type_str not in _TYPE_MAP:
                raise ValueError(
                    f"Contract '{name}', field '{field_name}': "
                    f"unknown type {field_type_str!r}. "
                    f"Valid types: {list(_TYPE_MAP.keys())}"
                )

            field_type = _TYPE_MAP[field_type_str]
            nullable: bool = bool(raw.get("nullable", True))
            field_desc: str = str(raw.get("description", ""))
            default = raw.get("default", None)

            fields.append(
                SchemaField(
                    name=field_name,
                    field_type=field_type,
                    nullable=nullable,
                    description=field_desc,
                    default=default,
                )
            )

        return Schema(
            name=name,
            version=version,
            fields=fields,
            description=description,
        )
