"""Private object-storage contract for skin images.

No concrete cloud or filesystem adapter is enabled in this module. The default
implementation fails closed so callers cannot accidentally persist images.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.services.skin_image_validation import SUPPORTED_FORMATS


class SkinImageStorageUnavailable(RuntimeError):
    """Raised when no explicitly configured private storage adapter exists."""


class SkinImageStorage(Protocol):
    """Contract every production adapter must satisfy.

    Implementations must use private buckets/containers, server-side encryption,
    TLS, least-privilege credentials, and must never return public object URLs.
    delete_private must be idempotent: deleting an absent key is successful.
    Adapters must not log image bytes, credentials, or user-identifying metadata.
    """

    def put_private(self, object_key: str, content: bytes, content_type: str) -> None:
        """Store sanitized bytes under a server-generated opaque object key."""

    def get_private(self, object_key: str) -> bytes:
        """Read an object only for an already-authorized application request."""

    def delete_private(self, object_key: str) -> None:
        """Permanently delete an object; repeated deletion must be safe."""


class DisabledSkinImageStorage:
    """Fail-closed adapter used until private storage is configured and reviewed."""

    def put_private(self, object_key: str, content: bytes, content_type: str) -> None:
        raise SkinImageStorageUnavailable(
            "Skin-image storage is disabled until a private storage adapter is configured."
        )

    def get_private(self, object_key: str) -> bytes:
        raise SkinImageStorageUnavailable(
            "Skin-image retrieval is disabled until a private storage adapter is configured."
        )

    def delete_private(self, object_key: str) -> None:
        raise SkinImageStorageUnavailable(
            "Skin-image deletion is unavailable until a private storage adapter is configured."
        )


def build_skin_image_object_key(image_id: UUID, image_format: str) -> str:
    """Build an opaque, non-user-identifying key from a server-generated UUID."""
    if image_format not in SUPPORTED_FORMATS:
        raise ValueError("Unsupported sanitized skin-image format.")
    extension = SUPPORTED_FORMATS[image_format][1]
    return f"skin-images/{image_id.hex}.{extension}"