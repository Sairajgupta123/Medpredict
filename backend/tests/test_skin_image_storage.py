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