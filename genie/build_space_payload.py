"""Build the Genie space create payload, scoped to exactly the four silver
tables from stages 01-02. Prints the API request body JSON to stdout.

Scope is deliberately limited to lead_opt_demo.silver.* — nothing outside this
catalog. Instructions spell out the joins and the synthetic nature of the tox
reference so Genie resolves scientist questions to the right table/join.
"""
import json
import uuid

WAREHOUSE_ID = "13d08bfefc608fe6"
PARENT_PATH = "/Workspace/Users/bimal.sebastian@databricks.com/lead-opt"
CATALOG_SCHEMA = "lead_opt_demo.silver"


def _id() -> str:
    return uuid.uuid4().hex


def table(identifier, cols):
    # column_configs must be sorted by column_name (API requirement).
    return {"identifier": identifier,
            "column_configs": sorted(cols, key=lambda c: c["column_name"])}


def col(name, entity=False):
    c = {"column_name": name, "enable_format_assistance": True}
    if entity:
        c["enable_entity_matching"] = True
    return c


# Tables sorted by identifier (per skill guidance).
tables = [
    table(f"{CATALOG_SCHEMA}.assay_flags", [
        col("compound_id", entity=True), col("reading_id"), col("assay_name", entity=True),
        col("result_value"), col("result_unit"), col("is_flagged"), col("reason"),
        col("concern_direction"), col("threshold"), col("margin"),
        col("compound_prior_n"), col("compound_prior_mean"), col("evaluated_ts"),
    ]),
    table(f"{CATALOG_SCHEMA}.assay_results", [
        col("sample_id"), col("compound_id", entity=True), col("assay_name", entity=True),
        col("result_value"), col("result_unit"), col("acquired_ts"),
        col("plate"), col("well"), col("replicate"), col("qc_flag"),
    ]),
    table(f"{CATALOG_SCHEMA}.compound_registry", [
        col("compound_id", entity=True), col("structure_id_placeholder"),
        col("n_readings"), col("n_assays"), col("first_seen"), col("last_seen"),
    ]),
    table(f"{CATALOG_SCHEMA}.tox_reference", [
        col("assay_name", entity=True), col("concern_direction"),
        col("concern_threshold"), col("unit"), col("is_synthetic"), col("rationale"),
    ]),
]

instructions_text = (
    "This space covers a synthetic pharma lead-optimization assay dataset. "
    "assay_results holds one row per assay reading (compound_id, assay_name, "
    "result_value, result_unit, acquired_ts). compound_registry has one row per "
    "compound. tox_reference holds SYNTHETIC per-assay concern thresholds "
    "(concern_direction 'low' means a reading BELOW concern_threshold is a "
    "concern; 'high' means ABOVE). assay_flags has one row per reading with "
    "is_flagged and an explainable reason. "
    "Joins: assay_results.compound_id = compound_registry.compound_id; "
    "assay_results.assay_name = tox_reference.assay_name; "
    "assay_flags.reading_id = assay_results.sample_id. "
    "For 'currently flagged' questions use assay_flags WHERE is_flagged = true. "
    "All thresholds are synthetic demo data, not real toxicology values."
)

example_sqls = [
    {
        "id": _id(),
        "question": ["Which compounds are currently flagged?"],
        "sql": [
            "SELECT compound_id, assay_name, result_value, threshold, reason "
            f"FROM {CATALOG_SCHEMA}.assay_flags WHERE is_flagged = true "
            "ORDER BY margin ASC"
        ],
    },
    {
        "id": _id(),
        "question": ["What were the last three readings for CMPD00012?"],
        "sql": [
            "SELECT assay_name, result_value, result_unit, acquired_ts "
            f"FROM {CATALOG_SCHEMA}.assay_results WHERE compound_id = 'CMPD00012' "
            "ORDER BY acquired_ts DESC LIMIT 3"
        ],
    },
    {
        "id": _id(),
        "question": ["How does CMPD00012's hERG reading compare to the reference threshold?"],
        "sql": [
            "SELECT r.compound_id, r.assay_name, r.result_value, t.concern_threshold, "
            "t.concern_direction "
            f"FROM {CATALOG_SCHEMA}.assay_results r "
            f"JOIN {CATALOG_SCHEMA}.tox_reference t ON t.assay_name = r.assay_name "
            "WHERE r.compound_id = 'CMPD00012' AND r.assay_name = 'hERG_IC50'"
        ],
    },
]

sample_questions = [
    "Which compounds are currently flagged?",
    "What were the last three hERG readings for CMPD00012?",
    "How many compounds are in the registry?",
    "Which assay has the most flagged readings?",
]

# id-keyed lists must be sorted by id (API requirement).
sample_q_entries = sorted(
    [{"id": _id(), "question": [q]} for q in sample_questions], key=lambda e: e["id"]
)
example_sqls = sorted(example_sqls, key=lambda e: e["id"])

serialized_space = {
    "version": 2,
    "config": {"sample_questions": sample_q_entries},
    "data_sources": {"tables": tables},
    "instructions": {
        "text_instructions": [{"id": _id(), "content": [instructions_text]}],
        "example_question_sqls": example_sqls,
    },
}

payload = {
    "title": "Lead-Opt Assay Triage",
    "description": "Natural-language querying over the governed silver assay tables (synthetic lead-optimization demo).",
    "parent_path": PARENT_PATH,
    "warehouse_id": WAREHOUSE_ID,
    "serialized_space": json.dumps(serialized_space),
}

print(json.dumps(payload, indent=2))
