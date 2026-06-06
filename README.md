# POC-11: Data Contract Enforcement with In-Process Schema Registry

**Wei Zhang | Data Engineering Portfolio**

---

## What This POC Demonstrates

This POC implements production-grade **consumer-driven contract testing** for data pipelines. The core problem it solves: in distributed data systems, a producer team silently breaks downstream consumers by changing a schema without realising who depends on it. This is the data equivalent of a REST API breaking a mobile client.

Three capabilities are demonstrated:

1. **In-process schema registry** — a dict-backed registry with `register`, `get`, `get_latest`, `list_versions`, and `check_compatibility`. No Kafka, no Confluent, no network hop. The same interface can be backed by BigQuery or Firestore in production.

2. **Compatibility mode enforcement** — three modes (BACKWARD, FORWARD, FULL) with precise violation semantics, mirroring Confluent Schema Registry's model.

3. **Consumer-driven contract validation** — consumers pin to a specific schema version. Before a producer publishes a new version, it validates against all registered consumers. Breaches surface as structured `ContractBreach` exceptions with `field_name`, `consumer_name`, and `incompatibility_type` attributes — ready for PagerDuty routing.

---

## Compatibility Modes

### BACKWARD

"A **new** reader can read data written by an **old** writer."

Old data records are fixed — they were written before the schema changed. The new schema must be able to deserialise them.

| Change | Safe? | Reason |
|---|---|---|
| Add nullable field | YES | Old records lack it; new reader uses NULL |
| Add field with default | YES | Old records lack it; new reader uses default |
| Add required field | **NO** | Old records won't have it — constraint violated |
| Remove any field | YES | New reader ignores fields it no longer knows |
| INTEGER → FLOAT | YES | Widening — no precision lost |
| FLOAT → INTEGER | **NO** | Old data may have fractional values |

### FORWARD

"An **old** reader can read data written by a **new** writer."

New data records are the ones being produced. The old reader (already deployed) must be able to handle them.

| Change | Safe? | Reason |
|---|---|---|
| Remove optional field | YES | Old reader can tolerate its absence |
| Remove required field | **NO** | Old reader expects it in every record |
| Add nullable field | YES | Old reader ignores unknown fields |
| Add required field | **NO** | Old reader doesn't know how to supply/validate it |
| INTEGER → FLOAT | YES | Old reader can widen |
| FLOAT → INTEGER | **NO** | Data truncation risk |

### FULL

Both BACKWARD and FORWARD must hold. The only truly unambiguous safe change under FULL is **adding a nullable (optional) field**. This is the strictest mode and is appropriate for long-lived, multi-consumer topics.

---

## How `DataContractValidator` Works

```python
from src.registry.schema_registry import SchemaRegistry
from src.registry.models import CompatibilityMode, FieldType, Schema, SchemaField
from src.contracts.validator import DataContractValidator, ContractBreach

# 1. Build and populate the registry.
registry = SchemaRegistry()
v1 = Schema(name="raw_trades", version=1, fields=[...])
registry.register("raw_trades", 1, v1)

# 2. Each consumer service declares its dependency at startup.
validator = DataContractValidator(registry)
validator.register_consumer("risk-engine", "raw_trades", pinned_version=1)
validator.register_consumer("ml-pipeline", "raw_trades", pinned_version=1)

# 3. Before the producer team ships v2, they call validate_producer_change.
proposed_v2 = Schema(name="raw_trades", version=2, fields=[...])
try:
    validator.validate_producer_change("raw_trades", proposed_v2, mode=CompatibilityMode.FORWARD)
except ContractBreach as breach:
    # breach.field_name      == "price"
    # breach.consumer_name   == "risk-engine"
    # breach.incompatibility_type == "required_field_removed"
    alert_pagerduty(breach.to_dict())
    raise
```

`validate_all()` is the non-raising variant — it collects results from all consumers and returns a `Dict[str, CompatibilityResult]`. Use it for CI gates and pre-flight dashboard reports.

---

## Running Tests

Install dependencies:

```bash
pip install -r requirements.txt
```

Run unit tests (no GCP credentials needed):

```bash
make test-unit
# equivalent: pytest tests/ -v -m "not integration"
```

Run with coverage:

```bash
make test-cov
```

Run lint + type check:

```bash
make lint
```

---

## Loading the Real Contracts

```python
from pathlib import Path
from src.registry.schema_registry import SchemaRegistry
from src.contracts.loader import ContractLoader

registry = SchemaRegistry()
loader = ContractLoader(Path("contracts"), registry)
count = loader.load_all()
print(f"Loaded {count} contracts")

raw_trades_v1 = registry.get("raw_trades", 1)
enriched_ohlcv_v2 = registry.get("enriched_ohlcv", 2)
risk_signals_v1 = registry.get("risk_signals", 1)
```

