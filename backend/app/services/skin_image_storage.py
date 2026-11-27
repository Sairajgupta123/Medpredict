"""Private object-storage contract and S3-compatible implementation.

The concrete adapter is opt-in and is never constructed automatically. Callers
must configure a private bucket, encryption, TLS, and least-privilege credentials.
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any, Protocol
from uuid import UUID

from app.services.skin_image_validation import MAX_IMAGE_BYTES, SUPPORTED_FORMATS


class SkinImageStorageUnavailable(RuntimeError):
    """Raised when no explicitly configured private storage adapter exists."""


class SkinImageStorageIntegrityError(RuntimeError):
    """Raised when bytes returned by private storage fail integrity checks."""


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


_OBJECT_KEY_PATTERN = re.compile(r"^skin-images/[0-9a-f]{32}\.(?:jpg|png|webp)$")
_ALLOWED_CONTENT_TYPES = {item[0] for item in SUPPORTED_FORMATS.values()}


def _validate_object_key(object_key: str) -> None:
    if not _OBJECT_KEY_PATTERN.fullmatch(object_key):
        raise ValueError("Object key must be a server-generated skin-image key.")


class S3PrivateSkinImageStorage:
    """S3-compatible private bucket adapter with encryption and SHA-256 checks.

    Supply an already-created SDK client to keep credential sourcing outside this
    class and make tests deterministic. No ACL or URL-generation operation exists.
    """

    def __init__(
        self,
        *,
        client: Any,
        bucket: str,
        encryption: str = "AES256",
        kms_key_id: str | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("A private object-storage bucket is required.")
        if encryption not in {"AES256", "aws:kms"}:
            raise ValueError("Server-side encryption must be AES256 or aws:kms.")
        if encryption == "aws:kms" and not (kms_key_id and kms_key_id.strip()):
            raise ValueError("A KMS key ID is required when using aws:kms encryption.")
        if encryption == "AES256" and kms_key_id:
            raise ValueError("A KMS key ID must not be supplied with AES256 encryption.")
        self._client = client
        self._bucket = bucket.strip()
        self._encryption = encryption
        self._kms_key_id = kms_key_id.strip() if kms_key_id else None

    def put_private(self, object_key: str, content: bytes, content_type: str) -> None:
        _validate_object_key(object_key)
        if not isinstance(content, bytes) or not content or len(content) > MAX_IMAGE_BYTES:
            raise ValueError("Only non-empty sanitized image bytes up to 8 MiB may be stored.")
        if content_type not in _ALLOWED_CONTENT_TYPES:
            raise ValueError("Unsupported sanitized image content type.")

        digest = hashlib.sha256(content).hexdigest()
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": object_key,
            "Body": content,
            "ContentLength": len(content),
            "ContentType": content_type,
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(digest)).decode("ascii"),
            "Metadata": {"sha256": digest},
            "ServerSideEncryption": self._encryption,
        }
        if self._kms_key_id:
            params["SSEKMSKeyId"] = self._kms_key_id
        # Deliberately omit ACL: bucket policy must keep objects private.
        self._client.put_object(**params)

    def get_private(self, object_key: str) -> bytes:
        _validate_object_key(object_key)
        response = self._client.get_object(Bucket=self._bucket, Key=object_key)
        body = response["Body"]
        try:
            content = body.read(MAX_IMAGE_BYTES + 1)
        finally:
            body.close()
        if len(content) > MAX_IMAGE_BYTES:
            raise SkinImageStorageIntegrityError("Stored image exceeds the configured size limit.")
        expected = response.get("Metadata", {}).get("sha256")
        actual = hashlib.sha256(content).hexdigest()
        if not expected or not re.fullmatch(r"[0-9a-f]{64}", expected) or actual != expected:
            raise SkinImageStorageIntegrityError("Stored image failed its SHA-256 integrity check.")
        return content

    def delete_private(self, object_key: str) -> None:
        _validate_object_key(object_key)
        # In a versioned bucket, DeleteObject only creates a delete marker;
        # previous object versions would continue retaining the image bytes.
        # Permanently remove every version and delete marker for this exact key.
        versioning = self._client.get_bucket_versioning(Bucket=self._bucket)
        status = versioning.get("Status")
        if status in {"Enabled", "Suspended"}:
            key_marker = None
            version_marker = None
            while True:
                params: dict[str, Any] = {
                    "Bucket": self._bucket,
                    "Prefix": object_key,
                }
                if key_marker is not None:
                    params["KeyMarker"] = key_marker
                if version_marker is not None:
                    params["VersionIdMarker"] = version_marker
                page = self._client.list_object_versions(**params)
                targets = [
                    {"Key": item["Key"], "VersionId": item["VersionId"]}
                    for collection in ("Versions", "DeleteMarkers")
                    for item in page.get(collection, [])
                    if item.get("Key") == object_key and "VersionId" in item
                ]
                for offset in range(0, len(targets), 1000):
                    result = self._client.delete_objects(
                        Bucket=self._bucket,
                        Delete={"Objects": targets[offset:offset + 1000], "Quiet": True},
                    )
                    if result.get("Errors"):
                        raise RuntimeError("Private image version deletion was incomplete.")
                if not page.get("IsTruncated"):
                    return
                next_key_marker = page.get("NextKeyMarker")
                next_version_marker = page.get("NextVersionIdMarker")
                if (
                    not next_key_marker
                    or (next_key_marker, next_version_marker) == (key_marker, version_marker)
                ):
                    raise RuntimeError("Object version listing returned an invalid continuation marker.")
                key_marker = next_key_marker
                version_marker = next_version_marker
            return
        # S3 DeleteObject is idempotent for an absent key in an unversioned bucket.
        self._client.delete_object(Bucket=self._bucket, Key=object_key)


def create_s3_private_client(
    *,
    region: str,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
) -> Any:
    """Create an S3 client with TLS verification and SigV4 enabled.

    Credentials are optional to allow the SDK's IAM role/credential-chain
    providers. Custom endpoints must use HTTPS; insecure local endpoints are
    intentionally not supported by this production-oriented factory.
    """
    if not region.strip():
        raise ValueError("An object-storage region is required.")
    if bool(access_key_id) != bool(secret_access_key):
        raise ValueError("Both access key ID and secret access key must be supplied together.")
    if endpoint_url is not None and not endpoint_url.lower().startswith("https://"):
        raise ValueError("Custom object-storage endpoints must use HTTPS.")
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
        raise SkinImageStorageUnavailable("The S3 SDK is not installed.") from exc

    kwargs: dict[str, Any] = {
        "region_name": region.strip(),
        "use_ssl": True,
        "verify": True,
        "config": Config(signature_version="s3v4", retries={"max_attempts": 4, "mode": "standard"}),
    }
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    if access_key_id and secret_access_key:
        kwargs["aws_access_key_id"] = access_key_id
        kwargs["aws_secret_access_key"] = secret_access_key
    return boto3.client("s3", **kwargs)


def build_skin_image_object_key(image_id: UUID, image_format: str) -> str:
    """Build an opaque, non-user-identifying key from a server-generated UUID."""
    if image_format not in SUPPORTED_FORMATS:
        raise ValueError("Unsupported sanitized skin-image format.")
    extension = SUPPORTED_FORMATS[image_format][1]
    return f"skin-images/{image_id.hex}.{extension}"
