"""Entry point for the Data Contract Registry.

Usage:
    python main.py              # default: api mode
    python main.py api          # FastAPI server on port 8000
    python main.py ui           # Streamlit dashboard on port 8501
    python main.py all          # API + UI simultaneously
    python main.py validate     # Load contracts + run sample validation
"""

import logging
import subprocess
import sys
from pathlib import Path

from src.logging_config import setup_logging
from src import settings

setup_logging()

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent


def run_api(port: int | None = None) -> None:
    import uvicorn

    port = port or settings.API_PORT
    logger.info("Starting FastAPI server on http://%s:%d", settings.API_HOST, port)
    logger.info("Docs: http://localhost:%d/docs", port)
    uvicorn.run("src.api:app", host=settings.API_HOST, port=port, reload=True)


def run_ui() -> None:
    ui_path = PROJECT_ROOT / "src" / "ui.py"
    ui_port = str(settings.UI_PORT)
    logger.info("Starting Streamlit dashboard on http://localhost:%s", ui_port)
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(ui_path),
         "--server.port", ui_port, "--server.address", "0.0.0.0"],
        cwd=PROJECT_ROOT,
    )


def run_validate() -> None:
    """Load all contracts and run a sample validation."""
    from src.contracts.loader import ContractLoader
    from src.contracts.validator import ContractBreach, DataContractValidator
    from src.registry.models import CompatibilityMode, FieldType, Schema, SchemaField
    from src.registry.schema_registry import SchemaRegistry

    registry = SchemaRegistry()
    contracts_dir = PROJECT_ROOT / settings.CONTRACTS_DIR

    loader = ContractLoader(contracts_dir, registry)
    count = loader.load_all()
    logger.info("Loaded %d contract(s)", count)

    for subject in registry.list_subjects():
        versions = registry.list_versions(subject)
        schema = registry.get_latest(subject)
        logger.info("  %s: versions=%s, fields=%d", subject, versions, len(schema.fields))

    # Register sample consumers.
    validator = DataContractValidator(registry)
    validator.register_consumer("risk-engine", "raw_trades", pinned_version=1)
    validator.register_consumer("ml-feature-store", "enriched_ohlcv", pinned_version=2)
    validator.register_consumer("alert-dashboard", "risk_signals", pinned_version=1)
    logger.info("Registered %d consumer(s)", len(validator._consumer_contracts))

    # Validate a safe change (add nullable field).
    logger.info("--- Safe change: add nullable field to raw_trades ---")
    current = registry.get("raw_trades", 1)
    safe_v2 = Schema(
        name="raw_trades",
        version=2,
        fields=list(current.fields) + [
            SchemaField(name="exchange", field_type=FieldType.STRING, nullable=True),
        ],
    )
    results = validator.validate_all("raw_trades", safe_v2, CompatibilityMode.FORWARD)
    for name, r in results.items():
        logger.info("  %s: compatible=%s", name, r.compatible)

    # Validate a breaking change (remove required field).
    logger.info("--- Breaking change: remove required field from raw_trades ---")
    breaking_v2 = Schema(
        name="raw_trades",
        version=2,
        fields=[f for f in current.fields if f.name != "price"],
    )
    results = validator.validate_all("raw_trades", breaking_v2, CompatibilityMode.FORWARD)
    for name, r in results.items():
        status = "COMPATIBLE" if r.compatible else "BREACH"
        logger.info("  %s: %s", name, status)
        for v in r.violations:
            logger.info("    - %s", v)

    logger.info("Validation complete.")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "api"

    if mode == "api":
        run_api()
    elif mode == "ui":
        run_ui()
    elif mode == "all":
        api_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "src.api:app",
             "--host", settings.API_HOST, "--port", str(settings.API_PORT)],
            cwd=PROJECT_ROOT,
        )
        try:
            run_ui()
        finally:
            api_proc.terminate()
    elif mode == "validate":
        run_validate()
    else:
        logger.error("Unknown mode %r. Usage: python main.py [api|ui|all|validate]", mode)
        sys.exit(1)


if __name__ == "__main__":
    main()
