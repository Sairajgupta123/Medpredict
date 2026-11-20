"""Structural tests for the initial ORM schema."""

from app.db.base import Base
from app.models import (  # noqa: F401 - imports register model metadata
    Disease,
    DiseaseSymptom,
    Prediction,
    PredictionFeedback,
    PredictionResult,
    SkinImageAnalysis,
    Symptom,
    User,
    CareRecommendation,
    MedicalReference,
    RecommendationReference,
)


def test_all_initial_tables_are_registered() -> None:
    expected = {
        "users",
        "diseases",
        "symptoms",
        "disease_symptoms",
        "predictions",
        "prediction_results",
        "skin_image_analyses",
        "prediction_feedback",
        "medical_references",
        "care_recommendations",
        "recommendation_references",
    }
    assert expected.issubset(set(Base.metadata.tables))


def test_prediction_has_nullable_user_for_guest_flow() -> None:
    user_column = Prediction.__table__.c.user_id
    assert user_column.nullable is True


def test_skin_image_is_metadata_not_binary_storage() -> None:
    columns = set(SkinImageAnalysis.__table__.c.keys())
    assert "object_key" in columns
    assert "image_bytes" not in columns


def test_result_probability_has_numeric_precision() -> None:
    probability_type = PredictionResult.__table__.c.probability.type
    assert probability_type.precision == 7
    assert probability_type.scale == 6


def test_knowledge_content_defaults_to_unpublished() -> None:
    assert CareRecommendation.is_active.default.arg is False
    assert CareRecommendation.review_status.default.arg == "draft"
    assert MedicalReference.review_status.default.arg == "draft"


def test_approved_knowledge_requires_auditable_review_metadata() -> None:
    medical_constraints = {
        constraint.name for constraint in MedicalReference.__table__.constraints
    }
    recommendation_constraints = {
        constraint.name for constraint in CareRecommendation.__table__.constraints
    }
    assert "ck_medical_reference_approval_audit" in medical_constraints
    assert "ck_care_recommendation_approval_audit" in recommendation_constraints
    assert "ck_care_recommendation_validity_window" in recommendation_constraints


def test_recommendation_reference_has_composite_identity() -> None:
    primary_key_columns = set(
        RecommendationReference.__table__.primary_key.columns.keys()
    )
    assert primary_key_columns == {"recommendation_id", "reference_id"}

def test_disease_symptom_links_default_to_unreviewed_and_require_audit() -> None:
    assert DiseaseSymptom.review_status.default.arg == "draft"
    constraints = {
        constraint.name for constraint in DiseaseSymptom.__table__.constraints
    }
    assert "ck_disease_symptoms_review_status" in constraints
    assert "ck_disease_symptoms_approval_audit" in constraints

