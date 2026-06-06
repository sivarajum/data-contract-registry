"""Consumer-driven contract validation.

The key insight of consumer-driven contract testing is that the *consumer*
declares what it needs from a schema, and the *producer* must honour every
consumer's expectations before publishing a new schema version.  This
inverts the traditional "producer owns the schema" model and surfaces
breaking changes before they reach production.

Workflow
--------
1. Each downstream consumer calls ``register_consumer`` once at startup,
   pinning itself to the schema version it was built against.
2. Before the producer registers a new schema version, it calls
   ``validate_producer_change``.  If any consumer would be broken,
   a ``ContractBreach`` exception is raised with full context.
3. Incident triage uses ``ContractBreach.to_dict()`` to route structured
   alerts to PagerDuty / Cloud Logging.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from src.registry.compatibility import check_backward, check_forward, check_full
from src.registry.models import CompatibilityMode, CompatibilityResult, Schema
from src.registry.schema_registry import SchemaRegistry

logger = logging.getLogger(__name__)


class ContractBreach(Exception):
    """Raised when a proposed schema change breaks a registered consumer contract.

    Attributes
    ----------
    field_name:
        The field that caused the breach.  May be ``"<multiple>"`` if more
        than one field is implicated — callers should inspect ``violations``
        on the ``CompatibilityResult`` for the full list.
    consumer_name:
        Identifier of the consumer whose contract was violated.
    incompatibility_type:
        A machine-readable string categorising the breach.
        Standard values: ``"required_field_added"``, ``"required_field_removed"``,
        ``"type_narrowed"``, ``"multiple_violations"``.
    producer_schema_version:
        The version number of the proposed (new) producer schema.
    consumer_schema_version:
        The version number the consumer is currently pinned to.
    message:
        Human-readable description.  Auto-generated if not supplied.
    """

    def __init__(
        self,
        field_name: str,
        consumer_name: str,
        incompatibility_type: str,
        producer_schema_version: int,
        consumer_schema_version: int,
        message: str = "",
    ) -> None:
        self.field_name = field_name
        self.consumer_name = consumer_name
        self.incompatibility_type = incompatibility_type
        self.producer_schema_version = producer_schema_version
        self.consumer_schema_version = consumer_schema_version
        self.message = message or (
            f"Contract breach: field '{field_name}' — {incompatibility_type} "
            f"(consumer: {consumer_name})"
        )
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """Return a structured dict suitable for structured logging or alerting.

        Example
        -------
        >>> breach.to_dict()
        {
            "field_name": "price",
            "consumer_name": "risk-engine",
            "incompatibility_type": "type_narrowed",
            "producer_schema_version": 3,
            "consumer_schema_version": 2,
            "message": "Contract breach: field 'price' — type_narrowed (consumer: risk-engine)"
        }
        """
        return {
            "field_name": self.field_name,
            "consumer_name": self.consumer_name,
            "incompatibility_type": self.incompatibility_type,
            "producer_schema_version": self.producer_schema_version,
            "consumer_schema_version": self.consumer_schema_version,
            "message": self.message,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_check(
    old_schema: Schema,
    new_schema: Schema,
    mode: CompatibilityMode,
) -> CompatibilityResult:
    """Dispatch to the appropriate compatibility checker."""
    if mode is CompatibilityMode.BACKWARD:
        return check_backward(old_schema, new_schema)
    elif mode is CompatibilityMode.FORWARD:
        return check_forward(old_schema, new_schema)
    else:
        return check_full(old_schema, new_schema)


def _extract_breach_field(violations: List[str]) -> Tuple[str, str]:
    """Best-effort extraction of the first violated field name and type.

    Returns ``(field_name, incompatibility_type)``.
    Falls back to ``("<multiple>", "multiple_violations")`` for > 1 violation.
    """
    if len(violations) > 1:
        return "<multiple>", "multiple_violations"

    violation = violations[0]

    # Determine incompatibility type from the violation text.
    if "required" in violation and "added" in violation:
        itype = "required_field_added"
    elif "required" in violation and "removed" in violation:
        itype = "required_field_removed"
    elif "narrowing" in violation or "type changed" in violation:
        itype = "type_narrowed"
    else:
        itype = "incompatible_change"

    # Extract the field name from the single-quote delimited token.
    try:
        field_name = violation.split("'")[1]
    except IndexError:
        field_name = "<unknown>"

    return field_name, itype


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class DataContractValidator:
    """Validates that a producer schema change does not break any consumer contracts.

    Consumer-driven contract testing places the specification burden on
    consumers: each consumer declares which schema version it depends on,
    and the registry enforces that any new producer version remains
    compatible with every pinned consumer.

    Parameters
    ----------
    registry:
        A populated ``SchemaRegistry`` instance.

    Example
    -------
    >>> validator = DataContractValidator(registry)
    >>> validator.register_consumer("risk-engine", "raw_trades", pinned_version=1)
    >>> validator.validate_producer_change("raw_trades", proposed_v2, mode=CompatibilityMode.FORWARD)
    """

    def __init__(self, registry: SchemaRegistry) -> None:
        self.registry = registry
        # Maps consumer_name -> (subject_name, pinned_version)
        self._consumer_contracts: Dict[str, Tuple[str, int]] = {}

    # ------------------------------------------------------------------
    # Consumer registration
    # ------------------------------------------------------------------

    def register_consumer(
        self,
        consumer_name: str,
        subject_name: str,
        pinned_version: int,
    ) -> None:
        """Register a consumer's schema dependency.

        Parameters
        ----------
        consumer_name:
            A stable identifier for the downstream consumer service or
            pipeline stage (e.g. ``"risk-engine"``, ``"ml-feature-store"``).
        subject_name:
            The schema subject this consumer depends on.
        pinned_version:
            The specific version the consumer was built and tested against.

        Notes
        -----
        Re-registering the same *consumer_name* with a different
        *subject_name* or *pinned_version* overwrites the previous
        registration silently.  This reflects a consumer upgrading its
        pinned version.
        """
        self._consumer_contracts[consumer_name] = (subject_name, pinned_version)
        logger.info(
            "Registered consumer %r → %s v%d",
            consumer_name, subject_name, pinned_version,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_producer_change(
        self,
        subject_name: str,
        new_schema: Schema,
        mode: CompatibilityMode = CompatibilityMode.FORWARD,
    ) -> List[CompatibilityResult]:
        """Validate *new_schema* against every consumer pinned to *subject_name*.

        Iterates through all registered consumers that have pinned a version
        of *subject_name*.  For each such consumer, retrieves the pinned
        schema from the registry and runs the specified compatibility check.

        Parameters
        ----------
        subject_name:
            The schema subject being changed by the producer.
        new_schema:
            The proposed next schema revision.
        mode:
            Compatibility mode to enforce.  Defaults to ``FORWARD`` because
            producers writing new data should ensure old consumers can still
            read it.

        Returns
        -------
        List[CompatibilityResult]
            One result per consumer that was checked (all passing).

        Raises
        ------
        ContractBreach
            On the **first** consumer violation found.  Use ``validate_all``
            to collect violations from all consumers without early exit.
        """
        results: List[CompatibilityResult] = []

        for consumer_name, (subj, pinned_version) in self._consumer_contracts.items():
            if subj != subject_name:
                continue  # This consumer doesn't depend on the subject being changed.

            old_schema = self.registry.get(subj, pinned_version)
            result = _run_check(old_schema, new_schema, mode)

            if not result.compatible:
                field_name, itype = _extract_breach_field(result.violations)
                logger.warning(
                    "Contract breach detected: consumer=%r subject=%s "
                    "field=%s type=%s producer_v=%d consumer_v=%d",
                    consumer_name, subject_name, field_name, itype,
                    new_schema.version, pinned_version,
                )
                raise ContractBreach(
                    field_name=field_name,
                    consumer_name=consumer_name,
                    incompatibility_type=itype,
                    producer_schema_version=new_schema.version,
                    consumer_schema_version=pinned_version,
                )

            results.append(result)

        logger.info(
            "Validated %d consumer(s) for %s v%d — all compatible",
            len(results), subject_name, new_schema.version,
        )
        return results

    def validate_all(
        self,
        subject_name: str,
        new_schema: Schema,
        mode: CompatibilityMode = CompatibilityMode.FORWARD,
    ) -> Dict[str, CompatibilityResult]:
        """Validate *new_schema* against all consumers and collect ALL violations.

        Unlike ``validate_producer_change``, this method does **not** raise on
        the first violation.  It evaluates every consumer and returns a
        comprehensive report — useful for pre-flight checks, CI gates, and
        bulk reporting dashboards.

        Parameters
        ----------
        subject_name:
            The schema subject being changed by the producer.
        new_schema:
            The proposed next schema revision.
        mode:
            Compatibility mode to enforce.

        Returns
        -------
        Dict[str, CompatibilityResult]
            Maps ``consumer_name`` → ``CompatibilityResult``.
            Entries where ``result.compatible is False`` indicate breaches.
        """
        results: Dict[str, CompatibilityResult] = {}

        for consumer_name, (subj, pinned_version) in self._consumer_contracts.items():
            if subj != subject_name:
                continue

            old_schema = self.registry.get(subj, pinned_version)
            result = _run_check(old_schema, new_schema, mode)
            results[consumer_name] = result

        return results
