# Data Contract Registry

Schema registry with consumer-driven contract testing — YAML-based contracts, compatibility checking, FastAPI API + Streamlit dashboard.

## What It Does

- **Schema Registry**: Store and version data contracts as YAML schemas
- **Contract Validation**: Validate data payloads against registered schemas (JSON Schema)
- **Compatibility Checking**: Backward/forward/full compatibility analysis between schema versions
- **Consumer-Driven Testing**: Consumers pin to schema versions; producers validate changes against all consumers before publishing
- **REST API**: 10 FastAPI endpoints for contract CRUD, validation, and compatibility
- **Dashboard**: Streamlit UI for browsing contracts and running validations

## Compatibility Modes

| Mode | Rule |
|------|------|
| **BACKWARD** | New reader can read old data (add nullable/default OK, add required NOT OK) |
| **FORWARD** | Old reader can read new data (remove optional OK, remove required NOT OK) |
| **FULL** | Both backward and forward must hold (only adding nullable fields is safe) |

## Architecture

```
contracts/*.yaml              # Contract definitions (YAML)
src/contracts/loader.py       # YAML loading + parsing
src/contracts/validator.py    # JSON Schema validation + ContractBreach exceptions
src/registry/schema_registry.py  # Version management
src/registry/compatibility.py    # Schema compatibility engine
src/api.py                    # FastAPI REST API (10 endpoints)
src/ui.py                     # Streamlit dashboard
```

## Quick Start

```bash
pip install -r requirements.txt
python main.py api          # API on :8000
python main.py ui           # Dashboard on :8501
python main.py all          # Both
```

## Testing

```bash
pytest                      # 136 tests, 97% coverage
pytest --cov=src --cov-report=term-missing
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/contracts` | List all contracts |
| GET | `/contracts/{name}` | Get contract by name |
| POST | `/contracts` | Register new contract |
| GET | `/schemas` | List all schemas |
| GET | `/schemas/{name}/latest` | Latest schema version |
| GET | `/schemas/{name}/{version}` | Specific schema version |
| POST | `/validate` | Validate data against schema |
| POST | `/compatibility` | Check schema compatibility |
| GET | `/stats` | Registry statistics |

## Docker

```bash
docker compose up --build
```

See [RUNNING.md](RUNNING.md) for full build, test, and deployment instructions.
