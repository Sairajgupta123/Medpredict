"""Tests for the evidence-backed disease/symptom mapping registry."""
import json

from ml.disease_mapping import audit_registry, validate_registry

KNOWN = {"SYM_FEVER", "SYM_COUGH"}


def valid_payload():
    return {
        "registry_version": 1,
        "conditions": [
            {
                "code": "COND_EXAMPLE",
                "label": "Example condition",
                "definition": "Synthetic test fixture only",
                "status": "draft",
            }
        ],
        "mappings": [
            {
                "mapping_id": "MAP_TEST_001",
                "condition_code": "COND_EXAMPLE",
                "symptom_id": "SYM_FEVER",
                "relation_type": "associated_with",
                "evidence": [
                    {
                        "title": "Synthetic test evidence placeholder",
                        "url": "https://example.org/test-source",
                        "accessed_on": "2026-01-01",
                    }
                ],
                "status": "in_review",
                "reviewer_id": "",
                "reviewed_on": "",
            }
        ],
    }


def test_empty_registry_is_valid_but_approves_nothing():
    payload = {"registry_version": 1, "conditions": [], "mappings": []}
    result = validate_registry(payload, KNOWN)
    assert result["registry_valid"] is True
    assert result["mapping_count"] == 0
    assert result["automatic_clinical_approval"] is False
    assert result["patient_facing_use_permitted"] is False


def test_valid_draft_mapping_passes_structure_only():
    result = validate_registry(valid_payload(), KNOWN)
    assert result["registry_valid"] is True
    assert result["approved_mapping_count"] == 0
    assert result["patient_facing_use_permitted"] is False


def test_unknown_condition_and_symptom_are_rejected():
    payload = valid_payload()
    payload["mappings"][0]["condition_code"] = "UNKNOWN"
    payload["mappings"][0]["symptom_id"] = "SYM_NOT_IN_TAXONOMY"
    result = validate_registry(payload, KNOWN)
    assert "mapping_0_unknown_condition_code" in result["errors"]
    assert "mapping_0_unknown_symptom_id" in result["errors"]


def test_approved_mapping_requires_reviewer_and_date():
    payload = valid_payload()
    payload["mappings"][0]["status"] = "approved"
    result = validate_registry(payload, KNOWN)
    assert "mapping_0_approved_requires_reviewer" in result["errors"]
    assert "mapping_0_approved_requires_review_date" in result["errors"]
    assert result["patient_facing_use_permitted"] is False


def test_mapping_requires_source_provenance():
    payload = valid_payload()
    payload["mappings"][0]["evidence"] = []
    result = validate_registry(payload, KNOWN)
    assert "mapping_0_evidence_required" in result["errors"]


def test_duplicate_relationships_are_rejected():
    payload = valid_payload()
    duplicate = dict(payload["mappings"][0], mapping_id="MAP_TEST_002")
    payload["mappings"].append(duplicate)
    result = validate_registry(payload, KNOWN)
    assert "duplicate_condition_symptom_relation:1" in result["errors"]


def test_audit_reads_versioned_symptom_taxonomy(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps({"registry_version": 1, "conditions": [], "mappings": []}),
        encoding="utf-8",
    )
    result = audit_registry(path)
    assert result["registry_valid"] is True
    assert result["patient_facing_use_permitted"] is False
