"""Tests for the FastAPI REST API (src/api.py).

Uses FastAPI's TestClient (backed by httpx) to exercise every endpoint,
including both success paths and error paths (404, 409, 400).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import app, registry, validator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_api_state():
    """Clear the module-level registry and validator state before each test.

    The API module creates singletons at import time and auto-loads YAML
    contracts.  We snapshot the state, clear it for a clean test, then
    restore it afterwards so that later tests start from a known baseline.
    """
    # Save original state.
    original_store = dict(registry._store)
    original_consumers = dict(validator._consumer_contracts)

    # Clear for a clean test environment.
    registry._store.clear()
    validator._consumer_contracts.clear()

    yield

    # Restore original state.
    registry._store.clear()
    registry._store.update(original_store)
    validator._consumer_contracts.clear()
    validator._consumer_contracts.update(original_consumers)


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient instance."""
    return TestClient(app)


def _register_test_schema(client: TestClient, name: str = "test_subject", version: int = 1) -> dict:
    """Helper to register a basic schema and return the response JSON."""
    body = {
        "name": name,
        "version": version,
        "description": "Test schema",
        "fields": [
            {"name": "id", "type": "string", "nullable": False},
            {"name": "price", "type": "float", "nullable": False},
            {"name": "description", "type": "string", "nullable": True},
        ],
    }
    resp = client.post("/schemas", json=body)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_empty_registry(self, client: TestClient) -> None:
        """Health check on empty registry returns status=healthy with zero counts."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["subjects"] == 0
        assert data["consumers"] == 0

    def test_health_after_registration(self, client: TestClient) -> None:
        """Health check reflects the number of subjects and consumers."""
        _register_test_schema(client)
        # Register a consumer.
        client.post(
            "/consumers",
            json={"consumer_name": "svc-a", "subject_name": "test_subject", "pinned_version": 1},
        )

        resp = client.get("/health")
        data = resp.json()
        assert data["subjects"] == 1
        assert data["consumers"] == 1


# ---------------------------------------------------------------------------
# GET /subjects
# ---------------------------------------------------------------------------


class TestListSubjects:
    def test_empty_registry(self, client: TestClient) -> None:
        """Empty registry returns an empty subjects list."""
        resp = client.get("/subjects")
        assert resp.status_code == 200
        assert resp.json() == {"subjects": []}

    def test_lists_registered_subjects(self, client: TestClient) -> None:
        """Lists all registered subjects in sorted order."""
        _register_test_schema(client, name="beta")
        _register_test_schema(client, name="alpha")
        resp = client.get("/subjects")
        assert resp.status_code == 200
        assert resp.json()["subjects"] == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# GET /subjects/{name}/versions
# ---------------------------------------------------------------------------


class TestListVersions:
    def test_known_subject(self, client: TestClient) -> None:
        """Returns sorted version list for a known subject."""
        _register_test_schema(client, name="trades", version=1)
        _register_test_schema(client, name="trades", version=3)
        _register_test_schema(client, name="trades", version=2)

        resp = client.get("/subjects/trades/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["subject"] == "trades"
        assert data["versions"] == [1, 2, 3]

    def test_unknown_subject_returns_404(self, client: TestClient) -> None:
        """Requesting versions for a non-existent subject returns 404."""
        resp = client.get("/subjects/no_such_subject/versions")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /schemas/{name}/{version}
# ---------------------------------------------------------------------------


class TestGetSchema:
    def test_get_existing_schema(self, client: TestClient) -> None:
        """Retrieving a registered schema returns the expected structure."""
        _register_test_schema(client, name="trades", version=1)
        resp = client.get("/schemas/trades/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "trades"
        assert data["version"] == 1
        assert len(data["fields"]) == 3
        # Verify field structure.
        id_field = next(f for f in data["fields"] if f["name"] == "id")
        assert id_field["type"] == "string"
        assert id_field["nullable"] is False
        assert id_field["required"] is True

    def test_get_schema_unknown_subject_returns_404(self, client: TestClient) -> None:
        """Requesting a non-existent subject returns 404."""
        resp = client.get("/schemas/nonexistent/1")
        assert resp.status_code == 404

    def test_get_schema_unknown_version_returns_404(self, client: TestClient) -> None:
        """Requesting a registered subject but non-existent version returns 404."""
        _register_test_schema(client, name="trades", version=1)
        resp = client.get("/schemas/trades/99")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /schemas/{name}/latest
# ---------------------------------------------------------------------------


class TestGetLatestSchema:
    def test_get_latest_returns_highest_version(self, client: TestClient) -> None:
        """latest endpoint returns the schema with the highest version number."""
        _register_test_schema(client, name="trades", version=1)
        _register_test_schema(client, name="trades", version=2)
        resp = client.get("/schemas/trades/latest")
        assert resp.status_code == 200
        assert resp.json()["version"] == 2

    def test_get_latest_unknown_subject_returns_404(self, client: TestClient) -> None:
        """Requesting latest for a non-existent subject returns 404."""
        resp = client.get("/schemas/nonexistent/latest")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /schemas  (register new schema)
# ---------------------------------------------------------------------------


class TestRegisterSchema:
    def test_register_new_schema(self, client: TestClient) -> None:
        """Registering a new schema returns 201 with the schema data."""
        data = _register_test_schema(client)
        assert data["name"] == "test_subject"
        assert data["version"] == 1
        assert data["registered_at"] is not None
        assert len(data["fields"]) == 3

    def test_register_duplicate_returns_409(self, client: TestClient) -> None:
        """Re-registering the same (name, version) pair returns 409."""
        _register_test_schema(client, name="trades", version=1)
        body = {
            "name": "trades",
            "version": 1,
            "fields": [{"name": "id", "type": "string", "nullable": False}],
        }
        resp = client.post("/schemas", json=body)
        assert resp.status_code == 409
        assert "already registered" in resp.json()["detail"].lower()

    def test_register_unknown_field_type_returns_400(self, client: TestClient) -> None:
        """Using an invalid field type returns 400."""
        body = {
            "name": "bad",
            "version": 1,
            "fields": [{"name": "x", "type": "banana", "nullable": True}],
        }
        resp = client.post("/schemas", json=body)
        assert resp.status_code == 400
        assert "unknown field type" in resp.json()["detail"].lower()

    def test_register_all_field_types(self, client: TestClient) -> None:
        """All valid field types should be accepted."""
        body = {
            "name": "all_types",
            "version": 1,
            "fields": [
                {"name": "f_string", "type": "string", "nullable": True},
                {"name": "f_integer", "type": "integer", "nullable": True},
                {"name": "f_float", "type": "float", "nullable": True},
                {"name": "f_boolean", "type": "boolean", "nullable": True},
                {"name": "f_timestamp", "type": "timestamp", "nullable": True},
                {"name": "f_array", "type": "array", "nullable": True},
                {"name": "f_object", "type": "object", "nullable": True},
            ],
        }
        resp = client.post("/schemas", json=body)
        assert resp.status_code == 201
        assert len(resp.json()["fields"]) == 7

    def test_register_with_defaults(self, client: TestClient) -> None:
        """Fields with defaults should be accepted and reflected in output."""
        body = {
            "name": "defaults_test",
            "version": 1,
            "fields": [
                {
                    "name": "status",
                    "type": "string",
                    "nullable": False,
                    "default": "active",
                    "description": "Account status",
                },
            ],
        }
        resp = client.post("/schemas", json=body)
        assert resp.status_code == 201
        field = resp.json()["fields"][0]
        assert field["default"] == "active"
        assert field["description"] == "Account status"
        # Non-nullable with default => not required.
        assert field["required"] is False

    def test_register_schema_missing_fields_returns_422(self, client: TestClient) -> None:
        """A request body missing required keys returns 422 (validation error)."""
        # Missing 'fields' entirely.
        resp = client.post("/schemas", json={"name": "bad", "version": 1})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /compatibility/check
# ---------------------------------------------------------------------------


class TestCompatibilityCheck:
    def test_compatible_change(self, client: TestClient) -> None:
        """Adding a nullable field should be compatible (FORWARD)."""
        _register_test_schema(client, name="trades", version=1)
        body = {
            "subject_name": "trades",
            "mode": "FORWARD",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [
                    {"name": "id", "type": "string", "nullable": False},
                    {"name": "price", "type": "float", "nullable": False},
                    {"name": "description", "type": "string", "nullable": True},
                    {"name": "exchange", "type": "string", "nullable": True},
                ],
            },
        }
        resp = client.post("/compatibility/check", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["compatible"] is True
        assert data["mode"] == "FORWARD"
        assert data["violations"] == []

    def test_incompatible_change(self, client: TestClient) -> None:
        """Removing a required field breaks FORWARD compatibility."""
        _register_test_schema(client, name="trades", version=1)
        body = {
            "subject_name": "trades",
            "mode": "FORWARD",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [
                    {"name": "id", "type": "string", "nullable": False},
                    # 'price' (required) removed.
                ],
            },
        }
        resp = client.post("/compatibility/check", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["compatible"] is False
        assert len(data["violations"]) > 0
        assert any("price" in v for v in data["violations"])

    def test_backward_mode(self, client: TestClient) -> None:
        """BACKWARD mode detects adding a required field."""
        _register_test_schema(client, name="trades", version=1)
        body = {
            "subject_name": "trades",
            "mode": "BACKWARD",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [
                    {"name": "id", "type": "string", "nullable": False},
                    {"name": "price", "type": "float", "nullable": False},
                    {"name": "description", "type": "string", "nullable": True},
                    {"name": "new_required", "type": "integer", "nullable": False},
                ],
            },
        }
        resp = client.post("/compatibility/check", json=body)
        data = resp.json()
        assert data["compatible"] is False
        assert data["mode"] == "BACKWARD"

    def test_full_mode(self, client: TestClient) -> None:
        """FULL mode detects violations in both directions."""
        _register_test_schema(client, name="trades", version=1)
        body = {
            "subject_name": "trades",
            "mode": "FULL",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [
                    {"name": "id", "type": "string", "nullable": False},
                    {"name": "price", "type": "float", "nullable": False},
                    {"name": "description", "type": "string", "nullable": True},
                    {"name": "new_required", "type": "integer", "nullable": False},
                ],
            },
        }
        resp = client.post("/compatibility/check", json=body)
        data = resp.json()
        assert data["compatible"] is False
        assert data["mode"] == "FULL"

    def test_invalid_mode_returns_422(self, client: TestClient) -> None:
        """Using an invalid compatibility mode returns 422 (Pydantic validation)."""
        _register_test_schema(client, name="trades", version=1)
        body = {
            "subject_name": "trades",
            "mode": "INVALID_MODE",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [{"name": "id", "type": "string", "nullable": False}],
            },
        }
        resp = client.post("/compatibility/check", json=body)
        assert resp.status_code == 422

    def test_unknown_subject_returns_404(self, client: TestClient) -> None:
        """Checking compatibility against a non-existent subject returns 404."""
        body = {
            "subject_name": "nonexistent",
            "mode": "FORWARD",
            "new_schema": {
                "name": "nonexistent",
                "version": 2,
                "fields": [{"name": "id", "type": "string", "nullable": False}],
            },
        }
        resp = client.post("/compatibility/check", json=body)
        assert resp.status_code == 404

    def test_unknown_field_type_in_new_schema_returns_400(self, client: TestClient) -> None:
        """An invalid field type in the new_schema returns 400."""
        _register_test_schema(client, name="trades", version=1)
        body = {
            "subject_name": "trades",
            "mode": "FORWARD",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [{"name": "id", "type": "invalid_type", "nullable": False}],
            },
        }
        resp = client.post("/compatibility/check", json=body)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /consumers
# ---------------------------------------------------------------------------


class TestListConsumers:
    def test_empty_consumers(self, client: TestClient) -> None:
        """Empty consumer list returns an empty array."""
        resp = client.get("/consumers")
        assert resp.status_code == 200
        assert resp.json() == {"consumers": []}

    def test_lists_registered_consumers(self, client: TestClient) -> None:
        """Lists all registered consumers with their pinned versions."""
        _register_test_schema(client, name="trades", version=1)
        client.post(
            "/consumers",
            json={"consumer_name": "risk-engine", "subject_name": "trades", "pinned_version": 1},
        )
        client.post(
            "/consumers",
            json={"consumer_name": "ml-pipeline", "subject_name": "trades", "pinned_version": 1},
        )

        resp = client.get("/consumers")
        assert resp.status_code == 200
        consumers = resp.json()["consumers"]
        assert len(consumers) == 2
        names = {c["consumer_name"] for c in consumers}
        assert names == {"risk-engine", "ml-pipeline"}


# ---------------------------------------------------------------------------
# POST /consumers  (register consumer)
# ---------------------------------------------------------------------------


class TestRegisterConsumer:
    def test_register_consumer_success(self, client: TestClient) -> None:
        """Registering a consumer returns 201 with the registration details."""
        _register_test_schema(client, name="trades", version=1)
        resp = client.post(
            "/consumers",
            json={"consumer_name": "risk-engine", "subject_name": "trades", "pinned_version": 1},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["consumer_name"] == "risk-engine"
        assert data["subject_name"] == "trades"
        assert data["pinned_version"] == 1

    def test_register_consumer_nonexistent_schema_returns_404(self, client: TestClient) -> None:
        """Pinning to a non-existent schema version returns 404."""
        resp = client.post(
            "/consumers",
            json={"consumer_name": "svc-a", "subject_name": "nonexistent", "pinned_version": 1},
        )
        assert resp.status_code == 404

    def test_register_consumer_nonexistent_version_returns_404(self, client: TestClient) -> None:
        """Pinning to a non-existent version of an existing subject returns 404."""
        _register_test_schema(client, name="trades", version=1)
        resp = client.post(
            "/consumers",
            json={"consumer_name": "svc-a", "subject_name": "trades", "pinned_version": 99},
        )
        assert resp.status_code == 404

    def test_register_consumer_updates_existing(self, client: TestClient) -> None:
        """Re-registering the same consumer name overwrites the previous pin."""
        _register_test_schema(client, name="trades", version=1)
        _register_test_schema(client, name="trades", version=2)

        client.post(
            "/consumers",
            json={"consumer_name": "svc-a", "subject_name": "trades", "pinned_version": 1},
        )
        resp = client.post(
            "/consumers",
            json={"consumer_name": "svc-a", "subject_name": "trades", "pinned_version": 2},
        )
        assert resp.status_code == 201
        assert resp.json()["pinned_version"] == 2

        # Only one consumer should exist.
        consumers_resp = client.get("/consumers")
        assert len(consumers_resp.json()["consumers"]) == 1


# ---------------------------------------------------------------------------
# POST /consumers/validate
# ---------------------------------------------------------------------------


class TestConsumerValidate:
    def test_validate_all_compatible(self, client: TestClient) -> None:
        """When all consumers are compatible, all_compatible is True."""
        _register_test_schema(client, name="trades", version=1)
        client.post(
            "/consumers",
            json={"consumer_name": "risk-engine", "subject_name": "trades", "pinned_version": 1},
        )

        body = {
            "subject_name": "trades",
            "mode": "FORWARD",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [
                    {"name": "id", "type": "string", "nullable": False},
                    {"name": "price", "type": "float", "nullable": False},
                    {"name": "description", "type": "string", "nullable": True},
                    {"name": "exchange", "type": "string", "nullable": True},
                ],
            },
        }
        resp = client.post("/consumers/validate", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["subject"] == "trades"
        assert data["proposed_version"] == 2
        assert data["mode"] == "FORWARD"
        assert data["all_compatible"] is True
        assert data["consumers"]["risk-engine"]["compatible"] is True
        assert data["consumers"]["risk-engine"]["violations"] == []

    def test_validate_breaking_change(self, client: TestClient) -> None:
        """Removing a required field should break the consumer contract."""
        _register_test_schema(client, name="trades", version=1)
        client.post(
            "/consumers",
            json={"consumer_name": "risk-engine", "subject_name": "trades", "pinned_version": 1},
        )

        body = {
            "subject_name": "trades",
            "mode": "FORWARD",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [
                    {"name": "id", "type": "string", "nullable": False},
                    # 'price' removed — breaks the consumer.
                ],
            },
        }
        resp = client.post("/consumers/validate", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_compatible"] is False
        assert data["consumers"]["risk-engine"]["compatible"] is False
        assert len(data["consumers"]["risk-engine"]["violations"]) > 0

    def test_validate_no_consumers(self, client: TestClient) -> None:
        """When no consumers exist, all_compatible is True (vacuously)."""
        body = {
            "subject_name": "trades",
            "mode": "FORWARD",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [{"name": "id", "type": "string", "nullable": False}],
            },
        }
        resp = client.post("/consumers/validate", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_compatible"] is True
        assert data["consumers"] == {}

    def test_validate_invalid_mode_returns_422(self, client: TestClient) -> None:
        """Using an invalid compatibility mode returns 422 (Pydantic validation)."""
        body = {
            "subject_name": "trades",
            "mode": "BANANA",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [{"name": "id", "type": "string", "nullable": False}],
            },
        }
        resp = client.post("/consumers/validate", json=body)
        assert resp.status_code == 422

    def test_validate_unknown_field_type_returns_400(self, client: TestClient) -> None:
        """An invalid field type in the proposed schema returns 400."""
        body = {
            "subject_name": "trades",
            "mode": "FORWARD",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [{"name": "id", "type": "bad_type", "nullable": False}],
            },
        }
        resp = client.post("/consumers/validate", json=body)
        assert resp.status_code == 400

    def test_validate_multiple_consumers_mixed(self, client: TestClient) -> None:
        """Multiple consumers with mixed compatibility results."""
        _register_test_schema(client, name="trades", version=1)

        # Consumer A pinned to v1.
        client.post(
            "/consumers",
            json={"consumer_name": "svc-a", "subject_name": "trades", "pinned_version": 1},
        )
        # Consumer B pinned to v1 as well.
        client.post(
            "/consumers",
            json={"consumer_name": "svc-b", "subject_name": "trades", "pinned_version": 1},
        )

        # A schema change that removes required 'price' — both should break.
        body = {
            "subject_name": "trades",
            "mode": "FORWARD",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [
                    {"name": "id", "type": "string", "nullable": False},
                    # 'price' removed.
                ],
            },
        }
        resp = client.post("/consumers/validate", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_compatible"] is False
        # Both consumers should be reported.
        assert len(data["consumers"]) == 2

    def test_validate_consumers_only_matching_subject(self, client: TestClient) -> None:
        """Only consumers pinned to the changed subject are evaluated."""
        _register_test_schema(client, name="trades", version=1)
        _register_test_schema(client, name="orders", version=1)

        # Consumer pinned to 'orders' (different subject).
        client.post(
            "/consumers",
            json={"consumer_name": "orders-svc", "subject_name": "orders", "pinned_version": 1},
        )

        # Validate against 'trades' — orders-svc should not appear.
        body = {
            "subject_name": "trades",
            "mode": "FORWARD",
            "new_schema": {
                "name": "trades",
                "version": 2,
                "fields": [{"name": "id", "type": "string", "nullable": False}],
            },
        }
        resp = client.post("/consumers/validate", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert "orders-svc" not in data["consumers"]


# ---------------------------------------------------------------------------
# Schema conversion edge cases
# ---------------------------------------------------------------------------


class TestSchemaConversion:
    def test_schema_to_dict_has_registered_at(self, client: TestClient) -> None:
        """Registered schemas should have a non-null registered_at ISO timestamp."""
        _register_test_schema(client)
        resp = client.get("/schemas/test_subject/1")
        data = resp.json()
        assert data["registered_at"] is not None
        # Should be a valid ISO-8601 string.
        assert "T" in data["registered_at"]

    def test_nullable_field_is_not_required(self, client: TestClient) -> None:
        """A nullable field with no default should not be required."""
        _register_test_schema(client)
        resp = client.get("/schemas/test_subject/1")
        desc_field = next(f for f in resp.json()["fields"] if f["name"] == "description")
        assert desc_field["nullable"] is True
        assert desc_field["required"] is False

    def test_non_nullable_field_is_required(self, client: TestClient) -> None:
        """A non-nullable field with no default should be required."""
        _register_test_schema(client)
        resp = client.get("/schemas/test_subject/1")
        id_field = next(f for f in resp.json()["fields"] if f["name"] == "id")
        assert id_field["nullable"] is False
        assert id_field["required"] is True
