"""
services/image_processor.py — Image manipulation logic for Mini Cloud Image Studio.

Pure-function module that handles all image operations using Pillow and NumPy.
Does not interact with any cloud service.
"""

import os
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from config import AppConfig
from services.models import ImageProcessingError


# ---------------------------------------------------------------------------
# Validation & Loading
# ---------------------------------------------------------------------------

def validate_image(file_bytes: bytes, filename: str) -> tuple[bool, str]:
    """
    Validate image file format and size.

    Checks the file extension against AppConfig.SUPPORTED_FORMATS and the
    byte length against AppConfig.MAX_FILE_SIZE_BYTES.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        filename:   Original filename (used to extract the extension).

    Returns:
        (True, "")                   if the file is valid.
        (False, human-readable msg)  if the extension is unsupported or the
                                     file exceeds the size limit.
    """
    # --- Extension check ---
    ext = os.path.splitext(filename)[1].lstrip(".").lower()
    if ext not in AppConfig.SUPPORTED_FORMATS:
        supported = ", ".join(AppConfig.SUPPORTED_FORMATS)
        return False, (
            f"Format file tidak didukung: '.{ext}'. "
            f"Format yang diterima: {supported}."
        )

    # --- Size check ---
    if len(file_bytes) > AppConfig.MAX_FILE_SIZE_BYTES:
        size_mb = len(file_bytes) / (1024 * 1024)
        limit_mb = AppConfig.MAX_FILE_SIZE_BYTES / (1024 * 1024)
        return False, (
            f"Ukuran file ({size_mb:.1f} MB) melebihi batas maksimum "
            f"{limit_mb:.0f} MB."
        )

    return True, ""


def load_image(file_bytes: bytes) -> Image.Image:
    """
    Load raw bytes into a PIL Image object.

    Args:
        file_bytes: Raw bytes of the image file.

    Returns:
        A PIL Image object (mode may vary; caller should convert if needed).

    Raises:
        ImageProcessingError: If the bytes cannot be decoded as a known image
                              format (wraps PIL.UnidentifiedImageError).
    """
    try:
        image = Image.open(BytesIO(file_bytes))
        # Force-load pixel data so any decoding error surfaces here rather
        # than lazily later during processing.
        image.load()
        return image
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageProcessingError(
            "File tidak dapat dibaca sebagai gambar. "
            "Pastikan file tidak rusak dan formatnya didukung."
        ) from exc


def get_image_dimensions(image: Image.Image) -> tuple[int, int]:
    """
    Return the (width, height) of a PIL Image.

    Args:
        image: A PIL Image object.

    Returns:
        Tuple of (width_px, height_px).
    """
    return image.size  # PIL Image.size is already (width, height)


# ---------------------------------------------------------------------------
# Resize
# ---------------------------------------------------------------------------

