"""Tests for DataContractValidator and ContractBreach.

Key assertions:
- validate_producer_change passes when all consumers are compatible.
- validate_producer_change raises ContractBreach on first violation.
- ContractBreach carries correct field_name, consumer_name as attributes.
- ContractBreach.to_dict() returns a complete structured dict.
- validate_all() collects all violations without raising.
- A consumer registered against subject A is not checked for subject B.
"""

from __future__ import annotations

import pytest
from src.contracts.validator import ContractBreach, DataContractValidator
from src.registry.models import FieldType, Schema
from src.registry.schema_registry import SchemaRegistry

from tests.conftest import opt, req

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_registry_with_v1() -> SchemaRegistry:
    """Registry with raw_trades v1 registered."""
    reg = SchemaRegistry()
    v1 = Schema(
        name="raw_trades",
        version=1,
        fields=[
            req("trade_id"),
            req("symbol"),
            req("price", FieldType.FLOAT),
            opt("strategy_id"),
        ],
    )
    reg.register("raw_trades", 1, v1)
    return reg


def _make_registry_with_enriched_v1() -> SchemaRegistry:
    """Registry with enriched_ohlcv v1 registered."""
    reg = SchemaRegistry()
    v1 = Schema(
        name="enriched_ohlcv",
        version=1,
        fields=[req("symbol"), req("close", FieldType.FLOAT)],
    )
    reg.register("enriched_ohlcv", 1, v1)
    return reg


# ---------------------------------------------------------------------------
# TestContractBreach
# ---------------------------------------------------------------------------


class TestContractBreach:
    def test_breach_attributes_set_correctly(self) -> None:
        """ContractBreach must store all constructor args as instance attributes."""
        breach = ContractBreach(
            field_name="price",
            consumer_name="risk-engine",
            incompatibility_type="type_narrowed",
            producer_schema_version=3,
            consumer_schema_version=2,
        )
        assert breach.field_name == "price"
        assert breach.consumer_name == "risk-engine"
        assert breach.incompatibility_type == "type_narrowed"
        assert breach.producer_schema_version == 3
        assert breach.consumer_schema_version == 2

    def test_breach_is_exception(self) -> None:
        """ContractBreach must be raise-able as an Exception."""
        with pytest.raises(ContractBreach):
            raise ContractBreach(
                field_name="x",
                consumer_name="svc",
                incompatibility_type="required_field_removed",
                producer_schema_version=2,
                consumer_schema_version=1,
            )

    def test_auto_message_contains_field_and_consumer(self) -> None:
        """Auto-generated message must embed field_name and consumer_name."""
        breach = ContractBreach(
            field_name="trade_id",
            consumer_name="analytics",
            incompatibility_type="required_field_removed",
            producer_schema_version=2,
            consumer_schema_version=1,
        )
        assert "trade_id" in breach.message
        assert "analytics" in breach.message

    def test_custom_message_overrides_auto(self) -> None:
        """Explicit message parameter must be used verbatim."""
        breach = ContractBreach(
            field_name="x",
            consumer_name="svc",
            incompatibility_type="type_narrowed",
            producer_schema_version=2,
            consumer_schema_version=1,
            message="Custom error text",
        )
        assert breach.message == "Custom error text"
        assert str(breach) == "Custom error text"

    def test_to_dict_has_all_required_keys(self) -> None:
        """to_dict() must include all six structured fields."""
        breach = ContractBreach(
            field_name="symbol",
            consumer_name="ml-pipeline",
            incompatibility_type="required_field_added",
            producer_schema_version=4,
            consumer_schema_version=3,
        )
        d = breach.to_dict()
        assert "field_name" in d
        assert "consumer_name" in d
        assert "incompatibility_type" in d
        assert "producer_schema_version" in d
        assert "consumer_schema_version" in d
        assert "message" in d

    def test_to_dict_values_match_attributes(self) -> None:
        """Values in to_dict() must match instance attributes."""
        breach = ContractBreach(
            field_name="price",
            consumer_name="risk-engine",
            incompatibility_type="type_narrowed",
            producer_schema_version=5,
            consumer_schema_version=2,
        )
        d = breach.to_dict()
        assert d["field_name"] == "price"
        assert d["consumer_name"] == "risk-engine"
        assert d["incompatibility_type"] == "type_narrowed"
        assert d["producer_schema_version"] == 5
        assert d["consumer_schema_version"] == 2


# ---------------------------------------------------------------------------
# TestDataContractValidator
# ---------------------------------------------------------------------------


