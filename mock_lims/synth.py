"""Synthetic assay-reading generator for the mock LIMS service.

Everything here is fabricated. Compound identifiers are opaque codes
(CMPD#####), assay names are generic ADMET/safety panels, and there are no
real compound names, structures, or company references anywhere. The point is
only to produce a batch with enough spread that *some* readings will later trip
a toxicity threshold (e.g. a low hERG IC50) while most look benign.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta

# Deterministic: the API must serve a stable set across restarts so the
# connector's row counts are reproducible as execution evidence.
SEED = 20260914

# Generic ADMET / safety assays. `low_is_bad` marks assays where a *low* value
# is the safety signal (potency against an off-target you do NOT want to hit,
# e.g. hERG cardiac channel or a CYP enzyme). Stage 03 will compare against a
# tox reference; here we just make sure the spread produces some low outliers.
ASSAYS = [
    # name,               unit,  low_is_bad, typical_range
    ("hERG_IC50",         "uM",  True,  (0.2, 40.0)),   # cardiac safety
    ("CYP3A4_IC50",       "uM",  True,  (0.3, 50.0)),   # DDI risk
    ("CACO2_PAPP",        "1e-6cm/s", False, (0.5, 45.0)),  # permeability
    ("KINETIC_SOL",       "uM",  False, (2.0, 200.0)),  # solubility
    ("LOGD_7_4",          "",    False, (0.5, 5.5)),    # lipophilicity
]

ASSAY_PROTOCOLS = {
    "hERG_IC50": "PATCH-CLAMP-QPatch-v3",
    "CYP3A4_IC50": "LCMS-CYP-INH-v2",
    "CACO2_PAPP": "CACO2-BIDIR-v4",
    "KINETIC_SOL": "NEPHELOMETRY-SOL-v1",
    "LOGD_7_4": "SHAKE-FLASK-LOGD-v2",
}

N_COMPOUNDS = 24
READINGS_PER_COMPOUND_ASSAY = 2  # replicates


def _rng() -> random.Random:
    return random.Random(SEED)


def _batch_guid(seed_str: str) -> str:
    return hashlib.sha1(seed_str.encode()).hexdigest()[:32]


def _lims_timestamp(dt: datetime) -> str:
    # Deliberately non-ISO: yyyyMMdd HH:mm:ss.SSS — a managed connector would
    # choke on this; the custom connector has to parse it.
    return dt.strftime("%Y%m%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def _sample_id(compound_n: int, plate: int, well: str, replicate: int) -> str:
    # LIMS-flavored composite key. Compound ID is buried in here and needs a
    # regex split to extract — it is NOT a clean standalone field.
    return f"LO-CMPD{compound_n:05d}-P{plate}-{well}-R{replicate}"


def generate_records() -> list[dict]:
    """Return the full batch of raw, awkward LIMS records (vendor field names)."""
    rng = _rng()
    base_ts = datetime(2026, 9, 10, 8, 0, 0)
    records: list[dict] = []
    wells = [f"{r}{c:02d}" for r in "ABCDEFGH" for c in range(1, 13)]

    for cn in range(1, N_COMPOUNDS + 1):
        # Give a minority of compounds a genuinely concerning safety profile:
        # a low hERG / CYP IC50. ~1 in 4.
        risky = (cn % 4 == 0)
        plate = 1 + (cn % 6)
        for (name, unit, low_is_bad, (lo, hi)) in ASSAYS:
            for rep in range(1, READINGS_PER_COMPOUND_ASSAY + 1):
                well = rng.choice(wells)
                if low_is_bad and risky and name in ("hERG_IC50", "CYP3A4_IC50"):
                    # Push into the concerning low tail.
                    value = round(rng.uniform(lo, lo + (hi - lo) * 0.06), 3)
                else:
                    value = round(rng.uniform(lo, hi), 3)
                ts = base_ts + timedelta(
                    minutes=rng.randint(0, 60 * 72), seconds=rng.randint(0, 59),
                    milliseconds=rng.randint(0, 999),
                )
                sid = _sample_id(cn, plate, well, rep)
                records.append({
                    # vendor-specific, abbreviated field names on purpose
                    "smpl": sid,
                    "analyte": name,
                    "meas": {"val": f"{value}", "uom": unit},
                    "acqTs": _lims_timestamp(ts),
                    "proto": ASSAY_PROTOCOLS[name],
                    "operator": f"op-{rng.randint(1000, 1999)}",
                    "batchGuid": _batch_guid(sid + name),
                    "qcFlag": rng.choice(["PASS", "PASS", "PASS", "REVIEW"]),
                })
    # Stable ordering by sample then analyte so pagination is deterministic.
    records.sort(key=lambda r: (r["smpl"], r["analyte"]))
    return records


if __name__ == "__main__":
    recs = generate_records()
    print(f"generated {len(recs)} records across {N_COMPOUNDS} compounds")
    import json
    print(json.dumps(recs[0], indent=2))
