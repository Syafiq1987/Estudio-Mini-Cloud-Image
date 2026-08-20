"""
tests/unit/test_image_processor.py — Unit tests for services/image_processor.py

Covers:
  - validate_image: valid file, unsupported extensions, file too large
  - load_image: valid bytes, corrupted bytes
  - get_image_dimensions: correct (width, height) tuple
  - resize_image: exact dimensions, aspect-ratio preservation, boundary values
  - apply_grayscale: mode RGB, r==g==b invariant, dimension preservation
  - apply_sepia: mode RGB, r>=g>=b invariant, dimension preservation
  - apply_invert: mode RGB, pixel negation, involution, dimension preservation
  - apply_watermark: mode RGB, all 4 positions, dimension preservation,
                     pixel visibility, source immutability, various text inputs
"""

import io

import pytest
from PIL import Image

from services.image_processor import (
    apply_grayscale,
    apply_invert,
    apply_sepia,
    apply_watermark,
    get_image_dimensions,
    load_image,
    resize_image,
    validate_image,
)
from services.models import ImageProcessingError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_image_bytes(width: int = 100, height: int = 80, fmt: str = "PNG") -> bytes:
    """Create real, valid image bytes using PIL."""
    img = Image.new("RGB", (width, height), color=(123, 45, 67))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# validate_image — format checks
# ---------------------------------------------------------------------------

class TestValidateImageFormat:
    """Req 1.4: Validate file extension against SUPPORTED_FORMATS."""

    @pytest.mark.parametrize("filename", [
        "photo.jpg",
        "photo.jpeg",
        "image.PNG",       # case-insensitive
        "logo.webp",
        "scan.bmp",
        "UPPERCASE.JPEG",  # fully uppercase
    ])
    def test_supported_formats_accepted(self, filename):
        """Supported extensions with minimal bytes should pass the format check."""
        # Use 1-byte payload — format validation is extension-only
        is_valid, msg = validate_image(b"x", filename)
        assert is_valid is True
        assert msg == ""

    @pytest.mark.parametrize("filename", [
        "animation.gif",
        "document.tiff",
        "vector.svg",
        "photo.heic",
        "archive.zip",
        "noextension",      # no dot at all
        "tricky.jpg.exe",   # double extension — final ext is .exe
    ])
    def test_unsupported_formats_rejected(self, filename):
        """Unsupported extensions must return (False, non-empty message)."""
        is_valid, msg = validate_image(b"x", filename)
        assert is_valid is False
        assert len(msg) > 0, "Error message must not be empty"
        # The message should mention format
        assert "format" in msg.lower() or "didukung" in msg.lower()


# ---------------------------------------------------------------------------
# validate_image — size checks
# ---------------------------------------------------------------------------

class TestValidateImageSize:
    """Req 1.5: Reject files larger than 10 MB."""

    MAX = 10 * 1024 * 1024  # 10 MB in bytes

    def test_exactly_at_limit_is_valid(self):
        """A file exactly at 10 MB should pass."""
        data = b"x" * self.MAX
        is_valid, msg = validate_image(data, "photo.jpg")
        assert is_valid is True
        assert msg == ""

    def test_one_byte_over_limit_is_rejected(self):
        """One byte above the limit must fail."""
        data = b"x" * (self.MAX + 1)
        is_valid, msg = validate_image(data, "photo.jpg")
        assert is_valid is False
        assert len(msg) > 0

    def test_clearly_over_limit_is_rejected(self):
        """Clearly oversized file must fail."""
        data = b"x" * (self.MAX + 1024 * 1024)  # 11 MB
        is_valid, msg = validate_image(data, "image.png")
        assert is_valid is False

    def test_small_valid_file(self):
        """Small files well under the limit must pass (size-wise)."""
        data = b"x" * 1024  # 1 KB
        is_valid, msg = validate_image(data, "photo.jpg")
        assert is_valid is True
        assert msg == ""

    def test_empty_file_is_valid_format_and_size(self):
        """0-byte file passes format + size checks (content validity is separate)."""
        is_valid, msg = validate_image(b"", "photo.jpg")
        assert is_valid is True
        assert msg == ""


# ---------------------------------------------------------------------------
# validate_image — combined checks
# ---------------------------------------------------------------------------

class TestValidateImageCombined:
    """Both format and size rules apply independently."""

    def test_bad_format_and_large_file_returns_format_error(self):
        """When both format and size fail, the format check fires first."""
        data = b"x" * (10 * 1024 * 1024 + 1)
        is_valid, msg = validate_image(data, "photo.gif")
        assert is_valid is False
        # Extension error should be reported (it is checked first)
        assert "format" in msg.lower() or "didukung" in msg.lower()


# ---------------------------------------------------------------------------
# load_image
# ---------------------------------------------------------------------------

class TestLoadImage:
    """Req 1.7: load_image must decode valid images and raise on corrupted ones."""

    def test_valid_png_bytes_loads_successfully(self):
        """Valid PNG bytes should return a PIL Image object."""
        data = _make_image_bytes(fmt="PNG")
        image = load_image(data)
        assert isinstance(image, Image.Image)

    def test_valid_jpeg_bytes_loads_successfully(self):
        """Valid JPEG bytes should return a PIL Image object."""
        data = _make_image_bytes(fmt="JPEG")
        image = load_image(data)
        assert isinstance(image, Image.Image)

    def test_corrupted_bytes_raise_image_processing_error(self):
        """Garbage bytes must raise ImageProcessingError, not PIL's own error."""
        corrupted = b"\x00\x01\x02\x03 this is not an image"
        with pytest.raises(ImageProcessingError):
            load_image(corrupted)

    def test_empty_bytes_raise_image_processing_error(self):
        """Empty bytes must raise ImageProcessingError."""
        with pytest.raises(ImageProcessingError):
            load_image(b"")

    def test_partial_bytes_raise_image_processing_error(self):
        """Truncated image data must raise ImageProcessingError."""
        valid_data = _make_image_bytes(fmt="PNG")
        truncated = valid_data[:50]  # cut the file short
        with pytest.raises(ImageProcessingError):
            load_image(truncated)


