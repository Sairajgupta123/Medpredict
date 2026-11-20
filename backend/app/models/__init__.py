"""ORM model registry.

Importing this module registers every model with the shared SQLAlchemy metadata.
"""

from app.models.catalog import CatalogReviewEvent, Disease, DiseaseSymptom, Symptom
from app.models.catalog_reference import CatalogReference, CatalogReferenceEvent
from app.models.feedback import PredictionFeedback
from app.models.knowledge import (
    CareRecommendation,
    MedicalReference,
    RecommendationReference,
)
from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent
from app.models.password_reset import PasswordResetToken
from app.models.prediction import (
    Prediction,
    PredictionConsentEvent,
    PredictionResult,
    SkinImageAnalysis,
)
from app.models.user import RoleProvisioningEvent, User

__all__ = [
    "CareRecommendation",
    "CatalogReviewEvent",
    "CatalogReference",
    "CatalogReferenceEvent",
    "CatalogReviewerScope",
    "CatalogReviewerScopeEvent",
    "Disease",
    "DiseaseSymptom",
    "MedicalReference",
    "PasswordResetToken",
    "Prediction",
    "PredictionConsentEvent",
    "PredictionFeedback",
    "PredictionResult",
    "RecommendationReference",
    "RoleProvisioningEvent",
    "SkinImageAnalysis",
    "Symptom",
    "User",
]