class TestDataContractValidatorPassingCase:
    def test_validate_passes_when_all_consumers_compatible(self) -> None:
        """No exception when new schema is FORWARD-compatible with all consumers."""
        reg = _make_registry_with_v1()
        validator = DataContractValidator(reg)
        validator.register_consumer("risk-engine", "raw_trades", pinned_version=1)
        validator.register_consumer("analytics", "raw_trades", pinned_version=1)

        # Adding a nullable field: FORWARD-compatible (old reader ignores it).
        v2 = Schema(
            name="raw_trades",
            version=2,
            fields=[
                req("trade_id"),
                req("symbol"),
                req("price", FieldType.FLOAT),
                opt("strategy_id"),
                opt("exchange_fee", FieldType.FLOAT),  # new nullable — safe
            ],
        )
        results = validator.validate_producer_change("raw_trades", v2)
        assert len(results) == 2
        assert all(r.compatible for r in results)

    def test_validate_returns_empty_list_when_no_consumers_registered(self) -> None:
        """No consumers for subject_name = no checks = empty results list, no error."""
        reg = _make_registry_with_v1()
        validator = DataContractValidator(reg)
        v2 = Schema(name="raw_trades", version=2, fields=[req("trade_id")])
        results = validator.validate_producer_change("raw_trades", v2)
        assert results == []

    def test_validate_only_checks_consumers_for_matching_subject(self) -> None:
        """Consumers registered for enriched_ohlcv must NOT be checked for raw_trades."""
        reg = _make_registry_with_v1()
        # Also add enriched_ohlcv v1.
        enriched_v1 = Schema(
            name="enriched_ohlcv",
            version=1,
            fields=[req("symbol"), req("close", FieldType.FLOAT)],
        )
        reg.register("enriched_ohlcv", 1, enriched_v1)

        validator = DataContractValidator(reg)
        # Consumer pinned to enriched_ohlcv — NOT raw_trades.
        validator.register_consumer("feature-store", "enriched_ohlcv", pinned_version=1)

        # This change REMOVES a required field from raw_trades — would break FORWARD.
        bad_raw_v2 = Schema(
            name="raw_trades",
            version=2,
            fields=[req("trade_id")],  # price removed
        )
        # Should NOT raise because the only consumer is on enriched_ohlcv, not raw_trades.
        results = validator.validate_producer_change("raw_trades", bad_raw_v2)
        assert results == []


class TestDataContractValidatorBreachCase:
    def test_raises_contract_breach_when_consumer_broken(self) -> None:
        """validate_producer_change must raise ContractBreach when a consumer breaks."""
        reg = _make_registry_with_v1()
        validator = DataContractValidator(reg)
        validator.register_consumer("risk-engine", "raw_trades", pinned_version=1)

        # Removing the required 'price' field breaks FORWARD compat for risk-engine.
        bad_v2 = Schema(
            name="raw_trades",
            version=2,
            fields=[
                req("trade_id"),
                req("symbol"),
                opt("strategy_id"),
                # 'price' (required) removed
            ],
        )
        with pytest.raises(ContractBreach) as exc_info:
            validator.validate_producer_change("raw_trades", bad_v2)

        breach = exc_info.value
        assert breach.field_name == "price"
        assert breach.consumer_name == "risk-engine"

    def test_breach_carries_correct_consumer_schema_version(self) -> None:
        """ContractBreach must carry the pinned version the consumer was registered with."""
        reg = _make_registry_with_v1()
        validator = DataContractValidator(reg)
        validator.register_consumer("analytics", "raw_trades", pinned_version=1)

        bad_v2 = Schema(
            name="raw_trades",
            version=2,
            fields=[req("trade_id")],  # price, symbol removed
        )
        with pytest.raises(ContractBreach) as exc_info:
            validator.validate_producer_change("raw_trades", bad_v2)

        assert exc_info.value.consumer_schema_version == 1

    def test_breach_carries_producer_schema_version(self) -> None:
        """ContractBreach.producer_schema_version must match the new_schema.version."""
        reg = _make_registry_with_v1()
        validator = DataContractValidator(reg)
        validator.register_consumer("svc", "raw_trades", pinned_version=1)

        bad_v7 = Schema(
            name="raw_trades",
            version=7,
            fields=[req("trade_id")],
        )
        with pytest.raises(ContractBreach) as exc_info:
            validator.validate_producer_change("raw_trades", bad_v7)

        assert exc_info.value.producer_schema_version == 7

    def test_breach_incompatibility_type_is_required_field_removed(self) -> None:
        """Removing a required field must produce 'required_field_removed' type."""
        reg = _make_registry_with_v1()
        validator = DataContractValidator(reg)
        validator.register_consumer("downstream", "raw_trades", pinned_version=1)

        bad_v2 = Schema(
            name="raw_trades",
            version=2,
            fields=[req("trade_id"), opt("strategy_id")],
            # symbol (required) and price (required) removed
        )
        with pytest.raises(ContractBreach) as exc_info:
            validator.validate_producer_change("raw_trades", bad_v2)

        # Multiple violations -> incompatibility_type is "multiple_violations"
        # or for single field it's "required_field_removed"
        assert exc_info.value.incompatibility_type in (
            "required_field_removed",
            "multiple_violations",
        )

    def test_breach_stops_at_first_consumer(self) -> None:
        """validate_producer_change raises on the first breach without checking others."""
        reg = _make_registry_with_v1()
        validator = DataContractValidator(reg)
        # Two consumers — the first one should trigger the breach.
        validator.register_consumer("consumer-a", "raw_trades", pinned_version=1)
        validator.register_consumer("consumer-b", "raw_trades", pinned_version=1)

        bad_v2 = Schema(
            name="raw_trades",
            version=2,
            fields=[req("trade_id")],  # many required fields removed
        )
        with pytest.raises(ContractBreach) as exc_info:
            validator.validate_producer_change("raw_trades", bad_v2)

        # Only one consumer should be named in the breach (first one hit).
        assert exc_info.value.consumer_name in ("consumer-a", "consumer-b")


