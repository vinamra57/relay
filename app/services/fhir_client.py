"""FHIR R4 client for querying public health information exchanges.

Queries public FHIR R4 servers (SMART on FHIR, HAPI FHIR) with Synthea synthetic
patient data to retrieve patient medical history: conditions, allergies, medications,
immunizations, and procedures.

In production, this would connect to Particle Health or a self-hosted FHIR server
with real HIE data. For development/testing, we use publicly available FHIR test
servers loaded with Synthea-generated patient data.
"""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

# Synthea FHIR R4 test server (synthetic patient data)
FHIR_SERVERS = [
    "https://launch.smarthealthit.org/v/r4/fhir",  # Synthea data
]

FHIR_HEADERS = {
    "Accept": "application/fhir+json",
}

FHIR_TIMEOUT = 45.0


def _extract_display(codeable_concept: dict) -> str:
    """Extract human-readable display text from a FHIR CodeableConcept."""
    if not codeable_concept:
        return "Unknown"
    codings = codeable_concept.get("coding", [])
    for coding in codings:
        if coding.get("display"):
            return coding["display"]
    return codeable_concept.get("text", "Unknown")


def _extract_entries(bundle: dict) -> list[dict]:
    """Extract resource entries from a FHIR Bundle."""
    if not bundle or bundle.get("resourceType") != "Bundle":
        return []
    return [e["resource"] for e in bundle.get("entry", []) if "resource" in e]


def _split_name(full_name: str) -> tuple[str | None, str | None]:
    """Split a full name into (given_name, family_name) for FHIR search.

    Convention: last token is family name, preceding tokens are given names.
    Returns (None, None) if name is empty.
    """
    parts = full_name.strip().split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return None, parts[0]
    return " ".join(parts[:-1]), parts[-1]


async def search_patient(
    client: httpx.AsyncClient,
    base_url: str,
    given: str | None = None,
    family: str | None = None,
    birthdate: str | None = None,
    gender: str | None = None,
) -> list[dict]:
    """Search for a patient by demographics on a FHIR R4 server.

    Tries progressively broader search strategies until a match is found:
    1. family + given + gender + birthdate (most specific)
    2. family + given + gender
    3. family + given
    4. family + gender
    5. family only (broadest)

    Args:
        client: httpx async client instance
        base_url: FHIR server base URL
        given: Patient given/first name(s)
        family: Patient family/last name
        birthdate: Date of birth in YYYY-MM-DD format
        gender: male, female, other, unknown

    Returns:
        List of matching Patient resources
    """
    if not family:
        return []

    gender_lower = gender.lower() if gender else None

    strategies: list[tuple[str, dict[str, str]]] = []

    if given and gender_lower and birthdate:
        strategies.append(("family+given+gender+birthdate", {
            "family": family, "given": given,
            "gender": gender_lower, "birthdate": birthdate,
        }))
    if given and gender_lower:
        strategies.append(("family+given+gender", {
            "family": family, "given": given, "gender": gender_lower,
        }))
    if given:
        strategies.append(("family+given", {
            "family": family, "given": given,
        }))
    if gender_lower:
        strategies.append(("family+gender", {
            "family": family, "gender": gender_lower,
        }))
    strategies.append(("family", {"family": family}))

    for strategy_name, params in strategies:
        params["_count"] = "5"
        resp = await client.get(
            f"{base_url}/Patient",
            params=params,
            headers=FHIR_HEADERS,
        )
        resp.raise_for_status()
        patients = _extract_entries(resp.json())
        if patients:
            logger.info(
                "Patient search hit on %s using strategy %s (%d results)",
                base_url, strategy_name, len(patients),
            )
            return patients

    return []


async def get_conditions(
    client: httpx.AsyncClient,
    base_url: str,
    patient_id: str,
) -> list[dict]:
    """Fetch all Condition resources for a patient (medical history)."""
    resp = await client.get(
        f"{base_url}/Condition",
        params={"patient": patient_id, "_count": "100"},
        headers=FHIR_HEADERS,
    )
    resp.raise_for_status()
    return _extract_entries(resp.json())


async def get_allergies(
    client: httpx.AsyncClient,
    base_url: str,
    patient_id: str,
) -> list[dict]:
    """Fetch all AllergyIntolerance resources for a patient."""
    resp = await client.get(
        f"{base_url}/AllergyIntolerance",
        params={"patient": patient_id, "_count": "100"},
        headers=FHIR_HEADERS,
    )
    resp.raise_for_status()
    return _extract_entries(resp.json())