# ---------------------------------------------------------------------------
# get_image_dimensions
# ---------------------------------------------------------------------------

class TestGetImageDimensions:
    """get_image_dimensions must return (width, height) in the correct order."""

    def test_returns_correct_dimensions(self):
        """Dimensions must match what was used to create the image."""
        img = Image.new("RGB", (320, 240))
        w, h = get_image_dimensions(img)
        assert w == 320
        assert h == 240

    def test_width_and_height_are_not_swapped(self):
        """Non-square image ensures (w, h) are not accidentally transposed."""
        img = Image.new("RGB", (800, 100))
        w, h = get_image_dimensions(img)
        assert w == 800
        assert h == 100

    def test_square_image(self):
        """Square image — both dimensions must be equal."""
        img = Image.new("RGB", (512, 512))
        w, h = get_image_dimensions(img)
        assert w == h == 512

    def test_single_pixel_image(self):
        """Edge case: 1×1 image."""
        img = Image.new("RGB", (1, 1))
        w, h = get_image_dimensions(img)
        assert w == 1
        assert h == 1

    def test_dimensions_from_loaded_image(self):
        """Dimensions should survive a PNG encode/decode round-trip via load_image."""
        original = Image.new("RGB", (200, 150), color=(0, 128, 255))
        buf = io.BytesIO()
        original.save(buf, format="PNG")
        loaded = load_image(buf.getvalue())
        w, h = get_image_dimensions(loaded)
        assert w == 200
        assert h == 150


# ---------------------------------------------------------------------------
# resize_image
# ---------------------------------------------------------------------------

class TestResizeImageExact:
    """Req 3.2, 3.3, 3.6: resize_image without aspect ratio must yield exact dimensions."""

    @pytest.mark.parametrize("target_w, target_h", [
        (200, 100),
        (800, 600),
        (50,  50),    # minimum boundary
        (2000, 2000), # maximum boundary
        (50,  2000),  # extreme aspect ratio
        (2000, 50),   # extreme aspect ratio (inverted)
    ])
    def test_exact_dimensions(self, target_w, target_h):
        """Result size must equal (target_w, target_h) exactly."""
        img = Image.new("RGB", (640, 480))
        result = resize_image(img, target_w, target_h, maintain_aspect_ratio=False)
        assert result.size == (target_w, target_h)

    def test_does_not_mutate_original(self):
        """resize_image must not modify the source image."""
        img = Image.new("RGB", (300, 200))
        _ = resize_image(img, 100, 100, maintain_aspect_ratio=False)
        assert img.size == (300, 200)

    def test_returns_new_object(self):
        """resize_image must return a new Image, not the same object."""
        img = Image.new("RGB", (300, 200))
        result = resize_image(img, 150, 100, maintain_aspect_ratio=False)
        assert result is not img

    def test_non_square_target(self):
        """Landscape source → portrait target must work without swapping axes."""
        img = Image.new("RGB", (1920, 1080))
        result = resize_image(img, 100, 500, maintain_aspect_ratio=False)
        assert result.size == (100, 500)

    def test_upscale_works(self):
        """Resizing a small image to a larger size must succeed."""
        img = Image.new("RGB", (50, 50))
        result = resize_image(img, 2000, 2000, maintain_aspect_ratio=False)
        assert result.size == (2000, 2000)

    def test_downscale_works(self):
        """Resizing a large image to a smaller size must succeed."""
        img = Image.new("RGB", (2000, 2000))
        result = resize_image(img, 50, 50, maintain_aspect_ratio=False)
        assert result.size == (50, 50)


class TestResizeImageAspectRatio:
    """Req 3.5: When maintain_aspect_ratio=True, the ratio must be preserved."""

    TOLERANCE = 0.02  # max acceptable deviation

    def _aspect_ratio(self, image: Image.Image) -> float:
        w, h = image.size
        return w / h

    def test_landscape_fits_within_bounds(self):
        """Landscape image: result must not exceed the target box."""
        img = Image.new("RGB", (1600, 900))
        result = resize_image(img, 800, 600, maintain_aspect_ratio=True)
        w, h = result.size
        assert w <= 800
        assert h <= 600

    def test_portrait_fits_within_bounds(self):
        """Portrait image: result must not exceed the target box."""
        img = Image.new("RGB", (400, 800))
        result = resize_image(img, 600, 400, maintain_aspect_ratio=True)
        w, h = result.size
        assert w <= 600
        assert h <= 400

    def test_aspect_ratio_preserved_landscape(self):
        """Aspect ratio must be within tolerance after resize."""
        img = Image.new("RGB", (800, 400))  # 2:1
        result = resize_image(img, 300, 300, maintain_aspect_ratio=True)
        original_ratio = self._aspect_ratio(img)
        result_ratio = self._aspect_ratio(result)
        assert abs(result_ratio - original_ratio) <= self.TOLERANCE

    def test_aspect_ratio_preserved_portrait(self):
        """Portrait aspect ratio must survive resize."""
        img = Image.new("RGB", (300, 900))  # 1:3
        result = resize_image(img, 200, 700, maintain_aspect_ratio=True)
        original_ratio = self._aspect_ratio(img)
        result_ratio = self._aspect_ratio(result)
        assert abs(result_ratio - original_ratio) <= self.TOLERANCE

    def test_square_image_remains_square(self):
        """Square image should stay square after aspect-ratio resize."""
        img = Image.new("RGB", (500, 500))
        result = resize_image(img, 200, 200, maintain_aspect_ratio=True)
        w, h = result.size
        assert w == h

    def test_does_not_upscale_beyond_target(self):
        """thumbnail() must never produce a result larger than the target box."""
        img = Image.new("RGB", (100, 100))  # small image
        result = resize_image(img, 500, 500, maintain_aspect_ratio=True)
        w, h = result.size
        # PIL thumbnail() does not upscale — result stays at or below original size
        assert w <= 500
        assert h <= 500

    def test_does_not_mutate_original_with_aspect_ratio(self):
        """Source image must remain unchanged when maintain_aspect_ratio=True."""
        img = Image.new("RGB", (640, 480))
        _ = resize_image(img, 320, 240, maintain_aspect_ratio=True)
        assert img.size == (640, 480)


