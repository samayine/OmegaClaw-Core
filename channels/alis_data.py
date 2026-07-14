"""
ALIS patient data tool for OmegaClaw standalone mode.

Three functions OmegaClaw can call:
  get_patient(patient_id)              — profile + current biomarkers + PC contributions + risks + events
  get_longitudinal(patient_id)         — biomarker and PC trends over time (separate from snapshot)
  list_patients()                      — summary list of all available patients

Required environment variables:
  ALIS_API_BASE_URL  — base URL of the ALIS API (e.g. https://api.alis.rejuve.bio)
  ALIS_API_TOKEN     — Bearer token for ALIS API authentication

NHANES codebook (data/nhanes_codebook.py) translates raw NHANES codes to human labels when the
ALIS API does not include a 'human' field in heatmap row responses.
"""

import os
import sys

try:
    import requests as _requests
    _requests_available = True
except ImportError:
    _requests_available = False

# Resolve repo root so data/ is importable regardless of working directory
_channels_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(_channels_dir)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from data.nhanes_codebook import NHANES_LABELS  # noqa: E402

_ALIS_BASE = os.environ.get("ALIS_API_BASE_URL", "").rstrip("/")
_ALIS_TOKEN = os.environ.get("ALIS_API_TOKEN", "")


def _api_get(path: str):
    """Call the ALIS REST API.

    Raises RuntimeError with a clear message if ALIS_API_BASE_URL is not set,
    so operators know exactly what to configure rather than getting a silent failure.
    """
    if not _ALIS_BASE:
        raise RuntimeError(
            "ALIS_API_BASE_URL is not configured.\n"
            "Set it in your environment or docker-compose.yml:\n"
            "  ALIS_API_BASE_URL=\n"
            "  ALIS_API_TOKEN= (if required)\n"
        )
    if not _requests_available:
        raise RuntimeError(
            "The 'requests' package is not installed.\n"
            "Add it to requirements.txt and rebuild the container."
        )
    url = f"{_ALIS_BASE}{path}"
    headers = {"Authorization": f"Bearer {_ALIS_TOKEN}"} if _ALIS_TOKEN else {}
    resp = _requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _pc_contributions_from_heatmap(heatmap_rows: list) -> dict:
    """Sum each PC's contributions across all biomarker rows from the real heatmap API response."""
    totals = {}
    for row in heatmap_rows:
        for i, val in enumerate(row.get("values", [])):
            pc = f"PC{i + 1}"
            totals[pc] = totals.get(pc, 0.0) + val
    return {pc: round(v, 3) for pc, v in totals.items() if v != 0.0}


def _format_patient_dict(p: dict) -> str:
    """Format a patient dict (parsed from real API) into a plain-text block for LLM consumption."""
    delta = p.get("delta", 0) or 0
    aging = "aging faster than normal" if float(delta) > 0 else "aging slower than normal"
    gender = p.get("gender", "").lower()
    pc_suffix = "M" if "male" in gender else "F" if "female" in gender else ""

    pc_lines = "\n".join(
        f"  {pc} (ChromaDB group: {pc}{pc_suffix}) — {val:+.3f} yrs ({'aging faster' if val > 0 else 'protective'})"
        for pc, val in sorted(p.get("pc_contributions", {}).items(), key=lambda x: abs(x[1]), reverse=True)
        if val != 0
    ) or "  No significant PC contributions recorded"

    bio_lines = "\n".join(
        f"  {k}: {v}" for k, v in p.get("biomarkers", {}).items() if v is not None
    ) or "  None"

    risk_lines = "\n".join(
        f"  {r['disease']} — evidence score: {r['evidence_score']:.2f} — PCs: {', '.join(f'{pc}{pc_suffix}' for pc in r.get('pcs', []))}"
        for r in sorted(p.get("risks", []), key=lambda x: x.get("evidence_score", 0), reverse=True)
    ) or "  None identified"

    event_lines = "\n".join(
        f"  {e.get('date', '')}: {e.get('event', e.get('label', ''))}"
        for e in sorted(p.get("events", []), key=lambda x: x.get("date", ""))
    ) or "  None recorded"

    return f"""=== Patient Profile ===
Name: {p.get('name', 'Unknown')} | Gender: {gender} | ID: {p.get('id', 'N/A')}
Chronological Age: {p.get('chron_age', 'N/A')} yrs | Biological Age: {p.get('bio_age', 'N/A')} yrs | Delta: {delta:+.2f} yrs | Status: {aging}
Clinician: {p.get('clinician', 'N/A')} | Notes: {p.get('notes') or 'None'}

=== PC Contributions (biological aging drivers) ===
Note: positive value = accelerating biological aging on that dimension.
{pc_lines}

=== Biomarkers ===
{bio_lines}

=== Disease Risks ===
Note: Evidence scores are raw magnitudes — higher = stronger evidence.
{risk_lines}

=== Life Events ===
{event_lines}"""