---

## sjarvis Data Model Contracts

Three contracts represent the sjarvis algorithmic trading system's core data streams:

### `raw_trades` v1

Raw trade execution events from the sjarvis order management system. All execution fields (`trade_id`, `symbol`, `side`, `quantity`, `price`, `currency`, `traded_at`, `_load_id`) are required and non-nullable. `strategy_id` is nullable to support manual desk trades that bypass the automated strategy layer.

Key constraint: `_load_id` provides idempotency for BigQuery MERGE operations — the ETL layer uses it to deduplicate replayed Pub/Sub messages.

### `enriched_ohlcv` v2

OHLCV bars post-enrichment with technical indicators. Published at version 2 because v1 lacked `vwap`, `rsi_14`, `ema_21`, and `regime`. All indicator fields are nullable because: (a) RSI requires 14 bars of history — the first 14 bars can't carry it; (b) VWAP is undefined for zero-volume bars in illiquid instruments.

The `regime` field (`TRENDING`, `RANGING`, `VOLATILE`) drives the regime gate in the sjarvis momentum strategies and is consumed by both the feature store and the risk engine.

### `risk_signals` v1

Per-position risk breach events emitted by the sjarvis risk engine. The `signal_type` enum (`DRAWDOWN_BREACH`, `CONCENTRATION_LIMIT`, `VAR_BREACH`, `STOP_LOSS`) and `severity` (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) fields are required to enable downstream automated responses. `acknowledged` (BOOLEAN, required) supports a two-phase alert flow: emit signal → risk desk ACKs → clear from dashboard.

---

## Terratest: Idempotency Test

The Go test in `terraform/tests/idempotency_test.go` proves that the Terraform module is **idempotent**: applying it twice produces no changes.

Terraform plan exit codes:
- `0` — no changes (expected on second plan)
- `2` — changes present (idempotency failure — the test fails)

Why this matters: non-idempotent Terraform modules silently overwrite live resources on every CI run, making it impossible to detect genuine infrastructure drift. This is a P0 requirement for production data platform infrastructure.

Run the idempotency test:

```bash
# Requires GOOGLE_APPLICATION_CREDENTIALS or gcloud ADC
make go-test-idempotency
```

Run the full BQ provisioning test:

```bash
make go-test-bq
```

Both tests call `terraform.Destroy` in a deferred statement, so infrastructure is always torn down even on test failure.

---

## Monitoring Dashboard

The dashboard JSON at `monitoring/dashboards/data_platform.json` defines a Cloud Monitoring mosaic layout with five tiles:

| Tile | Metric | Purpose |
|---|---|---|
| BQ Slot Utilisation | `bigquery.googleapis.com/slot/utilization` | Detect slot exhaustion in the poc11_contracts dataset |
| Pub/Sub Unacked Age | `pubsub.googleapis.com/subscription/oldest_unacked_message_age` | Alert on consumer lag for the contract violations subscription |
| Contract Violations Scorecard | `logging.googleapis.com/user/contract_violations` | Count of breaches in the last 24h (yellow >1, red >10) |
| BQ Upload Rate | `bigquery.googleapis.com/storage/uploaded_bytes_billed` | Throughput of audit log writes |
| Pub/Sub Undelivered Messages | `pubsub.googleapis.com/subscription/num_undelivered_messages` | Backlog depth for the violation topic |

Push the dashboard to a GCP project:

```bash
make dashboard-push
# equivalent: gcloud monitoring dashboards create \
#   --config-from-file=monitoring/dashboards/data_platform.json \
#   --project=ai-trading-prod
```

---

## Directory Structure

```
POC-11-Data-Contract-Registry/
├── src/
│   ├── registry/
│   │   ├── models.py           Schema, SchemaField, CompatibilityMode, CompatibilityResult
│   │   ├── compatibility.py    check_backward / check_forward / check_full
│   │   └── schema_registry.py  SchemaRegistry (dict-backed, in-process)
│   └── contracts/
│       ├── validator.py        DataContractValidator + ContractBreach
│       └── loader.py           ContractLoader (YAML -> SchemaRegistry)
├── contracts/
│   ├── raw_trades_v1.yaml
│   ├── enriched_ohlcv_v2.yaml
│   └── risk_signals_v1.yaml
├── tests/                      pytest test suite (60+ assertions)
├── terraform/                  BQ + Pub/Sub + SA + IAM
│   └── tests/                  Terratest (Go) idempotency + provisioning
├── monitoring/dashboards/      Cloud Monitoring JSON
├── Makefile
└── requirements.txt
```
