# Data Contract Registry -- Build, Test & Run

## Prerequisites

- Python 3.11 or later
- pip (bundled with Python 3.11+)
- Docker and Docker Compose (optional, for containerized deployment)

## Install

```bash
cd Sj-Prod/Data-Contract-Registry
pip install -r requirements.txt
```

The key dependencies are:

| Package | Purpose |
|---------|---------|
| pyyaml | YAML contract file parsing |
| fastapi | REST API framework |
| uvicorn | ASGI server for FastAPI |
| pydantic | Request/response validation |
| streamlit | Interactive dashboard UI |
| pytest, pytest-cov | Test runner with coverage |
| httpx | HTTP client used by FastAPI TestClient |
| ruff | Linting and formatting |
| mypy | Static type checking |

## Running Tests

All commands should be run from the `Data-Contract-Registry/` directory.

### Default (uses pytest.ini config)

```bash
pytest
```

This runs all unit tests with coverage enforcement (80% minimum). The configuration in `pytest.ini` automatically adds `--cov=src --cov-fail-under=80`.

### Verbose with coverage report

```bash
pytest -v --cov-report=term-missing
```

### Run a single test file

```bash
pytest tests/test_api.py -v
pytest tests/test_registry.py -v
pytest tests/test_compatibility.py -v
pytest tests/test_validator.py -v
pytest tests/test_loader.py -v
```

### Run a single test

```bash
pytest tests/test_api.py::TestRegisterSchema::test_register_new_schema -v
```

### Skip integration tests (if any require GCP credentials)

```bash
pytest -m "not integration"
```

### Lint and type check

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/ --ignore-missing-imports
```

### Using the Makefile

```bash
make test-unit     # unit tests only
make test-cov      # with coverage
make lint          # ruff + mypy
make fmt           # auto-format
```

## Running the System

The system has four run modes, all invoked through `main.py`.

### API Server (FastAPI) -- default mode

```bash
python main.py api
# or simply:
python main.py
```

- API: http://localhost:8000
- Interactive docs (Swagger): http://localhost:8000/docs
- Alternative docs (ReDoc): http://localhost:8000/redoc

The API auto-loads all YAML contract files from the `contracts/` directory on startup.

### Streamlit Dashboard

```bash
python main.py ui
```

- Dashboard: http://localhost:8501

### Both API + UI simultaneously

```bash
python main.py all
```

- API: http://localhost:8000
- UI: http://localhost:8501

The API process starts first, then the Streamlit UI launches. Both are terminated together.

### Validate Contracts (CLI demo)

```bash
python main.py validate
```

Loads all YAML contracts from `contracts/`, registers sample consumers, and runs sample compatibility checks to demonstrate the validation workflow. Useful for verifying the system works end-to-end without starting a server.

## Running with Docker

### Build and start all services

```bash
docker compose up --build
```

- API: http://localhost:8000
- UI: http://localhost:8501

### Run only the API

```bash
docker compose up --build api
```

### Stop all services

```bash
docker compose down
```

### Build the image manually

```bash
docker build -t data-contract-registry .
docker run -p 8000:8000 data-contract-registry uvicorn src.api:app --host 0.0.0.0 --port 8000
```

## API Endpoint Reference

All endpoints accept and return JSON. The base URL is `http://localhost:8000`.

### Health Check

```
GET /health
```

Returns system status with subject and consumer counts.

**Response 200:**
```json
{
  "status": "healthy",
  "subjects": 3,
  "consumers": 2
}
```

### List Subjects

```
GET /subjects
```

Returns all registered schema subject names in sorted order.

**Response 200:**
```json
{
  "subjects": ["enriched_ohlcv", "raw_trades", "risk_signals"]
}
```

### List Versions

```
GET /subjects/{name}/versions
```

Returns all registered version numbers for a subject, sorted ascending.

**Response 200:**
```json
{
  "subject": "raw_trades",
  "versions": [1, 2]
}
```

**Response 404:** Subject not found.

### Get Schema by Version

```
GET /schemas/{name}/{version}
```

Retrieves a specific schema version.

**Response 200:**
```json
{
  "name": "raw_trades",
  "version": 1,
  "description": "Raw trade events",
  "registered_at": "2025-01-15T10:30:00+00:00",
  "fields": [
    {
      "name": "trade_id",
      "type": "string",
      "nullable": false,
      "description": "Unique trade identifier",
      "default": null,
      "required": true
    }
  ]
}
```

**Response 404:** Subject or version not found.

### Get Latest Schema

```
GET /schemas/{name}/latest
```

Retrieves the schema with the highest version number for a subject.

**Response 200:** Same structure as Get Schema by Version.

**Response 404:** Subject not found.

### Register a Schema

```
POST /schemas
Content-Type: application/json
```

