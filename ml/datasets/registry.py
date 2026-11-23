"""Human-reviewed dataset provenance registry.

This registry records source and governance evidence. It never grants training or deployment
approval automatically.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REQUIRED_FIELDS = {
    "dataset_id", "name", "source_url", "version", "retrieved_on",
    "modality", "image_domain", "license", "license_review",
    "permitted_use_review", "privacy_review", "label_review",
    "patient_grouping", "clinical_reviewer_signoff", "approval_status",
}
REVIEW_STATES = {"not_reviewed", "in_review", "approved", "rejected"}
APPROVAL_STATES = {"not_approved", "research_only_approved", "rejected"}
MODALITIES = {"image", "text", "tabular", "multimodal"}
IMAGE_DOMAINS = {"dermoscopy", "clinical_phone_photo", "not_applicable", "mixed", "unknown"}


def validate_dataset_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return aggregate validation results; never infer or grant approval."""
    if not isinstance(record, dict):
        raise ValueError("Dataset registry record must be an object")
    missing = sorted(REQUIRED_FIELDS - set(record))
    errors: list[str] = []
    if missing:
        errors.append("required_fields_missing")

    for field in (
        "dataset_id", "name", "version", "retrieved_on", "license", "patient_grouping"
    ):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"invalid_{field}")
    if record.get("modality") not in MODALITIES:
        errors.append("invalid_modality")
    if record.get("image_domain") not in IMAGE_DOMAINS:
        errors.append("invalid_image_domain")

    source_url = str(record.get("source_url", "")).strip()
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.netloc:
        errors.append("source_url_must_be_https")

    for field in (
        "license_review", "permitted_use_review", "privacy_review", "label_review"
    ):
        if record.get(field) not in REVIEW_STATES:
            errors.append(f"invalid_{field}")

    if record.get("clinical_reviewer_signoff") not in REVIEW_STATES:
        errors.append("invalid_clinical_reviewer_signoff")
    if record.get("approval_status") not in APPROVAL_STATES:
        errors.append("invalid_approval_status")

    # The validator intentionally cannot mark a dataset approved.
    return {
        "dataset_id": str(record.get("dataset_id", "")),
        "record_complete": not missing and not errors,
        "missing_fields": missing,
        "validation_errors": errors,
        "training_eligible": False,
        "automatic_approval": False,
        "notice": (
            "This technical registry check does not approve training. Research approval requires "
            "documented source-specific rights, privacy review, label review and human sign-off."
        ),
    }


def audit_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Registry file does not exist: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("datasets"), list):
        raise ValueError("Registry JSON must contain a datasets array")
    for index, item in enumerate(data["datasets"]):
        if not isinstance(item, dict):
            raise ValueError(f"Dataset registry entry at index {index} must be an object")
    results = [validate_dataset_record(item) for item in data["datasets"]]
    ids = [
        item.get("dataset_id")
        for item in data["datasets"]
        if isinstance(item.get("dataset_id"), str) and item.get("dataset_id").strip()
    ]
    duplicate_ids = sorted(
        value for value, count in Counter(ids).items() if count > 1
    )
    return {
        "dataset_count": len(results),
        "records_complete": sum(item["record_complete"] for item in results),
        "duplicate_dataset_ids": duplicate_ids,
        "records": results,
        "automatic_training_approval": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = audit_registry(args.registry)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Dataset registry audit written to {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
