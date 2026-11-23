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