# ---------------------------------------------------------------------------
# Helpers (color filter tests)
# ---------------------------------------------------------------------------

def _make_rgb_image(width: int = 60, height: int = 40, color=(123, 45, 67)) -> Image.Image:
    """Create a solid-color RGB image."""
    return Image.new("RGB", (width, height), color=color)


def _make_rgba_image(width: int = 60, height: int = 40) -> Image.Image:
    """Create an RGBA image to test mode-conversion handling."""
    return Image.new("RGBA", (width, height), color=(100, 150, 200, 128))


def _make_grayscale_image(width: int = 60, height: int = 40) -> Image.Image:
    """Create a grayscale ('L' mode) image."""
    return Image.new("L", (width, height), color=128)


# ---------------------------------------------------------------------------
# apply_grayscale
# ---------------------------------------------------------------------------

class TestApplyGrayscale:
    """Req 4.2: apply_grayscale must return mode RGB with r==g==b for every pixel."""

    def test_returns_rgb_mode(self):
        """Result must be mode RGB."""
        result = apply_grayscale(_make_rgb_image())
        assert result.mode == "RGB"

    def test_all_pixels_have_equal_channels(self):
        """Every pixel in a grayscale result must satisfy r == g == b."""
        img = Image.new("RGB", (20, 20))
        # Colour gradient to exercise many input values
        for y in range(20):
            for x in range(20):
                img.putpixel((x, y), (x * 12, y * 12, (x + y) * 6 % 256))
        result = apply_grayscale(img)
        for r, g, b in result.getdata():
            assert r == g == b, f"Expected r==g==b but got ({r},{g},{b})"

    def test_preserves_dimensions(self):
        """Grayscale must not change image dimensions."""
        img = _make_rgb_image(80, 50)
        result = apply_grayscale(img)
        assert result.size == (80, 50)

    def test_accepts_rgba_input(self):
        """apply_grayscale must handle RGBA input without raising an exception."""
        img = _make_rgba_image()
        result = apply_grayscale(img)
        assert result.mode == "RGB"
        assert result.size == img.size

    def test_accepts_l_mode_input(self):
        """apply_grayscale must handle L-mode input gracefully."""
        img = _make_grayscale_image()
        result = apply_grayscale(img)
        assert result.mode == "RGB"

    def test_pure_white_stays_white(self):
        """Pure white (255,255,255) must remain (255,255,255) after grayscale."""
        img = Image.new("RGB", (1, 1), color=(255, 255, 255))
        result = apply_grayscale(img)
        assert result.getpixel((0, 0)) == (255, 255, 255)

    def test_pure_black_stays_black(self):
        """Pure black (0,0,0) must remain (0,0,0) after grayscale."""
        img = Image.new("RGB", (1, 1), color=(0, 0, 0))
        result = apply_grayscale(img)
        assert result.getpixel((0, 0)) == (0, 0, 0)

    def test_does_not_mutate_source(self):
        """Source image must be unchanged after apply_grayscale."""
        img = _make_rgb_image(color=(200, 100, 50))
        original_pixel = img.getpixel((0, 0))
        apply_grayscale(img)
        assert img.getpixel((0, 0)) == original_pixel


# ---------------------------------------------------------------------------
# apply_sepia
# ---------------------------------------------------------------------------

