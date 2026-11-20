"""Read-only access to the curated research symptom vocabulary."""

import json
from typing import Any

from app.services.symptom_normalizer import DEFAULT_TAXONOMY_PATH


def get_symptom_catalog() -> dict[str, Any]:
    """Return public identifiers and labels without exposing phrase aliases."""
    payload = json.loads(DEFAULT_TAXONOMY_PATH.read_text(encoding="utf-8"))
    return {
        "taxonomy_version": payload["taxonomy_version"],
        "status": payload["status"],
        "language": payload["language"],
        "clinical_interpretation_performed": False,
        "symptoms": [
            {
                "id": item["id"],
                "label": item["label"],
                "category": item["category"],
            }
            for item in payload["symptoms"]
        ],
        "disclaimer": (
            "This limited research vocabulary is not clinically validated. "
            "Selecting a phrase records only what the user reports, not a diagnosis."
        ),
    }
