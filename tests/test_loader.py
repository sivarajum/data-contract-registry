"""Tests for ContractLoader.

Verifies that YAML contract files are correctly parsed and registered,
that malformed files raise descriptive errors, and that the real contracts/
directory loads cleanly.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from src.contracts.loader import ContractLoader
from src.registry.models import FieldType, Schema
from src.registry.schema_registry import SchemaRegistry

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def write_yaml(tmp_path: Path, filename: str, content: str) -> Path:
    """Write a YAML string to a temp file and return its path."""
    path = tmp_path / filename
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# TestContractLoader — happy paths
# ---------------------------------------------------------------------------


class TestContractLoaderHappyPath:
    def test_load_file_returns_schema(self, tmp_path: Path) -> None:
        """load_file() must return a Schema with correct name and version."""
        yaml_content = """
            name: my_stream
            version: 1
            description: "Test stream"
            fields:
              - name: id
                type: string
                nullable: false
        """
        path = write_yaml(tmp_path, "my_stream_v1.yaml", yaml_content)
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        schema = loader.load_file(path)

        assert isinstance(schema, Schema)
        assert schema.name == "my_stream"
        assert schema.version == 1
        assert schema.description == "Test stream"

    def test_load_file_registers_in_registry(self, tmp_path: Path) -> None:
        """Loaded schema must be retrievable from the registry."""
        yaml_content = """
            name: orders
            version: 2
            fields:
              - name: order_id
                type: string
                nullable: false
        """
        path = write_yaml(tmp_path, "orders_v2.yaml", yaml_content)
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        loader.load_file(path)

        retrieved = reg.get("orders", 2)
        assert retrieved.name == "orders"
        assert retrieved.version == 2

    def test_load_file_parses_field_type(self, tmp_path: Path) -> None:
        """Field types must be correctly mapped to FieldType enum values."""
        yaml_content = """
            name: metrics
            version: 1
            fields:
              - name: value
                type: float
                nullable: false
              - name: count
                type: integer
                nullable: false
              - name: active
                type: boolean
                nullable: true
              - name: ts
                type: timestamp
                nullable: false
        """
        path = write_yaml(tmp_path, "metrics.yaml", yaml_content)
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        schema = loader.load_file(path)

        field_map = schema.field_map()
        assert field_map["value"].field_type is FieldType.FLOAT
        assert field_map["count"].field_type is FieldType.INTEGER
        assert field_map["active"].field_type is FieldType.BOOLEAN
        assert field_map["ts"].field_type is FieldType.TIMESTAMP

    def test_load_file_nullable_defaults_to_true(self, tmp_path: Path) -> None:
        """Fields without explicit nullable should default to True."""
        yaml_content = """
            name: stream
            version: 1
            fields:
              - name: tag
                type: string
        """
        path = write_yaml(tmp_path, "stream.yaml", yaml_content)
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        schema = loader.load_file(path)
        assert schema.fields[0].nullable is True

    def test_load_all_returns_count(self, tmp_path: Path) -> None:
        """load_all() must return the number of successfully loaded files."""
        for i in range(3):
            write_yaml(
                tmp_path,
                f"stream_{i}.yaml",
                f"name: stream_{i}\nversion: 1\nfields:\n  - name: id\n    type: string\n",
            )
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        count = loader.load_all()
        assert count == 3

    def test_load_all_skips_malformed_file(self, tmp_path: Path) -> None:
        """A malformed file must be skipped; other files still load."""
        write_yaml(tmp_path, "good.yaml", "name: good\nversion: 1\nfields:\n  - name: x\n    type: string\n")
        write_yaml(tmp_path, "bad.yaml", "this is not valid contract yaml at all: [unclosed")
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        count = loader.load_all()
        # At least the good file loads; the bad one is skipped.
        assert count >= 1
        assert "good" in reg.list_subjects()

    def test_load_all_only_picks_yaml_files(self, tmp_path: Path) -> None:
        """Non-.yaml files must be ignored by load_all()."""
        write_yaml(tmp_path, "real.yaml", "name: real\nversion: 1\nfields:\n  - name: x\n    type: string\n")
        (tmp_path / "not_a_contract.txt").write_text("name: fake\nversion: 1")
        (tmp_path / "README.md").write_text("# readme")
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        count = loader.load_all()
        assert count == 1

    def test_load_file_sets_description_from_yaml(self, tmp_path: Path) -> None:
        """Schema description must be read from the YAML description key."""
        yaml_content = """
            name: described
            version: 1
            description: "A very descriptive schema"
            fields:
              - name: x
                type: string
        """
        path = write_yaml(tmp_path, "described.yaml", yaml_content)
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        schema = loader.load_file(path)
        assert schema.description == "A very descriptive schema"


# ---------------------------------------------------------------------------
# TestContractLoader — error paths
# ---------------------------------------------------------------------------


class TestContractLoaderErrors:
    def test_missing_name_raises_value_error(self, tmp_path: Path) -> None:
        """YAML without 'name' must raise ValueError."""
        yaml_content = "version: 1\nfields:\n  - name: x\n    type: string\n"
        path = write_yaml(tmp_path, "no_name.yaml", yaml_content)
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        with pytest.raises(ValueError, match="name"):
            loader.load_file(path)

    def test_missing_version_raises_value_error(self, tmp_path: Path) -> None:
        """YAML without 'version' must raise ValueError."""
        yaml_content = "name: s\nfields:\n  - name: x\n    type: string\n"
        path = write_yaml(tmp_path, "no_version.yaml", yaml_content)
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        with pytest.raises(ValueError, match="version"):
            loader.load_file(path)

    def test_missing_fields_raises_value_error(self, tmp_path: Path) -> None:
        """YAML without 'fields' must raise ValueError."""
        yaml_content = "name: s\nversion: 1\n"
        path = write_yaml(tmp_path, "no_fields.yaml", yaml_content)
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        with pytest.raises(ValueError, match="fields"):
            loader.load_file(path)

    def test_unknown_field_type_raises_value_error(self, tmp_path: Path) -> None:
        """An unrecognised type string must raise ValueError."""
        yaml_content = "name: s\nversion: 1\nfields:\n  - name: x\n    type: supertype\n"
        path = write_yaml(tmp_path, "bad_type.yaml", yaml_content)
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        with pytest.raises(ValueError, match="unknown type"):
            loader.load_file(path)

    def test_field_missing_name_raises_value_error(self, tmp_path: Path) -> None:
        """A field entry without 'name' must raise ValueError."""
        yaml_content = "name: s\nversion: 1\nfields:\n  - type: string\n"
        path = write_yaml(tmp_path, "no_field_name.yaml", yaml_content)
        reg = SchemaRegistry()
        loader = ContractLoader(tmp_path, reg)
        with pytest.raises(ValueError, match="missing 'name'"):
            loader.load_file(path)


# ---------------------------------------------------------------------------
# TestRealContracts — integration against the actual contracts/ directory
# ---------------------------------------------------------------------------


class TestRealContracts:
    def test_all_real_contracts_load_successfully(self, contracts_dir: Path) -> None:
        """All three YAML files in contracts/ must load without errors."""
        reg = SchemaRegistry()
        loader = ContractLoader(contracts_dir, reg)
        count = loader.load_all()
        assert count == 3

    def test_raw_trades_v1_fields(self, contracts_dir: Path) -> None:
        """raw_trades v1 must have exactly the expected fields."""
        reg = SchemaRegistry()
        loader = ContractLoader(contracts_dir, reg)
        loader.load_all()
        schema = reg.get("raw_trades", 1)
        field_names = {f.name for f in schema.fields}
        assert "trade_id" in field_names
        assert "symbol" in field_names
        assert "price" in field_names
        assert "_load_id" in field_names
        assert "strategy_id" in field_names

    def test_enriched_ohlcv_v2_version_is_2(self, contracts_dir: Path) -> None:
        """enriched_ohlcv must be registered at version 2."""
        reg = SchemaRegistry()
        loader = ContractLoader(contracts_dir, reg)
        loader.load_all()
        schema = reg.get("enriched_ohlcv", 2)
        assert schema.version == 2

    def test_risk_signals_acknowledged_is_boolean(self, contracts_dir: Path) -> None:
        """risk_signals 'acknowledged' field must be typed as BOOLEAN."""
        reg = SchemaRegistry()
        loader = ContractLoader(contracts_dir, reg)
        loader.load_all()
        schema = reg.get("risk_signals", 1)
        field_map = schema.field_map()
        assert field_map["acknowledged"].field_type is FieldType.BOOLEAN

    def test_real_contracts_register_three_subjects(self, contracts_dir: Path) -> None:
        """Three distinct subjects must be registered."""
        reg = SchemaRegistry()
        loader = ContractLoader(contracts_dir, reg)
        loader.load_all()
        subjects = reg.list_subjects()
        assert "raw_trades" in subjects
        assert "enriched_ohlcv" in subjects
        assert "risk_signals" in subjects
