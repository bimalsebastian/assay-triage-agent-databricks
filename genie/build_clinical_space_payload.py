"""Build the create payload for the SEPARATE, tightly-scoped clinical Genie
space. Scoped to exactly ONE object: the aggregate/masked
lead_opt_demo.silver.clinical_correlation_summary view — no clinical catalog
tables, no patient-level data. Kept separate from the preclinical space by
design (a single unscoped room over both is the anti-pattern)."""
import json
import uuid

WAREHOUSE_ID = "13d08bfefc608fe6"
PARENT_PATH = "/Workspace/Users/bimal.sebastian@databricks.com/lead-opt"
VIEW = "lead_opt_demo.silver.clinical_correlation_summary"


def _id():
    return uuid.uuid4().hex


instructions = (
    "This space answers ONLY aggregate clinical-correlation questions about "
    "compounds, over a single masked view. It has no access to patient-level "
    "data, raw clinical observations, or the clinical catalog. correlation_state "
    "is one of: correlated (an adverse_reaction signal was found for the "
    "compound's crosswalked drug), checked_no_correlation (clinical data checked, "
    "no adverse signal), no_mapping (no clinical identifier mapping). Answer "
    "compound-level questions only; there is no patient data to expose."
)

example_sqls = sorted([
    {"id": _id(), "question": ["Which flagged compounds have a clinical correlation?"],
     "sql": [f"SELECT compound_id, signal_summary FROM {VIEW} WHERE correlation_state = 'correlated'"]},
    {"id": _id(), "question": ["How many compounds fall in each correlation state?"],
     "sql": [f"SELECT correlation_state, count(*) FROM {VIEW} GROUP BY correlation_state"]},
], key=lambda e: e["id"])

sample_qs = sorted(
    [{"id": _id(), "question": [q]} for q in [
        "Which flagged compounds have a clinical correlation?",
        "How many compounds have no clinical mapping?",
    ]], key=lambda e: e["id"])

serialized = {
    "version": 2,
    "config": {"sample_questions": sample_qs},
    "data_sources": {"tables": [{
        "identifier": VIEW,
        "column_configs": sorted([
            {"column_name": "compound_id", "enable_format_assistance": True, "enable_entity_matching": True},
            {"column_name": "correlation_state", "enable_format_assistance": True, "enable_entity_matching": True},
            {"column_name": "n_adverse_obs", "enable_format_assistance": True},
            {"column_name": "signal_summary", "enable_format_assistance": True},
        ], key=lambda c: c["column_name"]),
    }]},
    "instructions": {
        "text_instructions": [{"id": _id(), "content": [instructions]}],
        "example_question_sqls": example_sqls,
    },
}

payload = {
    "title": "Lead-Opt Clinical Correlation (scoped)",
    "description": "Aggregate-only clinical-correlation querying. No patient-level data — a deliberately scoped, separate room from the preclinical space.",
    "parent_path": PARENT_PATH,
    "warehouse_id": WAREHOUSE_ID,
    "serialized_space": json.dumps(serialized),
}
print(json.dumps(payload, indent=2))