def _fetch_real_patient(patient_id: str) -> str:
    """Fetch patient data from the ALIS API and format it."""
    try:
        profile = _api_get(f"/patients/{patient_id}")
        risks_data = _api_get(f"/patients/{patient_id}/risks-interventions")
        events_data = _api_get(f"/patients/{patient_id}/events")
    except Exception as e:
        return f"Error fetching patient {patient_id}: {e}"

    # PC contributions — real API has heatmap rows; some endpoints may include pre-computed dict
    if "pc_contributions" in profile:
        pc_contributions = profile["pc_contributions"]
    else:
        heatmap_rows = profile.get("latest_heatmap", {}).get("rows", [])
        pc_contributions = _pc_contributions_from_heatmap(heatmap_rows)

    # Biomarkers — real API has heatmap rows; translate codes via NHANES_LABELS when 'human' absent
    if "biomarkers" in profile:
        biomarkers = profile["biomarkers"]
    else:
        heatmap_rows = profile.get("latest_heatmap", {}).get("rows", [])
        biomarkers = {
            row.get("human") or NHANES_LABELS.get(row["label"], row["label"]): row.get("value")
            for row in heatmap_rows
            if row.get("value") is not None
        }

    risks_list = risks_data if isinstance(risks_data, list) else risks_data.get("risks", [])
    risks = [
        {
            "disease": r.get("disease_name", r.get("disease", "Unknown")),
            "evidence_score": float(r.get("evidence_score", 0)),
            "pcs": r.get("contributing_pcs", r.get("pcs", [])),
        }
        for r in risks_list
    ]

    events_list = events_data if isinstance(events_data, list) else events_data.get("events", [])
    events = [
        {"date": e.get("date", ""), "event": e.get("label", e.get("event", ""))}
        for e in events_list
    ]

    first = profile.get("first_name", "")
    last = profile.get("last_name", "")
    p = {
        "id": patient_id,
        "name": f"{first} {last}".strip() or patient_id,
        "gender": profile.get("gender", ""),
        "chron_age": profile.get("latest_chron_age"),
        "bio_age": profile.get("latest_bio_age"),
        "delta": profile.get("latest_delta"),
        "clinician": (profile.get("clinician") or {}).get("name", "N/A"),
        "notes": profile.get("notes"),
        "pc_contributions": pc_contributions,
        "biomarkers": biomarkers,
        "risks": risks,
        "events": events,
    }
    return _format_patient_dict(p)


def _fetch_real_longitudinal(patient_id: str) -> str:
    """Fetch longitudinal data from the ALIS API and format it.
    Real API path: /patients/{id}/longitudinal
    """
    try:
        data = _api_get(f"/patients/{patient_id}/longitudinal")
    except Exception as e:
        return f"Error fetching longitudinal data for {patient_id}: {e}"

    lines = [f"=== Longitudinal Data: {patient_id} (ALIS API) ==="]

    interventions = data.get("interventions", [])
    if interventions:
        lines.append("\nKey interventions & life events (chronological):")
        for iv in sorted(interventions, key=lambda x: x.get("date", "")):
            lines.append(f"  {iv.get('date', '')}: {iv.get('event', iv.get('label', ''))}")

    biomarkers = data.get("biomarkers", {})
    if biomarkers:
        lines.append("\nBiomarker responses over time (note = clinical context at that visit):")
        for bm, readings in biomarkers.items():
            lines.append(f"\n  {bm}:")
            first_val = readings[0]["value"]
            last_val = readings[-1]["value"]
            direction = "increasing" if last_val > first_val else "decreasing" if last_val < first_val else "stable"
            for r in readings:
                note = f"  [{r['note']}]" if r.get("note") else ""
                lines.append(f"    {r['date']}: {r['value']}{note}")
            lines.append(f"    Overall trend: {direction} ({first_val} → {last_val})")

    pcs = data.get("pcs", {})
    if pcs:
        lines.append("\nPC aging score trends (positive = aging faster on that dimension):")
        for pc, readings in pcs.items():
            lines.append(f"\n  {pc}:")
            first_val = readings[0]["value"]
            last_val = readings[-1]["value"]
            direction = "worsening" if last_val > first_val else "improving" if last_val < first_val else "stable"
            for r in readings:
                note = f"  [{r['note']}]" if r.get("note") else ""
                lines.append(f"    {r['date']}: {r['value']:+.2f}{note}")
            lines.append(f"    Overall trend: {direction} ({first_val:+.2f} → {last_val:+.2f})")

    return "\n".join(lines)


def get_patient(patient_id: str) -> str:
    """Return formatted patient profile, biomarkers, PC contributions, risks, and life events."""
    return _fetch_real_patient(patient_id)


def list_patients() -> str:
    """Return a summary list of all patients available in the ALIS API."""
    try:
        data = _api_get("/patients")
        patients = data if isinstance(data, list) else data.get("patients", data.get("results", []))
        lines = ["Available patients (ALIS API):"]
        for p in patients:
            first = p.get("first_name", "")
            last = p.get("last_name", "")
            name = f"{first} {last}".strip() or p.get("id", "Unknown")
            delta = p.get("latest_delta", 0) or 0
            lines.append(
                f"  {p.get('id', '?')} — {name} | {p.get('gender', '?')} | "
                f"Age: {p.get('latest_chron_age', '?')} | BioAge: {p.get('latest_bio_age', '?')} | "
                f"Delta: {float(delta):+.2f}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing patients: {e}"


def get_longitudinal(patient_id: str) -> str:
    """Return longitudinal biomarker trends and intervention history for a patient.
    Call when asked about trends, changes over time, or treatment/exercise response.
    """
    return _fetch_real_longitudinal(patient_id)