class TestApplySepia:
    """Req 4.3: apply_sepia must return mode RGB with r>=g>=b (warm tone) for every pixel."""

    def test_returns_rgb_mode(self):
        """Result must be mode RGB."""
        result = apply_sepia(_make_rgb_image())
        assert result.mode == "RGB"

    def test_warm_tone_invariant_r_ge_g_ge_b(self):
        """Every pixel must satisfy r >= g >= b after sepia transformation."""
        # Use a variety of pixel colours
        img = Image.new("RGB", (16, 16))
        for y in range(16):
            for x in range(16):
                img.putpixel((x, y), (x * 16, y * 16, ((x + y) * 8) % 256))
        result = apply_sepia(img)
        for r, g, b in result.getdata():
            assert r >= g, f"Expected r>=g but got r={r}, g={g}"
            assert g >= b, f"Expected g>=b but got g={g}, b={b}"

    def test_preserves_dimensions(self):
        """Sepia must not change image dimensions."""
        img = _make_rgb_image(120, 80)
        result = apply_sepia(img)
        assert result.size == (120, 80)

    def test_accepts_rgba_input(self):
        """apply_sepia must handle RGBA input without raising."""
        img = _make_rgba_image()
        result = apply_sepia(img)
        assert result.mode == "RGB"
        assert result.size == img.size

    def test_accepts_l_mode_input(self):
        """apply_sepia must handle L-mode input gracefully."""
        img = _make_grayscale_image()
        result = apply_sepia(img)
        assert result.mode == "RGB"

    def test_black_input_produces_black_output(self):
        """Pure black input must produce (0, 0, 0) output."""
        img = Image.new("RGB", (1, 1), color=(0, 0, 0))
        r, g, b = apply_sepia(img).getpixel((0, 0))
        assert (r, g, b) == (0, 0, 0)

    def test_warm_tone_on_white_input(self):
        """White input should produce a warm (reddish) output satisfying r>=g>=b."""
        img = Image.new("RGB", (1, 1), color=(255, 255, 255))
        r, g, b = apply_sepia(img).getpixel((0, 0))
        assert r >= g >= b

    def test_does_not_mutate_source(self):
        """Source image must be unchanged after apply_sepia."""
        img = _make_rgb_image(color=(80, 160, 240))
        original_pixel = img.getpixel((0, 0))
        apply_sepia(img)
        assert img.getpixel((0, 0)) == original_pixel


# ---------------------------------------------------------------------------
# apply_invert
# ---------------------------------------------------------------------------

class TestApplyInvert:
    """Req 4.4: apply_invert must return mode RGB, negate each channel, and be an involution."""

    def test_returns_rgb_mode(self):
        """Result must be mode RGB."""
        result = apply_invert(_make_rgb_image())
        assert result.mode == "RGB"

    def test_preserves_dimensions(self):
        """Invert must not change image dimensions."""
        img = _make_rgb_image(100, 75)
        result = apply_invert(img)
        assert result.size == (100, 75)

    def test_pixel_values_are_negated(self):
        """Each channel v must become 255 - v."""
        img = Image.new("RGB", (1, 1), color=(100, 150, 200))
        result = apply_invert(img)
        r, g, b = result.getpixel((0, 0))
        assert (r, g, b) == (155, 105, 55)

    def test_black_becomes_white(self):
        """Pure black (0,0,0) must become pure white (255,255,255)."""
        img = Image.new("RGB", (1, 1), color=(0, 0, 0))
        result = apply_invert(img)
        assert result.getpixel((0, 0)) == (255, 255, 255)

    def test_white_becomes_black(self):
        """Pure white (255,255,255) must become pure black (0,0,0)."""
        img = Image.new("RGB", (1, 1), color=(255, 255, 255))
        result = apply_invert(img)
        assert result.getpixel((0, 0)) == (0, 0, 0)

    def test_invert_is_not_identity(self):
        """Inverting a non-neutral image must change the pixel values."""
        img = Image.new("RGB", (10, 10), color=(100, 100, 100))
        result = apply_invert(img)
        assert list(result.getdata()) != list(img.getdata())

    def test_involution_round_trip(self):
        """Applying invert twice must return the exact original pixel data."""
        img = Image.new("RGB", (20, 20))
        for y in range(20):
            for x in range(20):
                img.putpixel((x, y), (x * 12, y * 10, (x * y) % 256))
        original_pixels = list(img.getdata())
        double_inverted = apply_invert(apply_invert(img))
        assert list(double_inverted.getdata()) == original_pixels

    def test_accepts_rgba_input(self):
        """apply_invert must handle RGBA input without raising."""
        img = _make_rgba_image()
        result = apply_invert(img)
        assert result.mode == "RGB"
        assert result.size == img.size

    def test_accepts_l_mode_input(self):
        """apply_invert must handle L-mode input gracefully."""
        img = _make_grayscale_image()
        result = apply_invert(img)
        assert result.mode == "RGB"

    def test_does_not_mutate_source(self):
        """Source image must be unchanged after apply_invert."""
        img = _make_rgb_image(color=(30, 60, 90))
        original_pixel = img.getpixel((0, 0))
        apply_invert(img)
        assert img.getpixel((0, 0)) == original_pixel


# ---------------------------------------------------------------------------
# apply_watermark
# ---------------------------------------------------------------------------