def resize_image(
    image: Image.Image,
    width: int,
    height: int,
    maintain_aspect_ratio: bool = False,
) -> Image.Image:
    """
    Resize the image to the specified dimensions.

    Args:
        image:                 Source PIL Image.
        width:                 Target width in pixels.
        height:                Target height in pixels.
        maintain_aspect_ratio: If True, scale to fit within (width, height)
                               while preserving the original aspect ratio.
                               The result may be smaller than the target in
                               one dimension.

    Returns:
        Resized PIL Image.
    """
    if maintain_aspect_ratio:
        # thumbnail() modifies in-place and keeps aspect ratio
        result = image.copy()
        result.thumbnail((width, height), Image.LANCZOS)
        return result
    return image.resize((width, height), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Color Filters
# ---------------------------------------------------------------------------

def apply_grayscale(image: Image.Image) -> Image.Image:
    """
    Convert the image to grayscale and return it as an RGB image.

    Every resulting pixel satisfies r == g == b.
    """
    return image.convert("L").convert("RGB")


def apply_sepia(image: Image.Image) -> Image.Image:
    """
    Apply a sepia tone effect using a colour-matrix transformation.

    The sepia matrix maps each (r, g, b) input channel to output channels
    where r >= g >= b, giving the characteristic warm brown tone.

    Returns:
        RGB PIL Image.
    """
    rgb = image.convert("RGB")
    arr = np.array(rgb, dtype=np.float64)

    # Standard sepia transformation matrix (rows = R_out, G_out, B_out)
    r_out = arr[:, :, 0] * 0.393 + arr[:, :, 1] * 0.769 + arr[:, :, 2] * 0.189
    g_out = arr[:, :, 0] * 0.349 + arr[:, :, 1] * 0.686 + arr[:, :, 2] * 0.168
    b_out = arr[:, :, 0] * 0.272 + arr[:, :, 1] * 0.534 + arr[:, :, 2] * 0.131

    sepia = np.stack(
        [
            np.clip(r_out, 0, 255),
            np.clip(g_out, 0, 255),
            np.clip(b_out, 0, 255),
        ],
        axis=2,
    ).astype(np.uint8)

    return Image.fromarray(sepia, mode="RGB")


def apply_invert(image: Image.Image) -> Image.Image:
    """
    Invert all pixel channel values (photographic negative effect).

    Returns:
        RGB PIL Image with each channel value v replaced by 255 - v.
    """
    rgb = image.convert("RGB")
    return ImageOps.invert(rgb)


# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------

def apply_watermark(
    image: Image.Image,
    text: str,
    position: str,  # "bottom-left" | "bottom-right" | "top-left" | "top-right"
) -> Image.Image:
    """
    Overlay semi-transparent text onto the image without changing its size.

    Font size is proportional to the smallest image dimension (~4 %).
    The text is drawn in white with a thin black outline for legibility on
    both light and dark backgrounds.

    Args:
        image:    Source PIL Image.
        text:     Watermark string.
        position: One of "bottom-left", "bottom-right", "top-left", "top-right".

    Returns:
        RGB PIL Image of identical dimensions to the input.
    """
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    width, height = base.size
    font_size = max(12, int(min(width, height) * 0.04))

    # Use PIL default font (always available, no external file needed)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except (IOError, OSError):
        # Fallback to the built-in bitmap font
        font = ImageFont.load_default()

    # Measure text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    padding = max(8, int(min(width, height) * 0.02))

    if position == "bottom-right":
        x = width - text_w - padding
        y = height - text_h - padding
    elif position == "bottom-left":
        x = padding
        y = height - text_h - padding
    elif position == "top-right":
        x = width - text_w - padding
        y = padding
    else:  # "top-left" (default)
        x = padding
        y = padding

    # Outline (drawn at offsets of ±1 px)
    outline_color = (0, 0, 0, 180)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)

    # Main text
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 200))

    composite = Image.alpha_composite(base, overlay)
    return composite.convert("RGB")


# ---------------------------------------------------------------------------
# Format Conversion
# ---------------------------------------------------------------------------

def convert_format(
    image: Image.Image,
    output_format: str,  # "JPEG" | "PNG" | "WEBP"
    quality: int = 85,
) -> tuple[bytes, int]:
    """
    Encode the image to the specified format and return its bytes.

    Args:
        image:         Source PIL Image.
        output_format: Target format string ("JPEG", "PNG", "WEBP").
        quality:       Compression quality (1–95); ignored for PNG.

    Returns:
        (image_bytes, file_size_bytes) where file_size_bytes == len(image_bytes).
    """
    buf = BytesIO()
    fmt = output_format.upper()

    # JPEG does not support an alpha channel
    save_image = image.convert("RGB") if fmt == "JPEG" else image

    save_kwargs: dict = {"format": fmt}
    if fmt in ("JPEG", "WEBP"):
        save_kwargs["quality"] = quality

    save_image.save(buf, **save_kwargs)
    image_bytes = buf.getvalue()
    return image_bytes, len(image_bytes)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def apply_pipeline(
    image: Image.Image,
    resize_options: dict | None,
    color_filter: str | None,
    watermark_options: dict | None,
    output_format: str,
    quality: int,
) -> tuple[Image.Image, bytes, int]:
    """
    Apply the full manipulation pipeline in order:
    resize → color filter → watermark → convert format.

    Args:
        image:             Source PIL Image.
        resize_options:    Dict with keys "width", "height",
                           "maintain_aspect_ratio"; or None to skip.
        color_filter:      "grayscale" | "sepia" | "invert" | None.
        watermark_options: Dict with keys "text", "position"; or None to skip.
        output_format:     "JPEG" | "PNG" | "WEBP".
        quality:           Compression quality for JPEG / WebP.

    Returns:
        (final_image, image_bytes, file_size_bytes)
    """
    result = image.copy()

    # 1. Resize
    if resize_options:
        result = resize_image(
            result,
            resize_options["width"],
            resize_options["height"],
            resize_options.get("maintain_aspect_ratio", False),
        )

    # 2. Color filter
    if color_filter == "grayscale":
        result = apply_grayscale(result)
    elif color_filter == "sepia":
        result = apply_sepia(result)
    elif color_filter == "invert":
        result = apply_invert(result)

    # 3. Watermark
    if watermark_options:
        result = apply_watermark(
            result,
            watermark_options["text"],
            watermark_options.get("position", "bottom-right"),
        )

    # 4. Convert format
    image_bytes, file_size = convert_format(result, output_format, quality)

    return result, image_bytes, file_size
