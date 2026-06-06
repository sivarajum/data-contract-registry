"""FastAPI REST API for the Data Contract Registry.

Exposes schema registration, retrieval, compatibility checking,
consumer contract management, and validation over HTTP.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.contracts.loader import ContractLoader
from src.contracts.validator import ContractBreach, DataContractValidator
from src.registry.models import CompatibilityMode, FieldType
from src.registry.models import Schema as DomainSchema
from src.registry.models import SchemaField
from src.registry.schema_registry import SchemaRegistry
from src.settings import CONTRACTS_DIR, CORS_ORIGINS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton registry + validator (created at import time)
# ---------------------------------------------------------------------------

registry = SchemaRegistry(thread_safe=True)
validator = DataContractValidator(registry)

# Load YAML contracts from the contracts/ directory if it exists.
_contracts_dir = Path(__file__).parent.parent / CONTRACTS_DIR
if _contracts_dir.is_dir():
    loader = ContractLoader(_contracts_dir, registry)
    _loaded = loader.load_all()
    logger.info("Auto-loaded %d contract(s) from %s", _loaded, _contracts_dir)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

_VALID_FIELD_TYPES = ", ".join(ft.value for ft in FieldType)
_VALID_MODES = "BACKWARD, FORWARD, FULL"


class FieldModel(BaseModel):
    name: str = Field(
        ..., min_length=1, max_length=128, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$",
        description="Field name (valid identifier)",
    )
    field_type: str = Field(
        alias="type",
        min_length=1, max_length=32,
        description=f"Field data type. Valid: {_VALID_FIELD_TYPES}",
    )
    nullable: bool = Field(default=True, description="Whether the field may be NULL")
    description: str = Field(default="", max_length=1024, description="Human-readable documentation")
    default: Optional[Any] = Field(default=None, description="Default value for absent data")

    model_config = {"populate_by_name": True}


class SchemaModel(BaseModel):
    name: str = Field(
        ..., min_length=1, max_length=128, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$",
        description="Schema subject name",
    )
    version: int = Field(..., ge=1, le=99999, description="Schema version (positive integer)")
    fields: list[FieldModel] = Field(..., min_length=1, description="Schema field definitions")
    description: str = Field(default="", max_length=2048, description="Schema description")


class ConsumerRegistration(BaseModel):
    consumer_name: str = Field(
        ..., min_length=1, max_length=128,
        description="Consumer service identifier",
    )
    subject_name: str = Field(
        ..., min_length=1, max_length=128,
        description="Schema subject the consumer depends on",
    )
    pinned_version: int = Field(..., ge=1, le=99999, description="Pinned schema version")


class CompatibilityRequest(BaseModel):
    subject_name: str = Field(
        ..., min_length=1, max_length=128,
        description="Subject to check compatibility against",
    )
    new_schema: SchemaModel = Field(..., description="Proposed new schema")
    mode: str = Field(
        default="FORWARD", pattern=r"^(BACKWARD|FORWARD|FULL)$",
        description=f"Compatibility mode. Valid: {_VALID_MODES}",
    )


class HealthResponse(BaseModel):
    status: str = "healthy"
    subjects: int = 0
    consumers: int = 0


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

_TYPE_MAP = {ft.value: ft for ft in FieldType}


def _to_domain_schema(model: SchemaModel) -> DomainSchema:
    """Convert a Pydantic SchemaModel to the domain Schema."""
    fields = []
    for f in model.fields:
        ft = _TYPE_MAP.get(f.field_type)
        if ft is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown field type {f.field_type!r}. Valid: {list(_TYPE_MAP.keys())}",
            )
        fields.append(
            SchemaField(
                name=f.name,
                field_type=ft,
                nullable=f.nullable,
                description=f.description,
                default=f.default,
            )
        )
    return DomainSchema(
        name=model.name,
        version=model.version,
        fields=fields,
        description=model.description,
    )


def _schema_to_dict(schema: DomainSchema) -> dict:
    """Convert a domain Schema to a JSON-friendly dict."""
    return {
        "name": schema.name,
        "version": schema.version,
        "description": schema.description,
        "registered_at": schema.registered_at.isoformat() if schema.registered_at else None,
        "fields": [
            {
                "name": f.name,
                "type": f.field_type.value,
                "nullable": f.nullable,
                "description": f.description,
                "default": f.default,
                "required": f.is_required(),
            }
            for f in schema.fields
        ],
    }


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Data Contract Registry",
    description="Schema registry with consumer-driven contract validation",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        subjects=len(registry.list_subjects()),
        consumers=len(validator._consumer_contracts),
    )


# -- Subjects ---------------------------------------------------------------


@app.get("/subjects")
def list_subjects() -> dict:
    """List all registered schema subjects."""
    return {"subjects": registry.list_subjects()}


@app.get("/subjects/{name}/versions")
def list_versions(name: str) -> dict:
    """List all registered versions for a subject."""
    versions = registry.list_versions(name)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Subject '{name}' not found.")
    return {"subject": name, "versions": versions}


# -- Schemas -----------------------------------------------------------------


@app.get("/schemas/{name}/latest")
def get_latest_schema(name: str) -> dict:
    """Retrieve the latest schema version for a subject."""
    try:
        schema = registry.get_latest(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _schema_to_dict(schema)


@app.get("/schemas/{name}/{version}")
def get_schema(name: str, version: int) -> dict:
    """Retrieve a specific schema version."""
    try:
        schema = registry.get(name, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _schema_to_dict(schema)


@app.post("/schemas", status_code=201)
def register_schema(body: SchemaModel) -> dict:
    """Register a new schema version."""
    domain = _to_domain_schema(body)
    try:
        registered = registry.register(domain.name, domain.version, domain)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    logger.info("Registered schema %s v%d via API", body.name, body.version)
    return _schema_to_dict(registered)


# -- Compatibility -----------------------------------------------------------


@app.post("/compatibility/check")
def check_compatibility(body: CompatibilityRequest) -> dict:
    """Check compatibility of a proposed schema against the latest registered version."""
    try:
        mode = CompatibilityMode(body.mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode {body.mode!r}. Use BACKWARD, FORWARD, or FULL.",
        )

    domain = _to_domain_schema(body.new_schema)
    try:
        result = registry.check_compatibility(body.subject_name, domain, mode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "compatible": result.compatible,
        "mode": result.mode.value,
        "violations": result.violations,
    }


# -- Consumer Contracts ------------------------------------------------------


@app.post("/consumers", status_code=201)
def register_consumer(body: ConsumerRegistration) -> dict:
    """Register a consumer's schema dependency."""
    # Verify the pinned schema exists.
    try:
        registry.get(body.subject_name, body.pinned_version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    validator.register_consumer(body.consumer_name, body.subject_name, body.pinned_version)
    logger.info(
        "Registered consumer %r -> %s v%d via API",
        body.consumer_name, body.subject_name, body.pinned_version,
    )
    return {
        "consumer_name": body.consumer_name,
        "subject_name": body.subject_name,
        "pinned_version": body.pinned_version,
    }


@app.get("/consumers")
def list_consumers() -> dict:
    """List all registered consumers."""
    consumers = []
    for name, (subject, version) in validator._consumer_contracts.items():
        consumers.append({
            "consumer_name": name,
            "subject_name": subject,
            "pinned_version": version,
        })
    return {"consumers": consumers}


@app.post("/consumers/validate")
def validate_change(body: CompatibilityRequest) -> dict:
    """Validate a proposed schema change against all registered consumers."""
    try:
        mode = CompatibilityMode(body.mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode {body.mode!r}. Use BACKWARD, FORWARD, or FULL.",
        )

    domain = _to_domain_schema(body.new_schema)
    results = validator.validate_all(body.subject_name, domain, mode)

    return {
        "subject": body.subject_name,
        "proposed_version": body.new_schema.version,
        "mode": mode.value,
        "consumers": {
            name: {
                "compatible": r.compatible,
                "violations": r.violations,
            }
            for name, r in results.items()
        },
        "all_compatible": all(r.compatible for r in results.values()),
    }