**Request body:**
```json
{
  "name": "raw_trades",
  "version": 2,
  "description": "Raw trade events v2",
  "fields": [
    {
      "name": "trade_id",
      "type": "string",
      "nullable": false,
      "description": "Unique trade identifier"
    },
    {
      "name": "exchange",
      "type": "string",
      "nullable": true,
      "default": null
    }
  ]
}
```

Valid field types: `string`, `integer`, `float`, `boolean`, `timestamp`, `array`, `object`.

**Response 201:** The registered schema (same structure as Get Schema).

**Response 400:** Invalid field type.

**Response 409:** Schema version already registered.

### Check Compatibility

```
POST /compatibility/check
Content-Type: application/json
```

Checks a proposed schema against the latest registered version of a subject.

**Request body:**
```json
{
  "subject_name": "raw_trades",
  "mode": "FORWARD",
  "new_schema": {
    "name": "raw_trades",
    "version": 2,
    "fields": [
      {"name": "trade_id", "type": "string", "nullable": false}
    ]
  }
}
```

Valid modes: `BACKWARD`, `FORWARD`, `FULL`.

**Response 200:**
```json
{
  "compatible": false,
  "mode": "FORWARD",
  "violations": [
    "FORWARD violation: required field 'price' removed from new schema ..."
  ]
}
```

**Response 400:** Invalid compatibility mode or field type.

**Response 404:** Subject not found.

### List Consumers

```
GET /consumers
```

Returns all registered consumer contracts.

**Response 200:**
```json
{
  "consumers": [
    {
      "consumer_name": "risk-engine",
      "subject_name": "raw_trades",
      "pinned_version": 1
    }
  ]
}
```

### Register a Consumer

```
POST /consumers
Content-Type: application/json
```

Registers a consumer's dependency on a specific schema version.

**Request body:**
```json
{
  "consumer_name": "risk-engine",
  "subject_name": "raw_trades",
  "pinned_version": 1
}
```

**Response 201:** The registration details echoed back.

**Response 404:** The pinned schema version does not exist.

### Validate Consumer Contracts

```
POST /consumers/validate
Content-Type: application/json
```

Validates a proposed schema change against all registered consumers for a subject.

**Request body:** Same as `/compatibility/check`.

**Response 200:**
```json
{
  "subject": "raw_trades",
  "proposed_version": 2,
  "mode": "FORWARD",
  "consumers": {
    "risk-engine": {
      "compatible": true,
      "violations": []
    },
    "ml-pipeline": {
      "compatible": false,
      "violations": ["FORWARD violation: ..."]
    }
  },
  "all_compatible": false
}
```

**Response 400:** Invalid compatibility mode or field type.

## Production Deployment Notes

1. **In-memory storage.** The registry is dict-backed. All schemas are lost on restart. For durability, swap `SchemaRegistry._store` for a database-backed implementation (PostgreSQL, Redis, etc.) behind the same interface.

2. **Thread safety.** The API creates the registry with `SchemaRegistry(thread_safe=True)`, which guards all reads and writes with a `threading.Lock`. This is safe for uvicorn's default thread-pool workers.

3. **Auto-loading contracts.** YAML files in the `contracts/` directory are automatically loaded when the API module is imported. Add new contract files there and restart the server.

4. **Structured alerting.** The `ContractBreach` exception provides `.to_dict()` for structured logging/alerting integration (PagerDuty, Cloud Logging, etc.).

5. **Scaling.** For multi-process deployments (e.g., gunicorn with multiple workers), each worker gets its own in-memory registry. Use a shared database backend or run a single API process behind a load balancer.

6. **CORS.** If the Streamlit UI or other frontends run on a different origin, add FastAPI CORS middleware to `src/api.py`.

7. **Health checks.** The `/health` endpoint is suitable for container orchestrators (Kubernetes liveness/readiness probes, Docker healthchecks). The `docker-compose.yml` already configures a healthcheck for the API service.

## Architecture

```
src/
  registry/
    models.py           -- Schema, SchemaField, CompatibilityMode, CompatibilityResult
    compatibility.py    -- check_backward / check_forward / check_full
    schema_registry.py  -- SchemaRegistry (dict-backed, thread-safe)
  contracts/
    validator.py        -- DataContractValidator + ContractBreach
    loader.py           -- ContractLoader (YAML -> SchemaRegistry)
  api.py                -- FastAPI REST API
  ui.py                 -- Streamlit dashboard
contracts/
  raw_trades_v1.yaml
  enriched_ohlcv_v2.yaml
  risk_signals_v1.yaml
tests/
  conftest.py           -- Shared fixtures
  test_api.py           -- API endpoint tests (FastAPI TestClient)
  test_compatibility.py -- Compatibility logic tests
  test_loader.py        -- YAML loader tests
  test_registry.py      -- Schema registry tests
  test_validator.py     -- Consumer contract validator tests
```
