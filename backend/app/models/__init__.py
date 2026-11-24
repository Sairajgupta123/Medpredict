"""ORM model registry.

Importing this module registers every model with the shared SQLAlchemy metadata.
"""

from app.models.account_deletion import AccountDeletionRequest
from app.models.auth_rate_limit import AuthRateLimitBucket
from app.models.catalog import CatalogReviewEvent, Disease, DiseaseSymptom, Symptom
from app.models.catalog_reference import CatalogReference, CatalogReferenceEvent
from app.models.email_verification import EmailVerificationToken
from app.models.feedback import PredictionFeedback
from app.models.knowledge import (
    CareRecommendation,
    MedicalReference,
    MedicalReferenceEvent,
    RecommendationReference,
)
from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent
from app.models.password_reset import PasswordResetToken
from app.models.prediction import (
    Prediction,
    PredictionConsentEvent,
    PredictionResult,
    SkinImageAnalysis,
    SkinImageReviewEvent,
)
from app.models.user import RoleProvisioningEvent, User

__all__ = [
    "AccountDeletionRequest",
    "AuthRateLimitBucket",
    "CareRecommendation",
    "CatalogReviewEvent",
    "CatalogReference",
    "CatalogReferenceEvent",
    "CatalogReviewerScope",
    "CatalogReviewerScopeEvent",
    "Disease",
    "DiseaseSymptom",
    "EmailVerificationToken",
    "MedicalReference",
    "MedicalReferenceEvent",
    "PasswordResetToken",
    "Prediction",
    "PredictionConsentEvent",
    "PredictionFeedback",
    "PredictionResult",
    "RecommendationReference",
    "RoleProvisioningEvent",
    "SkinImageAnalysis",
    "SkinImageReviewEvent",
    "Symptom",
    "User",
]
