# ADR-001: Consumer-driven contracts with an in-process schema registry

- **Status:** Accepted
- **Date:** 2026-05-19
- **Context layer:** governance

## Context

In a distributed data platform, a producer team changes a schema and silently
breaks downstream consumers who never agreed to the change. This is the data
equivalent of a REST API breaking a mobile client — except the break surfaces hours
later as a failed DAG or corrupt gold table, far from the cause. We need to fail the
change *at publish time*, not at consume time, and we need it to work before any
Kafka/Confluent infrastructure exists.

## Decision

Enforce **consumer-driven contracts** against an in-process schema registry.
Consumers pin to a specific schema version; before a producer publishes a new
version it is validated against every registered consumer's pinned version using
explicit BACKWARD / FORWARD / FULL compatibility rules. Breaches raise a structured
`ContractBreach` (`field_name`, `consumer_name`, `incompatibility_type`) ready for
alert routing.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Confluent Schema Registry from day one | Network hop + infra cost + Avro-only mental model; couples a governance *concept* to a vendor before the concept is proven. The dict-backed registry exposes the same `register/get_latest/check_compatibility` interface and is BQ/Firestore-backable later. |
| Producer-side schema versioning only | Versions a schema but never asks *who depends on it*. The break still ships. |
| JSON Schema validation at consume time | Detects the break after bad data is already written — too late, and cost is paid downstream. |

## Consequences

- **Positive:** Breaking changes are caught at the producer, with the exact
  consumer and field named. The interface (`check_compatibility`) is
  infrastructure-agnostic.
- **Negative / cost:** Consumers must *register and pin* — governance only works if
  the registry is the mandatory publish path. An unregistered consumer is invisible.
- **Risk accepted:** In-process registry has no durability/HA. Acceptable for a POC;
  production swaps the dict backend for BQ/Firestore behind the same interface.

## What changes at 100×

At 100s of producers/consumers, the registry must be a networked service of record
(Confluent SR or a BQ-backed service) with the compatibility engine unchanged behind
the same interface. The binding constraint shifts from *correctness* to *enforcement
coverage*: the registry must sit on the only sanctioned publish path (CI gate +
broker-level rejection), or teams route around it and governance silently erodes.
