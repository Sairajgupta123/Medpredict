"""Research-only overlap matching against the reviewed catalog.

This reports catalog coverage, not disease probability, diagnosis, or clinical risk.
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import Disease, DiseaseSymptom, Symptom


def match_approved_catalog(db: Session, symptom_codes: list[str]) -> list[dict]:
    """Compare supplied symptom IDs with approved disease associations only."""
    requested = set(symptom_codes)
    approved_symptoms = db.scalars(
        select(Symptom).where(
            Symptom.code.in_(requested),
            Symptom.is_active.is_(True),
            Symptom.review_status == "approved",
            Symptom.reviewed_by.is_not(None),
            Symptom.reviewed_at.is_not(None),
        )
    ).all()
    if len(approved_symptoms) != len(requested):
        raise HTTPException(
            status_code=422,
            detail="One or more symptom IDs are not in the approved catalog.",
        )

    rows = db.execute(
        select(Disease, Symptom, DiseaseSymptom)
        .join(DiseaseSymptom, DiseaseSymptom.disease_id == Disease.id)
        .join(Symptom, Symptom.id == DiseaseSymptom.symptom_id)
        .where(
            Disease.is_active.is_(True),
            Disease.review_status == "approved",
            Disease.reviewed_by.is_not(None),
            Disease.reviewed_at.is_not(None),
            Symptom.is_active.is_(True),
            Symptom.review_status == "approved",
            Symptom.reviewed_by.is_not(None),
            Symptom.reviewed_at.is_not(None),
            DiseaseSymptom.review_status == "approved",
            DiseaseSymptom.reviewed_by.is_not(None),
            DiseaseSymptom.reviewed_at.is_not(None),
        )
        .order_by(Disease.code.asc(), Symptom.code.asc())
    ).all()

    by_disease: dict[UUID, dict] = {}
    for disease, symptom, link in rows:
        item = by_disease.setdefault(
            disease.id,
            {
                "disease_code": disease.code,
                "disease_name": disease.name,
                "catalog_symptom_count": 0,
                "matched_symptoms": [],
                "matched_symptom_count": 0,
            },
        )
        item["catalog_symptom_count"] += 1
        if symptom.code in requested:
            item["matched_symptoms"].append(
                {"symptom_code": symptom.code, "symptom_name": symptom.name}
            )
            item["matched_symptom_count"] += 1

    matches = [
        item for item in by_disease.values()
        if item["matched_symptom_count"] > 0
    ]
    for item in matches:
        item["catalog_overlap_ratio"] = round(
            item["matched_symptom_count"] / item["catalog_symptom_count"], 4
        )
    return sorted(
        matches,
        key=lambda item: (
            -item["matched_symptom_count"],
            -item["catalog_overlap_ratio"],
            item["disease_code"],
        ),
    )
