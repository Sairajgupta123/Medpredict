"""Explicit boundary for optional skin-image ML inference.

No classifier is bundled or assumed by this module. The default adapter fails
closed. A future model adapter must return provenance-backed, calibrated
outputs and explicitly abstain when it cannot provide a safe result.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SkinImageModelUnavailable(RuntimeError):
    """Raised when no approved skin-image model is configured."""


class InvalidSkinImageModelOutput(ValueError):
    """Raised when a model adapter returns incomplete or unsafe metadata."""


@dataclass(frozen=True)
class SkinImageInferenceResult:
    """Validated model candidate metadata, not a medical diagnosis."""

    abstained: bool
    model_version: str
    model_artifact_sha256: str
    candidate_label: str | None = None
    confidence: float | None = None
    confidence_calibrated: bool = False
    abstention_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.abstained, bool):
            raise InvalidSkinImageModelOutput("The abstained flag must be boolean.")
        if not isinstance(self.confidence_calibrated, bool):
            raise InvalidSkinImageModelOutput("The confidence_calibrated flag must be boolean.")
        if (
            not isinstance(self.model_version, str)
            or not self.model_version
            or self.model_version != self.model_version.strip()
            or len(self.model_version) > 100
        ):
            raise InvalidSkinImageModelOutput("A valid model version is required.")
        if (
            not isinstance(self.model_artifact_sha256, str)
            or not _SHA256_RE.fullmatch(self.model_artifact_sha256)
        ):
            raise InvalidSkinImageModelOutput(
                "A verified SHA-256 model artifact digest is required."
            )
        if self.abstained:
            if self.candidate_label is not None or self.confidence is not None:
                raise InvalidSkinImageModelOutput(
                    "Abstained results must not contain a candidate or confidence."
                )
            if (
                not isinstance(self.abstention_reason, str)
                or not self.abstention_reason.strip()
                or len(self.abstention_reason.strip()) > 240
            ):
                raise InvalidSkinImageModelOutput(
                    "Abstained results require a concise reason."
                )
            return

        if not self.confidence_calibrated:
            raise InvalidSkinImageModelOutput(
                "Uncalibrated model confidence cannot be returned as a result."
            )
        if (
            not isinstance(self.candidate_label, str)
            or not self.candidate_label
            or self.candidate_label != self.candidate_label.strip()
            or len(self.candidate_label) > 160
        ):
            raise InvalidSkinImageModelOutput("A valid candidate label is required.")
        if (
            self.confidence is None
            or isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(self.confidence)
            or not 0.0 <= self.confidence <= 1.0
        ):
            raise InvalidSkinImageModelOutput(
                "Confidence must be a finite value between 0 and 1."
            )
        if self.abstention_reason is not None:
            raise InvalidSkinImageModelOutput(
                "A non-abstained result cannot include an abstention reason."
            )


class SkinImageModel(Protocol):
    """Interface implemented only by an explicitly configured model adapter."""

    def predict(
        self, image_bytes: bytes, content_type: str
    ) -> SkinImageInferenceResult:
        """Return provenance-backed output or explicitly abstain."""


class DisabledSkinImageModel:
    """Safe default until an approved, tested model artifact is configured."""

    def predict(
        self, image_bytes: bytes, content_type: str
    ) -> SkinImageInferenceResult:
        raise SkinImageModelUnavailable(
            "Skin-image classification is not configured; no prediction was made."
        )
