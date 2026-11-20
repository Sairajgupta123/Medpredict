"""ORM model registry.

Importing this module registers every model with the shared SQLAlchemy metadata.
"""

from app.models.catalog import Disease, DiseaseSymptom, Symptom
from app.models.feedback import PredictionFeedback
from app.models.prediction import Prediction, PredictionResult, SkinImageAnalysis
from app.models.user import User

__all__ = [
    "Disease",
    "DiseaseSymptom",
    "Prediction",
    "PredictionFeedback",
    "PredictionResult",
    "SkinImageAnalysis",
    "Symptom",
    "User",
]