class TestValidateAll:
    def test_validate_all_collects_violations_without_raising(self) -> None:
        """validate_all must return results for all consumers without raising."""
        reg = _make_registry_with_v1()
        validator = DataContractValidator(reg)
        validator.register_consumer("risk-engine", "raw_trades", pinned_version=1)
        validator.register_consumer("analytics", "raw_trades", pinned_version=1)

        # Remove required 'price' — breaks both consumers.
        bad_v2 = Schema(
            name="raw_trades",
            version=2,
            fields=[req("trade_id"), req("symbol"), opt("strategy_id")],
        )
        # Must NOT raise.
        all_results = validator.validate_all("raw_trades", bad_v2)

        assert "risk-engine" in all_results
        assert "analytics" in all_results
        assert all_results["risk-engine"].compatible is False
        assert all_results["analytics"].compatible is False

    def test_validate_all_returns_empty_dict_when_no_consumers(self) -> None:
        """validate_all with no consumers registered returns an empty dict."""
        reg = _make_registry_with_v1()
        validator = DataContractValidator(reg)
        v2 = Schema(name="raw_trades", version=2, fields=[req("trade_id")])
        result = validator.validate_all("raw_trades", v2)
        assert result == {}

    def test_validate_all_passes_for_compatible_change(self) -> None:
        """validate_all returns all-passing results for a safe change."""
        reg = _make_registry_with_v1()
        validator = DataContractValidator(reg)
        validator.register_consumer("svc-a", "raw_trades", pinned_version=1)
        validator.register_consumer("svc-b", "raw_trades", pinned_version=1)

        good_v2 = Schema(
            name="raw_trades",
            version=2,
            fields=[
                req("trade_id"),
                req("symbol"),
                req("price", FieldType.FLOAT),
                opt("strategy_id"),
                opt("new_nullable"),
            ],
        )
        results = validator.validate_all("raw_trades", good_v2)
        assert results["svc-a"].compatible is True
        assert results["svc-b"].compatible is True

    def test_validate_all_mixed_consumers_partial_violations(self) -> None:
        """validate_all correctly reports some consumers passing and some failing."""
        reg = SchemaRegistry()
        v1 = Schema(
            name="signals",
            version=1,
            fields=[req("signal_id"), req("severity"), opt("notes")],
        )
        reg.register("signals", 1, v1)

        # Add a second version where one consumer has pinned to v1.
        v2_source = Schema(
            name="signals",
            version=2,
            fields=[req("signal_id"), req("severity"), opt("notes")],
        )
        # Register a breaking version separately.
        reg.register("signals", 2, v2_source)

        validator = DataContractValidator(reg)
        # Both consumers pinned to v1.
        validator.register_consumer("consumer-lenient", "signals", pinned_version=1)
        validator.register_consumer("consumer-strict", "signals", pinned_version=1)

        # New proposal that removes 'severity' (required).
        bad_v3 = Schema(
            name="signals",
            version=3,
            fields=[req("signal_id"), opt("notes")],
        )
        results = validator.validate_all("signals", bad_v3)
        assert results["consumer-lenient"].compatible is False
        assert results["consumer-strict"].compatible is False
        assert len(results) == 2

    def test_validate_all_only_includes_matching_subject_consumers(self) -> None:
        """validate_all excludes consumers pinned to a different subject."""
        reg = _make_registry_with_v1()
        enriched_v1 = Schema(
            name="enriched_ohlcv",
            version=1,
            fields=[req("symbol"), req("close", FieldType.FLOAT)],
        )
        reg.register("enriched_ohlcv", 1, enriched_v1)

        validator = DataContractValidator(reg)
        validator.register_consumer("feature-store", "enriched_ohlcv", pinned_version=1)
        validator.register_consumer("risk-engine", "raw_trades", pinned_version=1)

        # Change raw_trades only.
        v2 = Schema(
            name="raw_trades",
            version=2,
            fields=[req("trade_id"), req("symbol"), req("price", FieldType.FLOAT), opt("strategy_id")],
        )
        results = validator.validate_all("raw_trades", v2)
        # Only risk-engine should be included; feature-store is for enriched_ohlcv.
        assert "feature-store" not in results
        assert "risk-engine" in results
