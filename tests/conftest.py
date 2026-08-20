"""
tests/conftest.py — Shared pytest fixtures for Mini Cloud Image Studio.

This file is auto-loaded by pytest for all test modules under tests/.
It sets up AWS dummy credentials at module level (before any boto3 import),
and provides reusable fixtures for configuration, services, image bytes,
and metadata objects.
"""

import io
import os

# ---------------------------------------------------------------------------
# Dummy AWS credentials — MUST be set before any boto3 import to prevent
# accidental real-AWS calls.  moto intercepts all boto3 calls when its
# decorators/context managers are active.
# ---------------------------------------------------------------------------
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import pytest
from unittest.mock import MagicMock
from PIL import Image

from services.models import ImageMetadata


# ---------------------------------------------------------------------------
# Shared test configuration
# ---------------------------------------------------------------------------

class _TestConfig:
    """
    Minimal AppConfig-compatible class for use in tests.

    ENDPOINT_URL is None so that moto intercepts boto3 calls without
    requiring a running MinIO/LocalStack instance.
    """

    ENDPOINT_URL = None
    AWS_ACCESS_KEY = "testing"
    AWS_SECRET_KEY = "testing"
    AWS_REGION = "us-east-1"
    S3_BUCKET_NAME = "test-bucket"
    DYNAMODB_TABLE_NAME = "test-metadata"
    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024   # 10 MB
    SUPPORTED_FORMATS = ["jpg", "jpeg", "png", "webp", "bmp"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_config():
    """
    Return the shared test configuration class.

    Use this anywhere an AppConfig-compatible object is required.
    """
    return _TestConfig


@pytest.fixture(autouse=False)
def aws_credentials():
    """
    Ensure dummy AWS credentials are present in the environment.

    Applied on-demand (autouse=False).  Individual test modules that
    already set credentials at module level will still benefit from
    having this fixture available via explicit request.
    """
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def sample_image_bytes() -> bytes:
    """
    Return real PNG bytes for a small 10×10 solid-red image.

    Using genuine image bytes (not empty b"") lets tests exercise
    realistic upload/download and image-processing payloads.
    """
    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sample_image_metadata() -> ImageMetadata:
    """
    Return a fully-populated ImageMetadata instance.

    All fields are set to realistic values so fixtures can be used
    in DynamoDB round-trip tests, consistency checks, and UI tests
    without additional setup.
    """
    return ImageMetadata(
        image_id="550e8400-e29b-41d4-a716-446655440000",
        original_filename="foto_liburan.jpg",
        s3_key="images/550e8400_foto_liburan.png",
        file_format="PNG",
        file_size_bytes=204800,
        original_width=1920,
        original_height=1080,
        final_width=800,
        final_height=450,
        upload_timestamp="2024-01-15T10:30:00Z",
        manipulations_applied=["resize", "sepia", "watermark"],
        watermark_text="Uploaded via Mini Cloud Storage - 12345",
        color_filter="sepia",
        output_quality=None,
    )


@pytest.fixture
def mock_storage_service():
    """
    Return a MagicMock that mimics the StorageService interface.

    Pre-configured return values reflect happy-path defaults:
    - upload_image   → returns the s3_key argument unchanged
    - get_image_bytes → returns an empty bytes object
    - generate_presigned_url → returns a plausible URL string
    - list_objects   → returns an empty list
    - delete_image / ensure_bucket_exists → return None (implicit)

    Use this fixture in Streamlit page tests and any unit test that
    needs to isolate business logic from real S3 behaviour.
    """
    from services.storage_service import StorageService

    mock = MagicMock(spec=StorageService)
    mock.upload_image.side_effect = lambda image_bytes, s3_key, content_type: s3_key
    mock.get_image_bytes.return_value = b""
    mock.generate_presigned_url.return_value = (
        "http://localhost:4566/test-bucket/images/sample.png"
    )
    mock.list_objects.return_value = []
    mock.delete_image.return_value = None
    mock.ensure_bucket_exists.return_value = None
    return mock


@pytest.fixture
def mock_metadata_service():
    """
    Return a MagicMock that mimics the MetadataService interface.

    Pre-configured return values reflect happy-path defaults:
    - save_metadata / delete_metadata / update_metadata / ensure_table_exists → None
    - get_metadata   → None (item not found by default)
    - list_all_metadata → empty list

    Use this fixture in Streamlit page tests and any unit test that
    needs to isolate business logic from real DynamoDB behaviour.
    """
    from services.metadata_service import MetadataService

    mock = MagicMock(spec=MetadataService)
    mock.save_metadata.return_value = None
    mock.get_metadata.return_value = None
    mock.list_all_metadata.return_value = []
    mock.delete_metadata.return_value = None
    mock.update_metadata.return_value = None
    mock.ensure_table_exists.return_value = None
    return mock
