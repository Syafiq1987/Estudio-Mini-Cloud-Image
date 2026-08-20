"""
tests/unit/test_metadata_service.py — Unit tests for services/metadata_service.py

Uses moto's mock_aws to intercept all real boto3/DynamoDB calls.
Environment variables MUST be set before importing services to prevent
any accidental real-AWS calls at import time.

Covers:
  - ensure_table_exists: table is created, idempotent (call twice)
  - save_metadata + get_metadata: round-trip preserves all fields
  - get_metadata: returns None for non-existent image_id
  - list_all_metadata: returns all saved items
  - delete_metadata: item no longer retrievable after delete
  - update_metadata: specified fields are updated correctly
"""

import os

# Set dummy AWS credentials BEFORE any boto3/moto import so that moto
# intercepts all calls and no real-AWS request is ever attempted.
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

import pytest
from moto import mock_aws

from services.metadata_service import MetadataService
from services.models import ImageMetadata, MetadataError


# ---------------------------------------------------------------------------
# Shared test configuration
# ---------------------------------------------------------------------------

class _TestConfig:
    """Minimal AppConfig-compatible object for moto-patched DynamoDB."""
    ENDPOINT_URL = None
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
def aws_credentials():
    """Ensure dummy credentials are set."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def sample_metadata() -> ImageMetadata:
    """A fully-populated ImageMetadata instance for use in tests."""
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
def another_metadata() -> ImageMetadata:
    """A second distinct ImageMetadata for list/multi-item tests."""
    return ImageMetadata(
        image_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        original_filename="portrait.jpg",
        s3_key="images/aaaaaaaa_portrait.jpeg",
        file_format="JPEG",
        file_size_bytes=512000,
        original_width=800,
        original_height=600,
        final_width=400,
        final_height=300,
        upload_timestamp="2024-02-20T08:00:00Z",
        manipulations_applied=["grayscale"],
        watermark_text=None,
        color_filter="grayscale",
        output_quality=85,
    )


# ---------------------------------------------------------------------------
# ensure_table_exists
# ---------------------------------------------------------------------------

@mock_aws
class TestEnsureTableExists:
    def test_creates_table(self, aws_credentials):
        """Req 2.3: DynamoDB table is created when it does not exist."""
        import boto3
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        ddb = boto3.client(
            "dynamodb",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        tables = ddb.list_tables()["TableNames"]
        assert _TestConfig.DYNAMODB_TABLE_NAME in tables

    def test_idempotent_double_call(self, aws_credentials):
        """Calling ensure_table_exists twice must not raise."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()
        svc.ensure_table_exists()  # second call — should be a no-op

    def test_table_has_correct_key_schema(self, aws_credentials):
        """The created table must have image_id as its HASH (partition) key."""
        import boto3
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        ddb = boto3.client(
            "dynamodb",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        desc = ddb.describe_table(TableName=_TestConfig.DYNAMODB_TABLE_NAME)
        key_schema = desc["Table"]["KeySchema"]
        hash_key = next(k for k in key_schema if k["KeyType"] == "HASH")
        assert hash_key["AttributeName"] == "image_id"


# ---------------------------------------------------------------------------
# save_metadata + get_metadata round-trip
# ---------------------------------------------------------------------------

@mock_aws
class TestSaveAndGetMetadata:
    def test_roundtrip_all_fields(self, aws_credentials, sample_metadata):
        """Req 2.1, 2.2: save then get returns an ImageMetadata with identical fields."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(sample_metadata)
        retrieved = svc.get_metadata(sample_metadata.image_id)

        assert retrieved is not None
        assert retrieved.image_id == sample_metadata.image_id
        assert retrieved.original_filename == sample_metadata.original_filename
        assert retrieved.s3_key == sample_metadata.s3_key
        assert retrieved.file_format == sample_metadata.file_format
        assert retrieved.file_size_bytes == sample_metadata.file_size_bytes
        assert retrieved.original_width == sample_metadata.original_width
        assert retrieved.original_height == sample_metadata.original_height
        assert retrieved.final_width == sample_metadata.final_width
        assert retrieved.final_height == sample_metadata.final_height
        assert retrieved.upload_timestamp == sample_metadata.upload_timestamp
        assert retrieved.manipulations_applied == sample_metadata.manipulations_applied
        assert retrieved.watermark_text == sample_metadata.watermark_text
        assert retrieved.color_filter == sample_metadata.color_filter
        assert retrieved.output_quality == sample_metadata.output_quality

    def test_save_is_idempotent_overwrite(self, aws_credentials, sample_metadata):
        """Saving the same image_id twice overwrites the previous item."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(sample_metadata)

        updated = ImageMetadata(
            image_id=sample_metadata.image_id,
            original_filename="updated.jpg",
            s3_key="images/updated.jpg",
            file_format="JPEG",
            file_size_bytes=1024,
            original_width=100,
            original_height=100,
            final_width=50,
            final_height=50,
            upload_timestamp="2024-03-01T00:00:00Z",
            manipulations_applied=[],
            watermark_text=None,
            color_filter=None,
            output_quality=90,
        )
        svc.save_metadata(updated)

        retrieved = svc.get_metadata(sample_metadata.image_id)
        assert retrieved.original_filename == "updated.jpg"
        assert retrieved.output_quality == 90

    def test_roundtrip_with_output_quality(self, aws_credentials, another_metadata):
        """output_quality (integer) must survive the DynamoDB round-trip correctly."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(another_metadata)
        retrieved = svc.get_metadata(another_metadata.image_id)

        assert retrieved.output_quality == another_metadata.output_quality
        assert isinstance(retrieved.output_quality, int)


# ---------------------------------------------------------------------------
# get_metadata — non-existent item
# ---------------------------------------------------------------------------

@mock_aws
class TestGetMetadataNotFound:
    def test_returns_none_for_missing_id(self, aws_credentials):
        """get_metadata must return None when the image_id does not exist."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        result = svc.get_metadata("non-existent-uuid-1234")
        assert result is None


# ---------------------------------------------------------------------------
# list_all_metadata
# ---------------------------------------------------------------------------

@mock_aws
class TestListAllMetadata:
    def test_empty_table_returns_empty_list(self, aws_credentials):
        """list_all_metadata on an empty table returns []."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        result = svc.list_all_metadata()
        assert result == []

    def test_single_item_listed(self, aws_credentials, sample_metadata):
        """After saving one item, list_all_metadata returns a list with that item."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(sample_metadata)
        result = svc.list_all_metadata()

        assert len(result) == 1
        assert result[0].image_id == sample_metadata.image_id

    def test_multiple_items_all_listed(self, aws_credentials, sample_metadata, another_metadata):
        """All saved items appear in list_all_metadata results."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(sample_metadata)
        svc.save_metadata(another_metadata)

        result = svc.list_all_metadata()
        listed_ids = {m.image_id for m in result}
        assert sample_metadata.image_id in listed_ids
        assert another_metadata.image_id in listed_ids

    def test_returns_list_of_image_metadata_objects(self, aws_credentials, sample_metadata):
        """list_all_metadata returns ImageMetadata objects, not raw dicts."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(sample_metadata)
        result = svc.list_all_metadata()

        assert all(isinstance(m, ImageMetadata) for m in result)


# ---------------------------------------------------------------------------
# delete_metadata
# ---------------------------------------------------------------------------

@mock_aws
class TestDeleteMetadata:
    def test_delete_makes_item_unretrievable(self, aws_credentials, sample_metadata):
        """Req 7.4: After delete_metadata, get_metadata must return None."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(sample_metadata)
        svc.delete_metadata(sample_metadata.image_id)

        result = svc.get_metadata(sample_metadata.image_id)
        assert result is None

    def test_delete_removes_from_list(self, aws_credentials, sample_metadata, another_metadata):
        """Deleted item must not appear in list_all_metadata results."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(sample_metadata)
        svc.save_metadata(another_metadata)
        svc.delete_metadata(sample_metadata.image_id)

        result = svc.list_all_metadata()
        listed_ids = {m.image_id for m in result}
        assert sample_metadata.image_id not in listed_ids
        assert another_metadata.image_id in listed_ids

    def test_delete_nonexistent_is_idempotent(self, aws_credentials):
        """Deleting an image_id that doesn't exist must not raise an error."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        # Must not raise
        svc.delete_metadata("does-not-exist-uuid")


# ---------------------------------------------------------------------------
# update_metadata
# ---------------------------------------------------------------------------

@mock_aws
class TestUpdateMetadata:
    def test_update_single_field(self, aws_credentials, sample_metadata):
        """update_metadata correctly updates a single field."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(sample_metadata)
        svc.update_metadata(sample_metadata.image_id, {"file_size_bytes": 999999})

        retrieved = svc.get_metadata(sample_metadata.image_id)
        assert retrieved.file_size_bytes == 999999

    def test_update_multiple_fields(self, aws_credentials, sample_metadata):
        """update_metadata correctly updates multiple fields at once."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(sample_metadata)
        svc.update_metadata(
            sample_metadata.image_id,
            {"color_filter": "invert", "output_quality": 75},
        )

        retrieved = svc.get_metadata(sample_metadata.image_id)
        assert retrieved.color_filter == "invert"
        assert retrieved.output_quality == 75

    def test_update_does_not_affect_other_fields(self, aws_credentials, sample_metadata):
        """Updating one field must leave other fields unchanged."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(sample_metadata)
        svc.update_metadata(sample_metadata.image_id, {"final_width": 1280})

        retrieved = svc.get_metadata(sample_metadata.image_id)
        assert retrieved.final_width == 1280
        # Other fields should be untouched
        assert retrieved.original_filename == sample_metadata.original_filename
        assert retrieved.file_format == sample_metadata.file_format

    def test_update_empty_dict_raises_metadata_error(self, aws_credentials, sample_metadata):
        """update_metadata with an empty dict must raise MetadataError."""
        svc = MetadataService(config=_TestConfig)
        svc.ensure_table_exists()

        svc.save_metadata(sample_metadata)
        with pytest.raises(MetadataError):
            svc.update_metadata(sample_metadata.image_id, {})