async def get_medications(
    client: httpx.AsyncClient,
    base_url: str,
    patient_id: str,
) -> list[dict]:
    """Fetch all MedicationRequest resources for a patient."""
    resp = await client.get(
        f"{base_url}/MedicationRequest",
        params={"patient": patient_id, "_count": "100"},
        headers=FHIR_HEADERS,
    )
    resp.raise_for_status()
    return _extract_entries(resp.json())


async def get_immunizations(
    client: httpx.AsyncClient,
    base_url: str,
    patient_id: str,
) -> list[dict]:
    """Fetch all Immunization resources for a patient."""
    resp = await client.get(
        f"{base_url}/Immunization",
        params={"patient": patient_id, "_count": "100"},
        headers=FHIR_HEADERS,
    )
    resp.raise_for_status()
    return _extract_entries(resp.json())


async def get_procedures(
    client: httpx.AsyncClient,
    base_url: str,
    patient_id: str,
) -> list[dict]:
    """Fetch all Procedure resources for a patient."""
    resp = await client.get(
        f"{base_url}/Procedure",
        params={"patient": patient_id, "_count": "100"},
        headers=FHIR_HEADERS,
    )
    resp.raise_for_status()
    return _extract_entries(resp.json())


async def fetch_patient_record(
    patient_id: str,
    base_url: str,
) -> dict:
    """Fetch all clinical resources for a patient concurrently.

    Makes parallel requests for conditions, allergies, medications,
    immunizations, and procedures using asyncio.gather.

    Args:
        patient_id: FHIR Patient resource ID
        base_url: FHIR server base URL

    Returns:
        Dict with keys: conditions, allergies, medications, immunizations, procedures.
        Each value is a list of FHIR resources or {"error": str} on failure.
    """
    async with httpx.AsyncClient(timeout=FHIR_TIMEOUT) as client:
        fetchers = {
            "conditions": get_conditions(client, base_url, patient_id),
            "allergies": get_allergies(client, base_url, patient_id),
            "medications": get_medications(client, base_url, patient_id),
            "immunizations": get_immunizations(client, base_url, patient_id),
            "procedures": get_procedures(client, base_url, patient_id),
        }
        keys = list(fetchers.keys())
        results_list = await asyncio.gather(*fetchers.values(), return_exceptions=True)

    result: dict[str, list[dict] | dict] = {}
    for key, value in zip(keys, results_list, strict=True):
        if isinstance(value, BaseException):
            logger.warning("Failed to fetch %s for patient %s: %s", key, patient_id, value)
            result[key] = {"error": str(value)}
        else:
            result[key] = list(value)
    return result


def parse_conditions(conditions: list[dict]) -> list[str]:
    """Parse Condition resources into human-readable condition names."""
    results = []
    for cond in conditions:
        if isinstance(cond, dict) and cond.get("resourceType") == "Condition":
            display = _extract_display(cond.get("code", {}))
            status = ""
            clinical = cond.get("clinicalStatus", {})
            if clinical:
                status_codings = clinical.get("coding", [])
                for c in status_codings:
                    if c.get("code"):
                        status = c["code"]
                        break
            if display != "Unknown":
                label = display
                if status and status != "active":
                    label += f" ({status})"
                if label not in results:
                    results.append(label)
    return results


def parse_allergies(allergies: list[dict]) -> list[str]:
    """Parse AllergyIntolerance resources into human-readable allergy names."""
    results = []
    for allergy in allergies:
        if isinstance(allergy, dict) and allergy.get("resourceType") == "AllergyIntolerance":
            display = _extract_display(allergy.get("code", {}))
            criticality = allergy.get("criticality", "")
            if display != "Unknown":
                label = display
                if criticality and criticality != "low":
                    label += f" [{criticality}]"
                if label not in results:
                    results.append(label)
    return results


def parse_medications(medications: list[dict]) -> list[str]:
    """Parse MedicationRequest resources into human-readable medication names."""
    results = []
    for med in medications:
        if isinstance(med, dict) and med.get("resourceType") == "MedicationRequest":
            display = _extract_display(med.get("medicationCodeableConcept", {}))
            status = med.get("status", "")
            if display != "Unknown":
                label = display
                if status and status != "active":
                    label += f" ({status})"
                if label not in results:
                    results.append(label)
    return results


