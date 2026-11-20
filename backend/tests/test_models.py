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
