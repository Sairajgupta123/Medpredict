"""Build the opt-in private skin-image storage adapter from runtime settings."""

from app.core.config import Settings, get_settings
from app.services.skin_image_storage import (
    DisabledSkinImageStorage,
    S3PrivateSkinImageStorage,
    create_s3_private_client,
)


def build_skin_image_storage(settings: Settings | None = None):
    """Return disabled storage unless bucket and region are explicitly configured."""
    configured = settings or get_settings()
    bucket = configured.skin_image_s3_bucket
    region = configured.skin_image_s3_region
    if not bucket or not bucket.strip() or not region or not region.strip():
        return DisabledSkinImageStorage()
    client = create_s3_private_client(
        region=region,
        endpoint_url=configured.skin_image_s3_endpoint_url,
    )
    return S3PrivateSkinImageStorage(
        client=client,
        bucket=bucket,
        encryption=configured.skin_image_s3_encryption,
        kms_key_id=configured.skin_image_s3_kms_key_id,
    )