class TestApplyWatermark:
    """
    Req 5.2, 5.3, 5.4, 5.5: apply_watermark must add semi-transparent text
    at the chosen position without altering image dimensions or mode.
    """

    POSITIONS = ["bottom-left", "bottom-right", "top-left", "top-right"]

    # --- Return type and mode ---

    def test_returns_rgb_mode(self):
        """Result must be mode RGB. Req 5.4"""
        img = Image.new("RGB", (400, 300), color=(200, 200, 200))
        result = apply_watermark(img, "Test", "bottom-right")
        assert result.mode == "RGB"

    def test_returns_pil_image(self):
        """apply_watermark must return a PIL Image instance."""
        img = Image.new("RGB", (400, 300), color=(100, 150, 200))
        result = apply_watermark(img, "Watermark", "top-left")
        assert isinstance(result, Image.Image)

    # --- All 4 positions work without raising ---

    @pytest.mark.parametrize("position", ["bottom-left", "bottom-right", "top-left", "top-right"])
    def test_all_positions_do_not_raise(self, position):
        """Every valid position string must succeed without raising. Req 5.3"""
        img = Image.new("RGB", (500, 400), color=(128, 128, 128))
        # Should not raise any exception
        result = apply_watermark(img, "Sample Text", position)
        assert result is not None

    # --- Dimension preservation ---

    @pytest.mark.parametrize("position", ["bottom-left", "bottom-right", "top-left", "top-right"])
    def test_all_positions_preserve_dimensions(self, position):
        """Result dimensions must exactly equal input dimensions for all positions. Req 5.4"""
        img = Image.new("RGB", (640, 480), color=(255, 255, 255))
        result = apply_watermark(img, "Watermark Text", position)
        assert result.size == (640, 480), (
            f"Position '{position}': expected (640, 480), got {result.size}"
        )

    def test_small_image_preserves_dimensions(self):
        """Watermark on a small image must still preserve dimensions."""
        img = Image.new("RGB", (100, 80), color=(50, 100, 150))
        result = apply_watermark(img, "Small", "top-right")
        assert result.size == (100, 80)

    def test_large_image_preserves_dimensions(self):
        """Watermark on a large image must still preserve dimensions."""
        img = Image.new("RGB", (1920, 1080), color=(30, 30, 30))
        result = apply_watermark(img, "Large Image Watermark", "bottom-left")
        assert result.size == (1920, 1080)

    def test_non_square_image_preserves_dimensions(self):
        """Wide (non-square) image must keep exact (width, height) after watermark."""
        img = Image.new("RGB", (800, 200), color=(200, 100, 50))
        result = apply_watermark(img, "Banner", "bottom-right")
        assert result.size == (800, 200)

    # --- Various text inputs ---

    def test_empty_string_does_not_raise(self):
        """Empty watermark text must not cause an exception."""
        img = Image.new("RGB", (400, 300), color=(100, 100, 100))
        result = apply_watermark(img, "", "bottom-left")
        assert result.size == (400, 300)
        assert result.mode == "RGB"

    def test_long_text_does_not_raise(self):
        """A long watermark string must be handled gracefully. Req 5.2"""
        long_text = "Uploaded via Mini Cloud Image Studio - 12345678901234567890"
        img = Image.new("RGB", (800, 600), color=(80, 80, 80))
        result = apply_watermark(img, long_text, "bottom-right")
        assert result.size == (800, 600)

    def test_special_characters_in_text(self):
        """Special characters (unicode, punctuation) must not raise. Req 5.2"""
        special_texts = [
            "© 2024 Studio",
            "Foto #1 — Liburan",
            "Tést wätérmärk",
            "日本語テスト",
        ]
        img = Image.new("RGB", (400, 300), color=(150, 150, 150))
        for text in special_texts:
            result = apply_watermark(img, text, "top-left")
            assert result.size == (400, 300), f"Failed for text: {text!r}"

    def test_single_character_text(self):
        """A single character watermark must work correctly."""
        img = Image.new("RGB", (200, 200), color=(200, 200, 200))
        result = apply_watermark(img, "X", "top-right")
        assert result.size == (200, 200)
        assert result.mode == "RGB"

    # --- Watermark is actually visible (pixels changed) ---

    def test_watermark_changes_pixels_bottom_right(self):
        """Watermark text must visibly alter pixels; result != original. Req 5.5"""
        # Use a uniform solid-color image so any pixel drawn stands out
        img = Image.new("RGB", (400, 300), color=(128, 128, 128))
        result = apply_watermark(img, "WATERMARK", "bottom-right")
        assert list(result.getdata()) != list(img.getdata()), (
            "Watermark should have changed at least some pixels"
        )

    def test_watermark_changes_pixels_all_positions(self):
        """For each position, the watermark must actually modify the image. Req 5.5"""
        for position in self.POSITIONS:
            img = Image.new("RGB", (400, 300), color=(100, 100, 100))
            result = apply_watermark(img, "VISIBLE", position)
            assert list(result.getdata()) != list(img.getdata()), (
                f"Position '{position}' should have changed pixels"
            )

    # --- Source image not mutated ---

    def test_does_not_mutate_source_image(self):
        """apply_watermark must not alter the original image. Req 5.4"""
        original_color = (77, 133, 200)
        img = Image.new("RGB", (400, 300), color=original_color)
        original_pixels = list(img.getdata())
        apply_watermark(img, "Test Watermark", "top-left")
        assert list(img.getdata()) == original_pixels, (
            "Source image was mutated by apply_watermark"
        )

    def test_returns_new_object(self):
        """apply_watermark must return a new Image object, not the input."""
        img = Image.new("RGB", (400, 300), color=(200, 200, 200))
        result = apply_watermark(img, "Test", "bottom-left")
        assert result is not img

    # --- RGBA input handling ---

    def test_accepts_rgba_input(self):
        """apply_watermark should handle RGBA input and return RGB. Req 5.4"""
        img = Image.new("RGBA", (400, 300), color=(100, 150, 200, 128))
        result = apply_watermark(img, "RGBA Input", "bottom-right")
        assert result.mode == "RGB"
        assert result.size == (400, 300)

    def test_accepts_l_mode_input(self):
        """apply_watermark should handle grayscale (L mode) input gracefully."""
        img = Image.new("L", (400, 300), color=128)
        result = apply_watermark(img, "Grayscale", "top-right")
        assert result.mode == "RGB"
        assert result.size == (400, 300)


# ---------------------------------------------------------------------------
# Imports needed for convert_format and apply_pipeline tests
# ---------------------------------------------------------------------------

from io import BytesIO as _BytesIO

from services.image_processor import apply_pipeline, convert_format


# ---------------------------------------------------------------------------
# convert_format
# ---------------------------------------------------------------------------