def parse_immunizations(immunizations: list[dict]) -> list[str]:
    """Parse Immunization resources into human-readable vaccine names."""
    results = []
    for imm in immunizations:
        if isinstance(imm, dict) and imm.get("resourceType") == "Immunization":
            display = _extract_display(imm.get("vaccineCode", {}))
            date = imm.get("occurrenceDateTime", "")
            if display != "Unknown":
                label = display
                if date:
                    label += f" ({date[:10]})"
                if label not in results:
                    results.append(label)
    return results


def parse_procedures_list(procedures: list[dict]) -> list[str]:
    """Parse Procedure resources into human-readable procedure names."""
    results = []
    for proc in procedures:
        if isinstance(proc, dict) and proc.get("resourceType") == "Procedure":
            display = _extract_display(proc.get("code", {}))
            date = proc.get("performedDateTime", proc.get("performedPeriod", {}).get("start", ""))
            if display != "Unknown":
                label = display
                if date:
                    label += f" ({date[:10]})"
                if label not in results:
                    results.append(label)
    return results


async def query_fhir_servers(
    patient_name: str,
    patient_gender: str | None = None,
    patient_dob: str | None = None,
) -> dict | None:
    """Query FHIR servers to find a patient and retrieve their full medical record.

    Tries each configured FHIR server in order until a matching patient is found.
    Uses cascading search strategies per server (most specific to broadest).

    Args:
        patient_name: Patient name for search
        patient_gender: Patient gender (male/female)
        patient_dob: Date of birth in YYYY-MM-DD format

    Returns:
        Dict with parsed medical record, or None if no match found.
    """
    given, family = _split_name(patient_name)

    for base_url in FHIR_SERVERS:
        try:
            async with httpx.AsyncClient(timeout=FHIR_TIMEOUT) as client:
                patients = await search_patient(
                    client, base_url,
                    given=given,
                    family=family,
                    birthdate=patient_dob,
                    gender=patient_gender,
                )

            if not patients:
                logger.info(
                    "No patient match on %s for %s", base_url, patient_name
                )
                continue

            # Use the first (best) match
            patient = patients[0]
            patient_id = patient.get("id")
            if not patient_id:
                continue

            logger.info(
                "Found patient %s on %s (FHIR ID: %s)",
                patient_name, base_url, patient_id,
            )

            # Fetch all clinical data concurrently
            record = await fetch_patient_record(patient_id, base_url)

            # Parse into human-readable format
            conditions_raw = record.get("conditions", [])
            allergies_raw = record.get("allergies", [])
            medications_raw = record.get("medications", [])
            immunizations_raw = record.get("immunizations", [])
            procedures_raw = record.get("procedures", [])

            return {
                "source": base_url,
                "fhir_patient_id": patient_id,
                "patient_name": _get_patient_name(patient),
                "patient_dob": patient.get("birthDate"),
                "patient_gender": patient.get("gender"),
                "conditions": (
                    parse_conditions(conditions_raw)
                    if isinstance(conditions_raw, list) else []
                ),
                "allergies": (
                    parse_allergies(allergies_raw)
                    if isinstance(allergies_raw, list) else []
                ),
                "medications": (
                    parse_medications(medications_raw)
                    if isinstance(medications_raw, list) else []
                ),
                "immunizations": (
                    parse_immunizations(immunizations_raw)
                    if isinstance(immunizations_raw, list) else []
                ),
                "procedures": (
                    parse_procedures_list(procedures_raw)
                    if isinstance(procedures_raw, list) else []
                ),
            }

        except httpx.HTTPStatusError as e:
            logger.warning("FHIR server %s returned HTTP %s: %s", base_url, e.response.status_code, e)
        except httpx.TimeoutException:
            logger.warning("FHIR server %s timed out", base_url)
        except Exception as e:
            logger.warning("FHIR query to %s failed: %s", base_url, e)

    return None


def _get_patient_name(patient: dict) -> str:
    """Extract human-readable name from a FHIR Patient resource."""
    names = patient.get("name", [])
    if not names:
        return "Unknown"
    name = names[0]
    given = " ".join(name.get("given", []))
    family = name.get("family", "")
    return f"{given} {family}".strip() or name.get("text", "Unknown")
