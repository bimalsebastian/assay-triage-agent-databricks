"""Synthetic openEHR composition data for the mock EHR.

Everything is fabricated. Patient references are opaque synthetic tokens
(no names, DOBs, or real identifiers of any kind). Each composition references
a synthetic drug_code — the identifier stage 09's crosswalk maps to a
preclinical compound_id.

The data is deliberately planted so the downstream clinical-correlation stages
have real, distinguishable cases:
  - DRG-0012  -> (crosswalks to CMPD00012, flagged preclinically for hERG):
                 carries adverse_reaction observations (cardiac arrhythmia /
                 QT prolongation) === a REAL correlated signal (stage 10 case A).
  - DRG-0004  -> (crosswalks to CMPD00004, flagged preclinically):
                 only benign lab_result observations, NO adverse reaction
                 === mapped but no clinical signal (stage 10 case B).
  - DRG-0777  -> ambiguous: stage 09 maps it to TWO compounds at low confidence.
  - flagged compounds with no drug_code at all (e.g. CMPD00024)
                 === no crosswalk mapping (stage 10 case C).

A real integration would model openEHR compositions in full (RM + archetypes +
templates); this synthetic set flattens to the fields the AQL query projects.
"""
from __future__ import annotations

from datetime import datetime, timedelta

# (patient_ref, drug_code, observation_type, value, day_offset, hour)
_BASE = datetime(2026, 6, 1, 9, 0, 0)


def _ts(day: int, hour: int) -> str:
    return (_BASE + timedelta(days=day, hours=hour)).strftime("%Y-%m-%dT%H:%M:%S")


# Each tuple: patient_ref, drug_code, observation_type, value, day, hour
_RECORDS = [
    # DRG-0012 — planted adverse-reaction signal (correlates with CMPD00012 hERG)
    ("synthetic-pt-0001", "DRG-0012", "adverse_reaction", "cardiac_arrhythmia", 3, 2),
    ("synthetic-pt-0001", "DRG-0012", "lab_result", "QTc 478 ms", 3, 3),
    ("synthetic-pt-0004", "DRG-0012", "adverse_reaction", "qt_prolongation", 9, 5),
    ("synthetic-pt-0004", "DRG-0012", "lab_result", "QTc 465 ms", 9, 6),
    ("synthetic-pt-0007", "DRG-0012", "lab_result", "potassium 4.1 mmol/L", 14, 1),
    # DRG-0004 — mapped but benign: only lab results, no adverse reaction
    ("synthetic-pt-0002", "DRG-0004", "lab_result", "ALT 34 U/L", 5, 4),
    ("synthetic-pt-0002", "DRG-0004", "lab_result", "AST 29 U/L", 5, 5),
    ("synthetic-pt-0005", "DRG-0004", "lab_result", "ALT 41 U/L", 11, 2),
    # DRG-0008 — mapped, benign labs only
    ("synthetic-pt-0003", "DRG-0008", "lab_result", "creatinine 0.9 mg/dL", 6, 3),
    ("synthetic-pt-0006", "DRG-0008", "lab_result", "eGFR 92 mL/min", 12, 7),
    # DRG-0001 — non-flagged compound, benign
    ("synthetic-pt-0003", "DRG-0001", "lab_result", "glucose 88 mg/dL", 7, 2),
    # DRG-0777 — ambiguous crosswalk target (stage 09), mild adverse note
    ("synthetic-pt-0008", "DRG-0777", "adverse_reaction", "mild_rash", 8, 4),
    ("synthetic-pt-0008", "DRG-0777", "lab_result", "eosinophils 6%", 8, 5),
]

# Column projection the AQL query returns (order matters for the resultset).
COLUMNS = ["patient_ref", "drug_code", "observation_type", "value", "effective_ts"]


def generate_rows() -> list[dict]:
    rows = []
    for pt, drug, otype, val, day, hour in _RECORDS:
        rows.append({
            "patient_ref": pt,
            "drug_code": drug,
            "observation_type": otype,
            "value": val,
            "effective_ts": _ts(day, hour),
        })
    rows.sort(key=lambda r: (r["patient_ref"], r["effective_ts"]))
    return rows


if __name__ == "__main__":
    import json
    rs = generate_rows()
    print(f"{len(rs)} composition rows across "
          f"{len({r['patient_ref'] for r in rs})} synthetic patients, "
          f"{len({r['drug_code'] for r in rs})} drug codes")
    print(json.dumps(rs[0], indent=2))
