"""In-process, dict-backed schema registry.

The registry is intentionally storage-agnostic: it holds schemas in memory
and exposes a small, stable API that mirrors a subset of Confluent Schema
Registry's REST interface.  In production you would swap the ``_store``
dict for a database-backed implementation behind the same interface.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .compatibility import check_backward, check_forward, check_full
from .models import CompatibilityMode, CompatibilityResult, Schema

logger = logging.getLogger(__name__)


class SchemaRegistry:
    """In-process schema registry backed by a plain Python dict.

    Thread safety
    -------------
    Pass ``thread_safe=True`` to guard all mutations and reads with a
    ``threading.Lock``.  For ``asyncio`` callers, wrap calls with an
    ``asyncio.Lock`` externally instead.

    Usage
    -----
    >>> registry = SchemaRegistry()
    >>> schema = Schema(name="trades", version=1, fields=[...])
    >>> registry.register("trades", 1, schema)
    >>> registry.get_latest("trades")
    """

    def __init__(self, *, thread_safe: bool = False) -> None:
        # _store: subject_name -> {version: Schema}
        self._store: Dict[str, Dict[int, Schema]] = {}
        self._lock: Optional[threading.Lock] = threading.Lock() if thread_safe else None

    def _acquire(self):
        """Return the lock as a context manager, or a no-op."""
        if self._lock is not None:
            return self._lock
        return _NoOpLock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, name: str, version: int, schema: Schema) -> Schema:
        """Register a schema version under *name*.

        Parameters
        ----------
        name:
            Subject name (logical stream identifier).
        version:
            Must be a positive integer.  Duplicate ``(name, version)``
            pairs are rejected.
        schema:
            The ``Schema`` to persist.  ``registered_at`` is set to the
            current UTC wall-clock time if not already provided.

        Returns
        -------
        Schema
            The registered schema (with ``registered_at`` populated).

        Raises
        ------
        ValueError
            If *version* already exists for *name*, or if *version* <= 0.
        """
        if version <= 0:
            raise ValueError(f"Version must be a positive integer, got {version!r}.")

        with self._acquire():
            if name not in self._store:
                self._store[name] = {}

            if version in self._store[name]:
                raise ValueError(
                    f"Schema '{name}' version {version} is already registered. "
                    f"Increment the version number to register a new revision."
                )

            if schema.registered_at is None:
                schema.registered_at = datetime.now(tz=timezone.utc)

            self._store[name][version] = schema

        logger.info("Registered schema %s v%d (%d fields)", name, version, len(schema.fields))
        return schema

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, name: str, version: int) -> Schema:
        """Retrieve a specific schema version.

        Raises
        ------
        KeyError
            If *name* or *version* is not found.
        """
        with self._acquire():
            if name not in self._store:
                raise KeyError(f"No schemas registered under subject '{name}'.")
            if version not in self._store[name]:
                raise KeyError(
                    f"Schema '{name}' version {version} not found. "
                    f"Available versions: {sorted(self._store[name].keys())}"
                )
            return self._store[name][version]

    def get_latest(self, name: str) -> Schema:
        """Retrieve the schema with the highest version number for *name*.

        Raises
        ------
        KeyError
            If *name* has no registered schemas.
        """
        with self._acquire():
            if name not in self._store or not self._store[name]:
                raise KeyError(f"No schemas registered under subject '{name}'.")
            latest_version = max(self._store[name].keys())
            return self._store[name][latest_version]

    # ------------------------------------------------------------------
    # Enumeration
    # ------------------------------------------------------------------

    def list_versions(self, name: str) -> List[int]:
        """List all registered version numbers for *name*, sorted ascending.

        Returns an empty list (not an error) if *name* is unknown.
        """
        with self._acquire():
            if name not in self._store:
                return []
            return sorted(self._store[name].keys())

    def list_subjects(self) -> List[str]:
        """Return all subject names with at least one registered schema."""
        with self._acquire():
            return sorted(self._store.keys())

    # ------------------------------------------------------------------
    # Compatibility checking
    # ------------------------------------------------------------------

    def check_compatibility(
        self,
        name: str,
        new_schema: Schema,
        mode: CompatibilityMode,
    ) -> CompatibilityResult:
        """Check *new_schema* against the latest registered version for *name*.

        Parameters
        ----------
        name:
            Subject to check against.
        new_schema:
            The proposed next schema revision.
        mode:
            ``BACKWARD``, ``FORWARD``, or ``FULL``.

        Returns
        -------
        CompatibilityResult
            Contains ``compatible`` bool and a ``violations`` list.

        Raises
        ------
        KeyError
            If *name* has no registered schemas to compare against.

        Notes
        -----
        Compatibility is always evaluated against the **latest** version only
        (not the full history).  This matches Confluent Schema Registry's
        default ``BACKWARD`` transitive behaviour for a single-step check.
        For transitive checks across all versions, call this method
        iteratively for each version pair.
        """
        old_schema = self.get_latest(name)

        if mode is CompatibilityMode.BACKWARD:
            return check_backward(old_schema, new_schema)
        elif mode is CompatibilityMode.FORWARD:
            return check_forward(old_schema, new_schema)
        elif mode is CompatibilityMode.FULL:
            return check_full(old_schema, new_schema)
        else:  # pragma: no cover
            raise ValueError(f"Unknown compatibility mode: {mode!r}")


class _NoOpLock:
    """Context manager that does nothing — used when thread_safe=False."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
