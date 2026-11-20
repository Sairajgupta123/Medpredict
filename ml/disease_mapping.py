"""Evidence-provenance checks for the disease/symptom mapping registry.

This module validates structure only. It does not determine whether a medical relationship is
true, clinically appropriate, licensed, or safe for patient-facing use.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_REGISTRY = Path(__file__).with_name("disease_mapping_registry.json")
REGISTRY_STATUSES = {"draft", "in_review", "approved", "rejected"}
RELATION_TYPES = {"associated_with", "may_include", "commonly_reported_with"}
REQUIRED_CONDITION_FIELDS = {"code", "label", "definition", "status"}
REQUIRED_MAPPING_FIELDS = {
    "mapping_id", "condition_code", "symptom_id", "relation_type",
    "evidence", "status", "reviewer_id", "reviewed_on",
}


def _is_https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme == "https" and bool(parsed.netloc)


def validate_registry(payload: dict[str, Any], known_symptom_ids: set[str]) -> dict[str, Any]:
    errors: list[str] = []
    conditions = payload.get("conditions")
    mappings = payload.get("mappings")
    if payload.get("registry_version") != 1:
        errors.append("unsupported_registry_version")
    if not isinstance(conditions, list):
        errors.append("conditions_must_be_a_list")
        conditions = []
    if not isinstance(mappings, list):
        errors.append("mappings_must_be_a_list")
        mappings = []

    condition_codes: set[str] = set()
    for index, condition in enumerate(conditions):
        if not isinstance(condition, dict):
            errors.append(f"condition_{index}_must_be_an_object")
            continue
        missing = REQUIRED_CONDITION_FIELDS - set(condition)
        if missing:
            errors.append(f"condition_{index}_missing_required_fields")
            continue
        code = condition.get("code")
        if not isinstance(code, str) or not code.strip():
            errors.append(f"condition_{index}_invalid_code")
        elif code in condition_codes:
            errors.append(f"duplicate_condition_code:{code}")
        else:
            condition_codes.add(code)
        if condition.get("status") not in REGISTRY_STATUSES:
            errors.append(f"condition_{index}_invalid_status")

    mapping_ids: set[str] = set()
    seen_pairs: set[tuple[str, str, str]] = set()
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            errors.append(f"mapping_{index}_must_be_an_object")
            continue
        if REQUIRED_MAPPING_FIELDS - set(mapping):
            errors.append(f"mapping_{index}_missing_required_fields")
            continue
        mapping_id = mapping.get("mapping_id")
        if not isinstance(mapping_id, str) or not mapping_id.strip():
            errors.append(f"mapping_{index}_invalid_id")
        elif mapping_id in mapping_ids:
            errors.append(f"duplicate_mapping_id:{mapping_id}")
        else:
            mapping_ids.add(mapping_id)

        code = mapping.get("condition_code")
        symptom_id = mapping.get("symptom_id")
        relation = mapping.get("relation_type")
        if code not in condition_codes:
            errors.append(f"mapping_{index}_unknown_condition_code")
        if symptom_id not in known_symptom_ids:
            errors.append(f"mapping_{index}_unknown_symptom_id")
        if relation not in RELATION_TYPES:
            errors.append(f"mapping_{index}_invalid_relation_type")
        pair = (str(code), str(symptom_id), str(relation))
        if pair in seen_pairs:
            errors.append(f"duplicate_condition_symptom_relation:{index}")
        seen_pairs.add(pair)
        if mapping.get("status") not in REGISTRY_STATUSES:
            errors.append(f"mapping_{index}_invalid_status")

        evidence = mapping.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"mapping_{index}_evidence_required")
        else:
            for item in evidence:
                if not isinstance(item, dict) or not _is_https_url(item.get("url")):
                    errors.append(f"mapping_{index}_evidence_must_have_https_url")
                    break
                if not isinstance(item.get("title"), str) or not item["title"].strip():
                    errors.append(f"mapping_{index}_evidence_title_required")
                    break
                if not isinstance(item.get("accessed_on"), str) or not item["accessed_on"].strip():
                    errors.append(f"mapping_{index}_evidence_access_date_required")
                    break

        if mapping.get("status") == "approved":
            if not isinstance(mapping.get("reviewer_id"), str) or not mapping["reviewer_id"].strip():
                errors.append(f"mapping_{index}_approved_requires_reviewer")
            if not isinstance(mapping.get("reviewed_on"), str) or not mapping["reviewed_on"].strip():
                errors.append(f"mapping_{index}_approved_requires_review_date")

    return {
        "registry_valid": not errors,
        "condition_count": len(conditions),
        "mapping_count": len(mappings),
        "approved_mapping_count": sum(
            isinstance(item, dict) and item.get("status") == "approved"
            for item in mappings
        ),
        "errors": errors,
        "automatic_clinical_approval": False,
        "patient_facing_use_permitted": False,
        "notice": (
            "Structural validation is not medical evidence review. No mapping is authorized "
            "for model training, recommendations, triage or patient-facing display by this tool."
        ),
    }


def audit_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    from ml.symptom_normalizer import load_taxonomy

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Registry root must be a JSON object")
    known_symptom_ids = {item.id for item in load_taxonomy()}
    return validate_registry(payload, known_symptom_ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_registry(args.registry)
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
