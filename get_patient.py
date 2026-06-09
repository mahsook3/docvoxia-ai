"""
get_patient.py
---------------
Thin wrapper around Google Cloud Healthcare FHIR API for Patient resources.

Provides:
  - list_patients(): fetches Patient resources (optionally limited)
  - get_patient_by_id(): fetches a single Patient by id
"""

from typing import Any, Dict, List, Optional

from googleapiclient.errors import HttpError

try:
	from .fhir_client import FHIR_BASE, _get_client, _fhir
except ImportError:
	from fhir_client import FHIR_BASE, _get_client, _fhir


def _search_patients(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    client = _get_client()
    result = (
        _fhir(client)
        .search(parent=FHIR_BASE, resourceType="Patient", body=params)
        .execute()
    )
    return [e["resource"] for e in result.get("entry", [])]


def list_patients(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return a list of Patient resources. If limit is provided, uses `_count`."""
    params: Dict[str, Any] = {"resourceType": "Patient"}
    if limit is not None:
        params["_count"] = int(limit)
    return _search_patients(params)


def get_patient_by_id(patient_id: str) -> Optional[Dict[str, Any]]:
	"""Return a single Patient resource by id, or None if not found."""
	pid = (patient_id or "").strip()
	if not pid:
		raise ValueError("patient_id is required")

	client = _get_client()
	try:
		return (
			_fhir(client)
			.read(name=f"{FHIR_BASE}/fhir/Patient/{pid}")
			.execute()
		)
	except HttpError as exc:
		if getattr(exc, "resp", None) and getattr(exc.resp, "status", None) == 404:
			return None
		raise


def create_patient(patient_resource: Dict[str, Any]) -> Dict[str, Any]:
	"""Create a Patient resource in the configured FHIR store and return it."""
	if not isinstance(patient_resource, dict):
		raise ValueError("patient_resource must be an object")

	body = dict(patient_resource)
	resource_type = body.get("resourceType")
	if resource_type and resource_type != "Patient":
		raise ValueError("resourceType must be 'Patient'")
	body["resourceType"] = "Patient"

	# Let the server assign ids on create.
	body.pop("id", None)

	client = _get_client()
	created = (
		_fhir(client)
		.create(parent=FHIR_BASE, type="Patient", body=body)
		.execute()
	)
	return created
