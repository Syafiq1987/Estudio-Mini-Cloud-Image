"""
Data models and custom exceptions for Mini Cloud Image Studio.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class MiniCloudError(Exception):
    """Base exception for all application errors."""


class StorageError(MiniCloudError):
    """Raised when an S3 operation fails."""


class MetadataError(MiniCloudError):
    """Raised when a DynamoDB operation fails."""


class ImageProcessingError(MiniCloudError):
    """Raised when an image manipulation operation fails."""


class ValidationError(MiniCloudError):
    """Raised when user input fails validation."""


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ImageMetadata:
    """
    Represents a single stored image entity.

    Used as a transfer object between application layers and as the
    canonical representation of a DynamoDB item.
    """

    # Primary identifiers
    image_id: str                          # UUID v4, DynamoDB partition key
    original_filename: str                 # Original filename supplied by the user
    s3_key: str                            # Object key in the S3 bucket

    # Format & size
    file_format: str                       # Output format: "JPEG" | "PNG" | "WEBP"
    file_size_bytes: int                   # Size of the processed file in bytes

    # Dimensions
    original_width: int                    # Width of the original image (px)
    original_height: int                   # Height of the original image (px)
    final_width: int                       # Width of the processed image (px)
    final_height: int                      # Height of the processed image (px)

    # Audit
    upload_timestamp: str                  # ISO 8601, e.g. "2024-01-15T10:30:00Z"

    # Manipulations
    manipulations_applied: list[str] = field(default_factory=list)
    # e.g. ["resize", "sepia", "watermark"]

    # Optional fields
    watermark_text: Optional[str] = None   # Watermark text, if applied
    color_filter: Optional[str] = None     # "grayscale" | "sepia" | "invert" | None
    output_quality: Optional[int] = None   # Compression quality for JPEG / WebP
