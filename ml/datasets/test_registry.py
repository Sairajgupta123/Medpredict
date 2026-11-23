"""Tests for dataset provenance registry validation."""
import json

import pytest

from ml.datasets.registry import audit_registry, validate_dataset_record


def valid_record():
    return {
        "dataset_id": "example-image-v1",
        "name": "Example research dataset",
        "source_url": "https://example.org/dataset",
        "version": "1.0",
        "retrieved_on": "not_downloaded",
        "modality": "image",
        "image_domain": "dermoscopy",
        "license": "unknown_pending_source_review",
        "license_review": "not_reviewed",
        "permitted_use_review": "not_reviewed",
        "privacy_review": "not_reviewed",
        "label_review": "not_reviewed",
        "patient_grouping": "unknown",
        "clinical_reviewer_signoff": "not_reviewed",
        "approval_status": "not_approved",
    }


def test_registry_record_never_automatically_approves_training():
    result = validate_dataset_record(valid_record())
    assert result["record_complete"] is True
    assert result["training_eligible"] is False
    assert result["automatic_approval"] is False


def test_registry_requires_source_and_governance_fields():
    record = valid_record()
    del record["license"]
    record["source_url"] = "http://example.org/data"
    result = validate_dataset_record(record)
    assert result["record_complete"] is False
    assert "license" in result["missing_fields"]
    assert "source_url_must_be_https" in result["validation_errors"]


def test_registry_rejects_unknown_review_states():
    record = valid_record()
    record["privacy_review"] = "approved_by_ai"
    result = validate_dataset_record(record)
    assert "invalid_privacy_review" in result["validation_errors"]


def test_registry_audit_reports_duplicate_ids_without_exposing_private_data(tmp_path):
    record = valid_record()
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"datasets": [record, record]}), encoding="utf-8")
    result = audit_registry(path)
    assert result["dataset_count"] == 2
    assert result["duplicate_dataset_ids"] == ["example-image-v1"]
    assert result["automatic_training_approval"] is False


@pytest.mark.parametrize("invalid_entry", [None, [], "not-an-object", 42])
def test_registry_rejects_non_object_entries_with_safe_error(tmp_path, invalid_entry):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"datasets": [invalid_entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match="entry at index 0 must be an object"):
        audit_registry(path)


def test_record_validator_rejects_non_object_input():
    with pytest.raises(ValueError, match="record must be an object"):
        validate_dataset_record(None)  # type: ignore[arg-type]