class TestConvertFormat:
    """
    Req 6.2, 6.3, 6.4, 6.5:
    convert_format must produce non-empty, reload-able bytes and report the
    size accurately (file_size_bytes == len(image_bytes)).
    """

    def _base_image(
        self,
        width: int = 80,
        height: int = 60,
        color: tuple = (100, 150, 200),
    ) -> Image.Image:
        """Return a solid-color RGB image."""
        return Image.new("RGB", (width, height), color=color)

    # --- JPEG ---

    def test_jpeg_returns_non_empty_bytes(self):
        """JPEG conversion must return a non-empty bytes object. Req 6.2"""
        img_bytes, size = convert_format(self._base_image(), "JPEG")
        assert isinstance(img_bytes, bytes)
        assert len(img_bytes) > 0

    def test_jpeg_bytes_are_reloadable(self):
        """JPEG bytes must be re-openable as a valid PIL Image. Req 6.3"""
        img_bytes, _ = convert_format(self._base_image(), "JPEG")
        reloaded = Image.open(_BytesIO(img_bytes))
        reloaded.verify()  # raises if file is corrupt

    def test_jpeg_reported_size_matches_bytes_length(self):
        """file_size_bytes must equal len(image_bytes) for JPEG. Req 6.5"""
        img_bytes, reported_size = convert_format(self._base_image(), "JPEG")
        assert reported_size == len(img_bytes)

    def test_jpeg_reloaded_image_has_correct_dimensions(self):
        """JPEG round-trip must preserve image dimensions. Req 6.4"""
        img = self._base_image(160, 120)
        img_bytes, _ = convert_format(img, "JPEG")
        reloaded = Image.open(_BytesIO(img_bytes))
        assert reloaded.size == (160, 120)

    def test_jpeg_format_string_is_case_insensitive(self):
        """'jpeg' and 'JPEG' must both work without raising. Req 6.2"""
        img = self._base_image()
        bytes_upper, size_upper = convert_format(img, "JPEG")
        bytes_lower, size_lower = convert_format(img, "jpeg")
        # Both must be valid and report sizes accurately
        assert size_upper == len(bytes_upper)
        assert size_lower == len(bytes_lower)

    # --- PNG ---

    def test_png_returns_non_empty_bytes(self):
        """PNG conversion must return a non-empty bytes object. Req 6.2"""
        img_bytes, size = convert_format(self._base_image(), "PNG")
        assert isinstance(img_bytes, bytes)
        assert len(img_bytes) > 0

    def test_png_bytes_are_reloadable(self):
        """PNG bytes must be re-openable as a valid PIL Image. Req 6.3"""
        img_bytes, _ = convert_format(self._base_image(), "PNG")
        reloaded = Image.open(_BytesIO(img_bytes))
        reloaded.verify()

    def test_png_reported_size_matches_bytes_length(self):
        """file_size_bytes must equal len(image_bytes) for PNG. Req 6.5"""
        img_bytes, reported_size = convert_format(self._base_image(), "PNG")
        assert reported_size == len(img_bytes)

    def test_png_reloaded_image_has_correct_dimensions(self):
        """PNG round-trip must preserve image dimensions. Req 6.4"""
        img = self._base_image(200, 150)
        img_bytes, _ = convert_format(img, "PNG")
        reloaded = Image.open(_BytesIO(img_bytes))
        assert reloaded.size == (200, 150)

    def test_png_is_lossless_round_trip(self):
        """PNG is lossless — reloaded pixels must match the original exactly."""
        img = Image.new("RGB", (10, 10), color=(77, 133, 200))
        img_bytes, _ = convert_format(img, "PNG")
        reloaded = Image.open(_BytesIO(img_bytes))
        assert list(reloaded.convert("RGB").getdata()) == list(img.getdata())

    # --- WebP ---

    def test_webp_returns_non_empty_bytes(self):
        """WebP conversion must return a non-empty bytes object. Req 6.2"""
        img_bytes, size = convert_format(self._base_image(), "WEBP")
        assert isinstance(img_bytes, bytes)
        assert len(img_bytes) > 0

    def test_webp_bytes_are_reloadable(self):
        """WebP bytes must be re-openable as a valid PIL Image. Req 6.3"""
        img_bytes, _ = convert_format(self._base_image(), "WEBP")
        reloaded = Image.open(_BytesIO(img_bytes))
        reloaded.load()  # .verify() is not supported for WEBP; .load() confirms decodability

    def test_webp_reported_size_matches_bytes_length(self):
        """file_size_bytes must equal len(image_bytes) for WebP. Req 6.5"""
        img_bytes, reported_size = convert_format(self._base_image(), "WEBP")
        assert reported_size == len(img_bytes)

    def test_webp_reloaded_image_has_correct_dimensions(self):
        """WebP round-trip must preserve image dimensions. Req 6.4"""
        img = self._base_image(120, 90)
        img_bytes, _ = convert_format(img, "WEBP")
        reloaded = Image.open(_BytesIO(img_bytes))
        assert reloaded.size == (120, 90)

    # --- Quality parameter ---

    def test_quality_affects_jpeg_size(self):
        """Higher JPEG quality must produce a larger (or equal) file than lower quality."""
        img = self._base_image(200, 200)
        _, size_low = convert_format(img, "JPEG", quality=10)
        _, size_high = convert_format(img, "JPEG", quality=95)
        assert size_high >= size_low

    def test_quality_affects_webp_size(self):
        """WebP quality must affect file size; lossless (quality=100) is larger than lossy."""
        # Use a complex gradient image so quality setting has visible effect on file size.
        img = Image.new("RGB", (200, 200))
        for y in range(200):
            for x in range(200):
                img.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
        _, size_low = convert_format(img, "WEBP", quality=1)
        _, size_high = convert_format(img, "WEBP", quality=100)
        assert size_high >= size_low

    # --- RGBA input handling ---

    def test_jpeg_accepts_rgba_input(self):
        """convert_format must handle RGBA images for JPEG by stripping alpha. Req 6.2"""
        img = Image.new("RGBA", (80, 60), color=(100, 150, 200, 128))
        img_bytes, reported_size = convert_format(img, "JPEG")
        assert reported_size == len(img_bytes)
        assert len(img_bytes) > 0

    # --- Source image not mutated ---

    def test_does_not_mutate_source(self):
        """convert_format must not modify the source image."""
        img = self._base_image(color=(50, 100, 150))
        original_pixels = list(img.getdata())
        convert_format(img, "PNG")
        assert list(img.getdata()) == original_pixels

    # --- Property 8: size accuracy across all formats ---

    @pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
    def test_property8_reported_size_always_accurate(self, fmt):
        """Property 8: file_size_bytes == len(image_bytes) for every format. Req 6.5"""
        img = self._base_image()
        img_bytes, reported_size = convert_format(img, fmt)
        assert reported_size == len(img_bytes), (
            f"Format {fmt}: reported {reported_size} but actual len is {len(img_bytes)}"
        )


