"""
tests/unit/test_storage_service.py — Unit tests for services/storage_service.py

Uses moto's mock_aws to intercept all real boto3/S3 calls.
Environment variables MUST be set before importing services to prevent
any accidental real-AWS calls at import time.

Covers:
  - ensure_bucket_exists: creates bucket, idempotent (call twice)
  - upload_image: uploads successfully, returns s3_key
  - get_image_bytes: round-trip (upload then download) yields identical bytes
  - delete_image: object no longer exists after delete
  - list_objects: returns correct list of {key, size} dicts
  - generate_presigned_url: returns a non-empty string URL
"""

import os

# Set dummy AWS credentials BEFORE any boto3/moto import so that moto
# intercepts all calls and no real-AWS request is ever attempted.
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

import pytest
from moto import mock_aws

# Now safe to import the service
from services.storage_service import StorageService
from services.models import StorageError


# ---------------------------------------------------------------------------
# Shared test configuration
# ---------------------------------------------------------------------------

class _TestConfig:
    """Minimal AppConfig-compatible object pointing at fake/moto S3."""
    ENDPOINT_URL = None           # moto intercepts without a real endpoint
    AWS_ACCESS_KEY = "testing"
    AWS_SECRET_KEY = "testing"
    AWS_REGION = "us-east-1"
    S3_BUCKET_NAME = "test-bucket"
    DYNAMODB_TABLE_NAME = "test-metadata"
    S3_ADDRESSING_STYLE = "path"
    S3_SIGNATURE_VERSION = "s3v4"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def storage_service(aws_credentials):
    """Return a StorageService wired to the moto-patched environment."""
    return StorageService(config=_TestConfig)


@pytest.fixture
def aws_credentials():
    """Ensure dummy credentials are set (already done at module level, kept for clarity)."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def sample_image_bytes() -> bytes:
    """Return a tiny but real PNG so tests exercise realistic payloads."""
    import io
    from PIL import Image
    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ensure_bucket_exists
# ---------------------------------------------------------------------------

@mock_aws
class TestEnsureBucketExists:
    def test_creates_bucket(self):
        """Req 1.6: Bucket is created when it does not yet exist."""
        import boto3
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        s3 = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        buckets = [b["Name"] for b in s3.list_buckets()["Buckets"]]
        assert _TestConfig.S3_BUCKET_NAME in buckets

    def test_idempotent_double_call(self):
        """Calling ensure_bucket_exists twice must not raise."""
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()
        svc.ensure_bucket_exists()  # second call — should be a no-op


# ---------------------------------------------------------------------------
# upload_image
# ---------------------------------------------------------------------------

@mock_aws
class TestUploadImage:
    def test_upload_returns_s3_key(self, sample_image_bytes):
        """Req 1.2: upload_image returns the same s3_key that was passed in."""
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        key = "images/test_image.png"
        returned_key = svc.upload_image(sample_image_bytes, key, "image/png")
        assert returned_key == key

    def test_upload_object_exists_in_bucket(self, sample_image_bytes):
        """After upload, the object must be retrievable from S3."""
        import boto3
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        key = "images/exists_check.png"
        svc.upload_image(sample_image_bytes, key, "image/png")

        s3 = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        # head_object raises if key doesn't exist
        response = s3.head_object(Bucket=_TestConfig.S3_BUCKET_NAME, Key=key)
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200


# ---------------------------------------------------------------------------
# get_image_bytes — round-trip
# ---------------------------------------------------------------------------

@mock_aws
class TestGetImageBytes:
    def test_roundtrip_bytes_identical(self, sample_image_bytes):
        """Req 1.3: Bytes downloaded from S3 are byte-for-byte identical to what was uploaded."""
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        key = "images/roundtrip.png"
        svc.upload_image(sample_image_bytes, key, "image/png")
        retrieved = svc.get_image_bytes(key)

        assert retrieved == sample_image_bytes

    def test_get_nonexistent_key_raises_storage_error(self):
        """Attempting to download a missing object must raise StorageError."""
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        with pytest.raises(StorageError):
            svc.get_image_bytes("images/does_not_exist.png")


# ---------------------------------------------------------------------------
# delete_image
# ---------------------------------------------------------------------------

@mock_aws
class TestDeleteImage:
    def test_delete_removes_object(self, sample_image_bytes):
        """Req 7.4: Object must not be retrievable after delete_image."""
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        key = "images/to_delete.png"
        svc.upload_image(sample_image_bytes, key, "image/png")
        svc.delete_image(key)

        # Attempting to retrieve the deleted object must now fail
        with pytest.raises(StorageError):
            svc.get_image_bytes(key)

    def test_delete_nonexistent_is_idempotent(self):
        """Deleting a key that doesn't exist must not raise an error."""
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        # Must not raise
        svc.delete_image("images/never_existed.png")


# ---------------------------------------------------------------------------
# list_objects
# ---------------------------------------------------------------------------

@mock_aws
class TestListObjects:
    def test_empty_bucket_returns_empty_list(self):
        """list_objects on an empty bucket returns []."""
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        result = svc.list_objects()
        assert result == []

    def test_returns_correct_key_and_size(self, sample_image_bytes):
        """list_objects returns dicts with 'key' and 'size' matching the uploaded object."""
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        key = "images/listed.png"
        svc.upload_image(sample_image_bytes, key, "image/png")

        objects = svc.list_objects()
        assert len(objects) == 1
        assert objects[0]["key"] == key
        assert objects[0]["size"] == len(sample_image_bytes)

    def test_multiple_uploads_all_listed(self, sample_image_bytes):
        """All uploaded keys appear in list_objects output."""
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        keys = ["images/a.png", "images/b.png", "images/c.png"]
        for k in keys:
            svc.upload_image(sample_image_bytes, k, "image/png")

        objects = svc.list_objects()
        listed_keys = {o["key"] for o in objects}
        assert set(keys) == listed_keys


# ---------------------------------------------------------------------------
# generate_presigned_url
# ---------------------------------------------------------------------------

@mock_aws
class TestGeneratePresignedUrl:
    def test_returns_string_url(self, sample_image_bytes):
        """generate_presigned_url must return a non-empty string."""
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        key = "images/presigned.png"
        svc.upload_image(sample_image_bytes, key, "image/png")

        url = svc.generate_presigned_url(key)
        assert isinstance(url, str)
        assert len(url) > 0

    def test_url_contains_bucket_or_key(self, sample_image_bytes):
        """The returned URL should reference either the bucket or the key."""
        svc = StorageService(config=_TestConfig)
        svc.ensure_bucket_exists()

        key = "images/url_check.png"
        svc.upload_image(sample_image_bytes, key, "image/png")

        url = svc.generate_presigned_url(key)
        # Either the key or the bucket name must appear somewhere in the URL
        assert _TestConfig.S3_BUCKET_NAME in url or key in url
