"""Tests for fail-closed private skin-image storage contract."""

from uuid import UUID

import pytest

from app.services.skin_image_storage import (
    DisabledSkinImageStorage,
    SkinImageStorageUnavailable,
    build_skin_image_object_key,
)


def test_object_key_uses_only_server_generated_image_uuid_and_safe_extension() -> None:
    image_id = UUID("12345678-1234-5678-1234-567812345678")
    assert build_skin_image_object_key(image_id, "JPEG") == (
        "skin-images/12345678123456781234567812345678.jpg"
    )
    assert build_skin_image_object_key(image_id, "PNG").endswith(".png")
    assert build_skin_image_object_key(image_id, "WEBP").endswith(".webp")


def test_object_key_rejects_unsupported_format() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        build_skin_image_object_key(UUID(int=1), "SVG")


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("put_private", ("skin-images/example.jpg", b"image", "image/jpeg")),
        ("get_private", ("skin-images/example.jpg",)),
        ("delete_private", ("skin-images/example.jpg",)),
    ],
)
def test_default_storage_fails_closed(method: str, args: tuple[object, ...]) -> None:
    storage = DisabledSkinImageStorage()
    with pytest.raises(SkinImageStorageUnavailable, match="disabled|unavailable"):
        getattr(storage, method)(*args)