# ---------------------------------------------------------------------------
# apply_pipeline
# ---------------------------------------------------------------------------

class TestApplyPipeline:
    """
    Req 6.2, 6.3, 6.4, 6.5:
    apply_pipeline must apply steps in order (resize → filter → watermark →
    convert) and return (final_image, image_bytes, file_size_bytes).
    """

    def _base_image(self, width: int = 400, height: int = 300) -> Image.Image:
        """Return a solid-color RGB image suitable for pipeline testing."""
        return Image.new("RGB", (width, height), color=(80, 120, 200))

    # --- Return contract ---

    def test_returns_three_tuple(self):
        """apply_pipeline must return a 3-tuple. Req 6.2"""
        result = apply_pipeline(
            self._base_image(),
            resize_options=None,
            color_filter=None,
            watermark_options=None,
            output_format="PNG",
            quality=85,
        )
        assert len(result) == 3

    def test_first_element_is_pil_image(self):
        """First return value must be a PIL Image. Req 6.4"""
        img, _, _ = apply_pipeline(
            self._base_image(),
            resize_options=None,
            color_filter=None,
            watermark_options=None,
            output_format="PNG",
            quality=85,
        )
        assert isinstance(img, Image.Image)

    def test_second_element_is_bytes(self):
        """Second return value must be bytes. Req 6.2"""
        _, img_bytes, _ = apply_pipeline(
            self._base_image(),
            resize_options=None,
            color_filter=None,
            watermark_options=None,
            output_format="JPEG",
            quality=85,
        )
        assert isinstance(img_bytes, bytes)
        assert len(img_bytes) > 0

    def test_third_element_equals_len_of_bytes(self):
        """Third return value must equal len(image_bytes). Req 6.5"""
        _, img_bytes, file_size = apply_pipeline(
            self._base_image(),
            resize_options=None,
            color_filter=None,
            watermark_options=None,
            output_format="JPEG",
            quality=85,
        )
        assert file_size == len(img_bytes)

    # --- Passthrough (all None) ---

    def test_all_none_options_returns_valid_result(self):
        """Pipeline with all None optional params must still produce valid output. Req 6.2"""
        img = self._base_image(200, 150)
        final_img, img_bytes, file_size = apply_pipeline(
            img,
            resize_options=None,
            color_filter=None,
            watermark_options=None,
            output_format="PNG",
            quality=85,
        )
        assert isinstance(final_img, Image.Image)
        assert len(img_bytes) > 0
        assert file_size == len(img_bytes)

    def test_all_none_preserves_original_dimensions(self):
        """No-op pipeline must leave image dimensions unchanged. Req 6.4"""
        img = self._base_image(200, 150)
        final_img, _, _ = apply_pipeline(
            img,
            resize_options=None,
            color_filter=None,
            watermark_options=None,
            output_format="PNG",
            quality=85,
        )
        assert final_img.size == (200, 150)

    def test_does_not_mutate_source_image(self):
        """apply_pipeline must not modify the original image."""
        img = self._base_image(100, 100)
        original_pixels = list(img.getdata())
        apply_pipeline(
            img,
            resize_options={"width": 50, "height": 50},
            color_filter="grayscale",
            watermark_options={"text": "Test"},
            output_format="PNG",
            quality=85,
        )
        assert list(img.getdata()) == original_pixels

    # --- Resize step ---

    def test_resize_changes_final_image_dimensions(self):
        """Pipeline resize step must change the output image dimensions. Req 3.6"""
        img = self._base_image(400, 300)
        final_img, _, _ = apply_pipeline(
            img,
            resize_options={"width": 100, "height": 80},
            color_filter=None,
            watermark_options=None,
            output_format="PNG",
            quality=85,
        )
        assert final_img.size == (100, 80)

    def test_resize_with_aspect_ratio_fits_within_bounds(self):
        """Aspect-ratio resize must not exceed the target bounding box."""
        img = self._base_image(800, 600)
        final_img, _, _ = apply_pipeline(
            img,
            resize_options={"width": 200, "height": 200, "maintain_aspect_ratio": True},
            color_filter=None,
            watermark_options=None,
            output_format="PNG",
            quality=85,
        )
        w, h = final_img.size
        assert w <= 200
        assert h <= 200

    # --- Color filter step ---

    def test_pipeline_with_only_grayscale_filter(self):
        """Grayscale filter via pipeline must return an RGB image with r==g==b. Req 4.2"""
        img = self._base_image()
        final_img, _, _ = apply_pipeline(
            img,
            resize_options=None,
            color_filter="grayscale",
            watermark_options=None,
            output_format="PNG",
            quality=85,
        )
        assert final_img.mode == "RGB"
        for r, g, b in final_img.getdata():
            assert r == g == b

    def test_pipeline_with_only_sepia_filter(self):
        """Sepia filter via pipeline must return RGB with r>=g>=b per pixel. Req 4.3"""
        img = self._base_image()
        final_img, _, _ = apply_pipeline(
            img,
            resize_options=None,
            color_filter="sepia",
            watermark_options=None,
            output_format="PNG",
            quality=85,
        )
        assert final_img.mode == "RGB"
        for r, g, b in final_img.getdata():
            assert r >= g >= b

    def test_pipeline_with_only_invert_filter(self):
        """Invert filter via pipeline must negate all channel values. Req 4.4"""
        img = Image.new("RGB", (10, 10), color=(100, 150, 200))
        final_img, _, _ = apply_pipeline(
            img,
            resize_options=None,
            color_filter="invert",
            watermark_options=None,
            output_format="PNG",
            quality=85,
        )
        r, g, b = final_img.getpixel((0, 0))
        assert (r, g, b) == (155, 105, 55)

    def test_unknown_color_filter_is_ignored(self):
        """An unrecognised filter string must be silently ignored (no crash)."""
        img = self._base_image(100, 100)
        original_pixels = list(img.convert("RGB").getdata())
        final_img, _, _ = apply_pipeline(
            img,
            resize_options=None,
            color_filter="unknown_filter",
            watermark_options=None,
            output_format="PNG",
            quality=85,
        )
        # No exception, and pixels should be unchanged (filter was skipped)
        assert list(final_img.getdata()) == original_pixels

    # --- Watermark step ---

    def test_pipeline_with_only_watermark(self):
        """Watermark-only pipeline must preserve dimensions and return RGB. Req 5.2, 5.4"""
        img = self._base_image(400, 300)
        final_img, _, _ = apply_pipeline(
            img,
            resize_options=None,
            color_filter=None,
            watermark_options={"text": "Studio", "position": "bottom-right"},
            output_format="PNG",
            quality=85,
        )
        assert final_img.size == (400, 300)
        assert final_img.mode == "RGB"

    def test_watermark_default_position_used_when_not_specified(self):
        """watermark_options without 'position' must not raise. Req 5.3"""
        img = self._base_image()
        final_img, _, _ = apply_pipeline(
            img,
            resize_options=None,
            color_filter=None,
            watermark_options={"text": "No Position Key"},
            output_format="PNG",
            quality=85,
        )
        assert final_img.size == img.size

    # --- Format conversion step ---

    @pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
    def test_pipeline_output_bytes_reloadable_all_formats(self, fmt):
        """Pipeline bytes must be re-openable as a PIL Image for every format. Req 6.3"""
        img = self._base_image()
        _, img_bytes, file_size = apply_pipeline(
            img,
            resize_options=None,
            color_filter=None,
            watermark_options=None,
            output_format=fmt,
            quality=85,
        )
        reloaded = Image.open(_BytesIO(img_bytes))
        reloaded.load()
        assert file_size == len(img_bytes)

    # --- Full pipeline (all steps active) ---

    def test_full_pipeline_all_options_set(self):
        """Running all pipeline steps together must produce a valid result. Req 6.2"""
        img = self._base_image(600, 400)
        final_img, img_bytes, file_size = apply_pipeline(
            img,
            resize_options={"width": 300, "height": 200},
            color_filter="sepia",
            watermark_options={"text": "Full Pipeline", "position": "bottom-right"},
            output_format="JPEG",
            quality=80,
        )
        assert isinstance(final_img, Image.Image)
        assert len(img_bytes) > 0
        assert file_size == len(img_bytes)

    def test_full_pipeline_resize_happens_before_filter(self):
        """After the full pipeline with resize, the output image must have the target size."""
        img = self._base_image(600, 400)
        final_img, _, _ = apply_pipeline(
            img,
            resize_options={"width": 150, "height": 100},
            color_filter="grayscale",
            watermark_options={"text": "Order Test", "position": "top-left"},
            output_format="PNG",
            quality=85,
        )
        # Resize step must have run first — final image has resized dimensions
        assert final_img.size == (150, 100)

    def test_full_pipeline_grayscale_applied_after_resize(self):
        """Grayscale invariant (r==g==b) must still hold after full pipeline."""
        img = self._base_image(600, 400)
        final_img, _, _ = apply_pipeline(
            img,
            resize_options={"width": 200, "height": 150},
            color_filter="grayscale",
            watermark_options=None,
            output_format="PNG",
            quality=85,
        )
        for r, g, b in final_img.getdata():
            assert r == g == b

    def test_pipeline_size_consistency_across_formats(self):
        """file_size_bytes == len(image_bytes) must hold for JPEG, PNG, WebP. Req 6.5"""
        img = self._base_image()
        for fmt in ("JPEG", "PNG", "WEBP"):
            _, img_bytes, file_size = apply_pipeline(
                img,
                resize_options=None,
                color_filter=None,
                watermark_options=None,
                output_format=fmt,
                quality=85,
            )
            assert file_size == len(img_bytes), (
                f"Format {fmt}: reported {file_size} but actual len is {len(img_bytes)}"
            )
