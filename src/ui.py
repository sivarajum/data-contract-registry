"""Streamlit dashboard for the Data Contract Registry."""

import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path for local imports.
_root = str(Path(__file__).parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

import streamlit as st

logger = logging.getLogger(__name__)

from src.contracts.loader import ContractLoader
from src.contracts.validator import DataContractValidator
from src.registry.models import CompatibilityMode, FieldType
from src.registry.models import Schema as DomainSchema
from src.registry.models import SchemaField
from src.registry.schema_registry import SchemaRegistry

# ---------------------------------------------------------------------------
# Session-scoped registry
# ---------------------------------------------------------------------------


@st.cache_resource
def _init_registry() -> tuple[SchemaRegistry, DataContractValidator]:
    reg = SchemaRegistry(thread_safe=True)
    contracts_dir = Path(__file__).parent.parent / "contracts"
    if contracts_dir.is_dir():
        loader = ContractLoader(contracts_dir, reg)
        loader.load_all()
    val = DataContractValidator(reg)
    return reg, val


registry, validator = _init_registry()

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Data Contract Registry", page_icon="📋", layout="wide")
st.title("📋 Data Contract Registry")

# ---------------------------------------------------------------------------
# Sidebar: Navigation
# ---------------------------------------------------------------------------

page = st.sidebar.radio(
    "Navigation",
    ["Schemas", "Compatibility Check", "Consumer Contracts"],
)

# ---------------------------------------------------------------------------
# Schemas page
# ---------------------------------------------------------------------------

if page == "Schemas":
    st.header("Registered Schemas")

    subjects = registry.list_subjects()
    if not subjects:
        st.info("No schemas registered yet.")
    else:
        for subject in subjects:
            versions = registry.list_versions(subject)
            with st.expander(f"**{subject}** ({len(versions)} version(s))", expanded=True):
                for v in versions:
                    schema = registry.get(subject, v)
                    st.subheader(f"v{v}")
                    if schema.description:
                        st.caption(schema.description)
                    if schema.registered_at:
                        st.caption(f"Registered: {schema.registered_at.isoformat()}")

                    # Field table
                    rows = []
                    for f in schema.fields:
                        rows.append({
                            "Field": f.name,
                            "Type": f.field_type.value,
                            "Required": "Yes" if f.is_required() else "No",
                            "Nullable": "Yes" if f.nullable else "No",
                            "Default": str(f.default) if f.default is not None else "-",
                            "Description": f.description or "-",
                        })
                    st.dataframe(rows, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Compatibility Check page
# ---------------------------------------------------------------------------

elif page == "Compatibility Check":
    st.header("Check Schema Compatibility")

    subjects = registry.list_subjects()
    if not subjects:
        st.warning("No schemas registered. Load contracts first.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            subject = st.selectbox("Subject", subjects)
        with col2:
            mode = st.selectbox("Mode", ["BACKWARD", "FORWARD", "FULL"])

        st.subheader("Current Latest Schema")
        latest = registry.get_latest(subject)
        st.json({
            "name": latest.name,
            "version": latest.version,
            "fields": [{"name": f.name, "type": f.field_type.value, "nullable": f.nullable} for f in latest.fields],
        })

        st.subheader("Propose a Change")
        st.caption("Modify the fields below and click 'Check Compatibility'.")

        # Build editable field list from latest
        new_fields = []
        for i, f in enumerate(latest.fields):
            cols = st.columns([3, 2, 1, 1])
            name = cols[0].text_input("Name", value=f.name, key=f"fname_{i}")
            ftype = cols[1].selectbox(
                "Type", [ft.value for ft in FieldType],
                index=[ft.value for ft in FieldType].index(f.field_type.value),
                key=f"ftype_{i}",
            )
            nullable = cols[2].checkbox("Nullable", value=f.nullable, key=f"fnull_{i}")
            new_fields.append({"name": name, "type": ftype, "nullable": nullable})

        # Option to add a new field
        if st.checkbox("Add a new field"):
            cols = st.columns([3, 2, 1])
            new_name = cols[0].text_input("New field name", key="new_fname")
            new_type = cols[1].selectbox("New field type", [ft.value for ft in FieldType], key="new_ftype")
            new_nullable = cols[2].checkbox("Nullable", value=True, key="new_fnull")
            if new_name:
                new_fields.append({"name": new_name, "type": new_type, "nullable": new_nullable})

        if st.button("Check Compatibility", type="primary"):
            type_map = {ft.value: ft for ft in FieldType}
            proposed = DomainSchema(
                name=subject,
                version=latest.version + 1,
                fields=[
                    SchemaField(name=f["name"], field_type=type_map[f["type"]], nullable=f["nullable"])
                    for f in new_fields
                ],
            )
            result = registry.check_compatibility(subject, proposed, CompatibilityMode(mode))
            if result.compatible:
                st.success(f"Compatible under {mode} mode!")
            else:
                st.error(f"Incompatible under {mode} mode!")
                for v in result.violations:
                    st.warning(v)

# ---------------------------------------------------------------------------
# Consumer Contracts page
# ---------------------------------------------------------------------------

elif page == "Consumer Contracts":
    st.header("Consumer Contract Management")

    # Registration form
    st.subheader("Register a Consumer")
    subjects = registry.list_subjects()

    if not subjects:
        st.warning("No schemas registered.")
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            consumer_name = st.text_input("Consumer Name", placeholder="e.g. risk-engine")
        with col2:
            subject = st.selectbox("Subject", subjects, key="consumer_subject")
        with col3:
            versions = registry.list_versions(subject)
            pinned = st.selectbox("Pinned Version", versions, key="consumer_version")

        if st.button("Register Consumer"):
            if consumer_name:
                validator.register_consumer(consumer_name, subject, pinned)
                st.success(f"Registered '{consumer_name}' → {subject} v{pinned}")
            else:
                st.error("Consumer name is required.")

    # List registered consumers
    st.subheader("Registered Consumers")
    if not validator._consumer_contracts:
        st.info("No consumers registered yet.")
    else:
        rows = []
        for name, (subj, ver) in validator._consumer_contracts.items():
            rows.append({"Consumer": name, "Subject": subj, "Pinned Version": ver})
        st.dataframe(rows, use_container_width=True, hide_index=True)

    # Validate a proposed change
    st.subheader("Validate Producer Change")
    if subjects and validator._consumer_contracts:
        val_subject = st.selectbox("Subject to validate", subjects, key="val_subject")
        val_mode = st.selectbox("Mode", ["BACKWARD", "FORWARD", "FULL"], key="val_mode")

        if st.button("Run Validation Against All Consumers"):
            latest = registry.get_latest(val_subject)
            # Simulate a breaking change: add a required field
            test_schema = DomainSchema(
                name=val_subject,
                version=latest.version + 1,
                fields=list(latest.fields) + [
                    SchemaField(name="_test_required", field_type=FieldType.STRING, nullable=False),
                ],
            )
            results = validator.validate_all(val_subject, test_schema, CompatibilityMode(val_mode))
            if not results:
                st.info("No consumers registered for this subject.")
            else:
                for cname, result in results.items():
                    if result.compatible:
                        st.success(f"{cname}: Compatible")
                    else:
                        st.error(f"{cname}: BREACH")
                        for v in result.violations:
                            st.warning(v)