class _FakeBody:
    def __init__(self, content: bytes) -> None:
        from io import BytesIO
        self._buffer = BytesIO(content)

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def close(self) -> None:
        self._buffer.close()


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}
        self.put_calls: list[dict[str, object]] = []
        self.deleted: list[str] = []

    def put_object(self, **kwargs) -> None:
        self.put_calls.append(kwargs)
        self.objects[kwargs["Key"]] = {
            "Body": kwargs["Body"],
            "Metadata": kwargs["Metadata"],
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        stored = self.objects[Key]
        return {"Body": _FakeBody(stored["Body"]), "Metadata": stored["Metadata"]}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deleted.append(Key)
        self.objects.pop(Key, None)

    def get_bucket_versioning(self, *, Bucket: str) -> dict[str, str]:
        return {}


def test_s3_adapter_encrypts_private_object_and_verifies_sha256() -> None:
    import hashlib

    from app.services.skin_image_storage import S3PrivateSkinImageStorage

    client = _FakeS3Client()
    storage = S3PrivateSkinImageStorage(client=client, bucket="private-medical-images")
    key = build_skin_image_object_key(UUID(int=2), "JPEG")
    content = b"sanitized-jpeg-bytes"

    storage.put_private(key, content, "image/jpeg")
    params = client.put_calls[0]
    assert params["ServerSideEncryption"] == "AES256"
    assert params["Metadata"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert "ACL" not in params
    assert storage.get_private(key) == content

    storage.delete_private(key)
    storage.delete_private(key)
    assert client.deleted == [key, key]


def test_s3_adapter_supports_kms_and_requires_key_id() -> None:
    from app.services.skin_image_storage import S3PrivateSkinImageStorage

    with pytest.raises(ValueError, match="KMS key"):
        S3PrivateSkinImageStorage(
            client=_FakeS3Client(), bucket="private", encryption="aws:kms"
        )
    client = _FakeS3Client()
    storage = S3PrivateSkinImageStorage(
        client=client,
        bucket="private",
        encryption="aws:kms",
        kms_key_id="alias/medipredict-images",
    )
    storage.put_private(
        build_skin_image_object_key(UUID(int=3), "PNG"), b"png-data", "image/png"
    )
    assert client.put_calls[0]["SSEKMSKeyId"] == "alias/medipredict-images"


def test_s3_adapter_rejects_unsafe_keys_and_content_types() -> None:
    from app.services.skin_image_storage import S3PrivateSkinImageStorage

    storage = S3PrivateSkinImageStorage(client=_FakeS3Client(), bucket="private")
    with pytest.raises(ValueError, match="server-generated"):
        storage.delete_private("../public/image.jpg")
    with pytest.raises(ValueError, match="content type"):
        storage.put_private(
            build_skin_image_object_key(UUID(int=4), "JPEG"), b"data", "text/plain"
        )


def test_s3_adapter_detects_corrupted_object_bytes() -> None:
    from app.services.skin_image_storage import (
        S3PrivateSkinImageStorage,
        SkinImageStorageIntegrityError,
    )

    client = _FakeS3Client()
    storage = S3PrivateSkinImageStorage(client=client, bucket="private")
    key = build_skin_image_object_key(UUID(int=5), "WEBP")
    storage.put_private(key, b"original", "image/webp")
    client.objects[key]["Body"] = b"tampered"
    with pytest.raises(SkinImageStorageIntegrityError, match="SHA-256"):
        storage.get_private(key)


def test_s3_client_factory_rejects_insecure_or_partial_configuration() -> None:
    from app.services.skin_image_storage import create_s3_private_client

    with pytest.raises(ValueError, match="HTTPS"):
        create_s3_private_client(region="ap-south-1", endpoint_url="http://localhost:9000")
    with pytest.raises(ValueError, match="Both access key"):
        create_s3_private_client(
            region="ap-south-1", access_key_id="only-one-half"
        )

def test_s3_adapter_rejects_missing_or_malformed_integrity_metadata() -> None:
    from app.services.skin_image_storage import (
        S3PrivateSkinImageStorage,
        SkinImageStorageIntegrityError,
    )

    client = _FakeS3Client()
    storage = S3PrivateSkinImageStorage(client=client, bucket="private")
    key = build_skin_image_object_key(UUID(int=6), "JPEG")
    storage.put_private(key, b"valid-image-content", "image/jpeg")

    client.objects[key]["Metadata"] = {}
    with pytest.raises(SkinImageStorageIntegrityError, match="SHA-256"):
        storage.get_private(key)

    client.objects[key]["Metadata"] = {"sha256": "not-a-sha256"}
    with pytest.raises(SkinImageStorageIntegrityError, match="SHA-256"):
        storage.get_private(key)


def test_s3_adapter_rejects_empty_and_oversized_uploads() -> None:
    from app.services.skin_image_storage import S3PrivateSkinImageStorage
    from app.services.skin_image_validation import MAX_IMAGE_BYTES

    storage = S3PrivateSkinImageStorage(client=_FakeS3Client(), bucket="private")
    key = build_skin_image_object_key(UUID(int=7), "PNG")

    with pytest.raises(ValueError, match="non-empty"):
        storage.put_private(key, b"", "image/png")
    with pytest.raises(ValueError, match="8 MiB"):
        storage.put_private(key, b"x" * (MAX_IMAGE_BYTES + 1), "image/png")


def test_s3_adapter_rejects_oversized_download_before_returning_bytes() -> None:
    from app.services.skin_image_storage import (
        S3PrivateSkinImageStorage,
        SkinImageStorageIntegrityError,
    )
    from app.services.skin_image_validation import MAX_IMAGE_BYTES

    client = _FakeS3Client()
    storage = S3PrivateSkinImageStorage(client=client, bucket="private")
    key = build_skin_image_object_key(UUID(int=8), "WEBP")
    client.objects[key] = {
        "Body": b"x" * (MAX_IMAGE_BYTES + 1),
        "Metadata": {"sha256": "0" * 64},
    }

    with pytest.raises(SkinImageStorageIntegrityError, match="size limit"):
        storage.get_private(key)



def test_s3_adapter_permanently_deletes_all_versions_and_delete_markers() -> None:
    from app.services.skin_image_storage import S3PrivateSkinImageStorage

    class VersionedClient(_FakeS3Client):
        def __init__(self) -> None:
            super().__init__()
            self.pages = [
                {
                    "Versions": [
                        {"Key": "skin-images/0123456789abcdef0123456789abcdef.jpg", "VersionId": "v1"},
                        {"Key": "skin-images/0123456789abcdef0123456789abcdef.jpg", "VersionId": "v2"},
                        {"Key": "skin-images/ffffffffffffffffffffffffffffffff.jpg", "VersionId": "keep"},
                    ],
                    "DeleteMarkers": [
                        {"Key": "skin-images/0123456789abcdef0123456789abcdef.jpg", "VersionId": "marker1"}
                    ],
                    "IsTruncated": True,
                    "NextKeyMarker": "skin-images/0123456789abcdef0123456789abcdef.jpg",
                    "NextVersionIdMarker": "v2",
                },
                {
                    "Versions": [
                        {"Key": "skin-images/0123456789abcdef0123456789abcdef.jpg", "VersionId": "v3"}
                    ],
                    "DeleteMarkers": [],
                    "IsTruncated": False,
                },
            ]
            self.list_calls = []
            self.delete_batches = []

        def get_bucket_versioning(self, *, Bucket: str) -> dict[str, str]:
            return {"Status": "Enabled"}

        def list_object_versions(self, **kwargs):
            self.list_calls.append(kwargs)
            return self.pages.pop(0)

        def delete_objects(self, *, Bucket: str, Delete: dict):
            self.delete_batches.append(Delete["Objects"])
            return {"Deleted": Delete["Objects"]}

    client = VersionedClient()
    storage = S3PrivateSkinImageStorage(client=client, bucket="private")
    storage.delete_private("skin-images/0123456789abcdef0123456789abcdef.jpg")

    assert len(client.list_calls) == 2
    assert client.list_calls[1]["KeyMarker"] == "skin-images/0123456789abcdef0123456789abcdef.jpg"
    assert client.list_calls[1]["VersionIdMarker"] == "v2"
    assert [item["VersionId"] for item in client.delete_batches[0]] == [
        "v1", "v2", "marker1"
    ]
    assert [item["VersionId"] for item in client.delete_batches[1]] == ["v3"]
    assert all(item["Key"] == "skin-images/0123456789abcdef0123456789abcdef.jpg" for batch in client.delete_batches for item in batch)


def test_s3_adapter_raises_when_version_delete_reports_partial_failure() -> None:
    from app.services.skin_image_storage import S3PrivateSkinImageStorage

    class FailingVersionedClient(_FakeS3Client):
        def get_bucket_versioning(self, *, Bucket: str) -> dict[str, str]:
            return {"Status": "Enabled"}

        def list_object_versions(self, **kwargs):
            return {
                "Versions": [{"Key": kwargs["Prefix"], "VersionId": "v1"}],
                "IsTruncated": False,
            }

        def delete_objects(self, *, Bucket: str, Delete: dict):
            return {"Errors": [{"Key": Delete["Objects"][0]["Key"], "Code": "AccessDenied"}]}

    storage = S3PrivateSkinImageStorage(
        client=FailingVersionedClient(), bucket="private"
    )
    with pytest.raises(RuntimeError, match="version deletion was incomplete"):
        storage.delete_private("skin-images/0123456789abcdef0123456789abcdef.jpg")


def test_s3_adapter_rejects_non_advancing_version_pagination() -> None:
    from app.services.skin_image_storage import S3PrivateSkinImageStorage

    class StuckVersionedClient(_FakeS3Client):
        def get_bucket_versioning(self, *, Bucket: str) -> dict[str, str]:
            return {"Status": "Enabled"}

        def list_object_versions(self, **kwargs):
            return {
                "Versions": [],
                "DeleteMarkers": [],
                "IsTruncated": True,
                "NextKeyMarker": kwargs.get("KeyMarker"),
                "NextVersionIdMarker": kwargs.get("VersionIdMarker"),
            }

    storage = S3PrivateSkinImageStorage(
        client=StuckVersionedClient(), bucket="private"
    )
    with pytest.raises(RuntimeError, match="invalid continuation marker"):
        storage.delete_private("skin-images/0123456789abcdef0123456789abcdef.jpg")
