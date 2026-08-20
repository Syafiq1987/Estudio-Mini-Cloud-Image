import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from PIL import Image as PILImage

from services.image_processor import (
    apply_pipeline,
    get_image_dimensions,
    load_image,
    validate_image,
)
from services.models import ImageMetadata, MiniCloudError

ROOT_DIR = Path(__file__).resolve().parent.parent
APP_PY = ROOT_DIR / "app.py"
UPLOAD_PY = ROOT_DIR / "pages" / "1_upload.py"
GALLERY_PY = ROOT_DIR / "pages" / "2_gallery.py"
ASSETS_DIR = ROOT_DIR / "assets"
LOGO_ESTUDIO = ASSETS_DIR / "logo_estudio.png"
NAV_BERANDA = ASSETS_DIR / "nav_beranda.png"
NAV_UPLOAD = ASSETS_DIR / "nav_upload.png"
NAV_GALLERY = ASSETS_DIR / "nav_gallery.png"


def _load_pil(img_path: Path) -> PILImage.Image | None:
    """Load file gambar sebagai PIL Image. Return None jika gagal (UI tetap aman)."""
    if not img_path or not img_path.exists():
        return None
    try:
        return PILImage.open(img_path)
    except Exception:
        return None


def _nav_sidebar_row(img_path: Path, page_path: Path, label: str) -> None:
    _icol, _lcol = st.columns([2, 5], gap="small")
    _img_pil = _load_pil(img_path)
    if _img_pil:
        _icol.image(_img_pil, use_container_width=True)
    with _lcol:
        st.page_link(page=str(page_path), label=label)


# ---------------------------------------------------------------------------
# Konfigurasi halaman (HARUS dipanggil PALING AWAL sebelum widget apapun)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Upload Gambar — Mini Cloud Image Studio",
    page_icon="⬆️",
    layout="wide",
    initial_sidebar_state="expanded",
)


with st.sidebar:
    # --- Branding: logo estudio pixel art + judul ---
    _c1, _c2 = st.columns([1, 3], gap="small")
    _logo_pil = _load_pil(LOGO_ESTUDIO)
    if _logo_pil:
        _c1.image(_logo_pil, use_container_width=True)
    else:
        _c1.markdown("## 🖼️")
    _c2.title("Mini Cloud Image Studio")
    st.markdown("---")
    st.subheader("Navigasi")
    if APP_PY.exists():
        _nav_sidebar_row(NAV_BERANDA, APP_PY, "Beranda")
    if UPLOAD_PY.exists():
        _nav_sidebar_row(NAV_UPLOAD, UPLOAD_PY, "Upload Gambar")
    if GALLERY_PY.exists():
        _nav_sidebar_row(NAV_GALLERY, GALLERY_PY, "Galeri Gambar")
    st.markdown("---")
    st.caption("Mini Cloud Image Studio v1.0")

storage_svc = st.session_state.get("storage_service")
metadata_svc = st.session_state.get("metadata_service")
config = st.session_state.get("config")
connection_ok = st.session_state.get("connection_ok", False)
connection_error = st.session_state.get("connection_error")

if not storage_svc or not metadata_svc or not config:
    from config import AppConfig
    from services.storage_service import StorageService
    from services.metadata_service import MetadataService

    config = AppConfig()
    try:
        storage_svc = StorageService(config)
        metadata_svc = MetadataService(config)
        storage_svc.ensure_bucket_exists()
        metadata_svc.ensure_table_exists()
        connection_ok = True
        connection_error = None
    except MiniCloudError as exc:
        connection_ok = False
        connection_error = str(exc)
    except Exception as exc:  # noqa: BLE001
        connection_ok = False
        connection_error = (
            f"Koneksi cloud gagal: {type(exc).__name__}: {exc}. "
            f"Pastikan Ministack berjalan di {config.ENDPOINT_URL}."
        )

# --- Judul halaman dengan icon navigasi pixel art ---
_up_hc1, _up_hc2 = st.columns([2, 8], gap="medium")
_up_head_pil = _load_pil(NAV_UPLOAD)
if _up_head_pil:
    _up_hc1.image(_up_head_pil, use_container_width=True)
else:
    _up_hc1.markdown("## ⬆️")
_up_hc2.title("Upload & Manipulasi Gambar")

st.markdown(
    "Unggah gambar, terapkan manipulasi (resize, filter warna, watermark), "
    "lalu simpan hasilnya ke cloud lokal (**Ministack** S3 + DynamoDB)."
)

if not connection_ok:
    st.warning(
        "⚠️ Koneksi ke cloud lokal (Ministack) gagal. Anda masih BISA melakukan upload & preview "
        "manipulasi gambar secara LOKAL, tapi tombol simpan ke S3/DynamoDB akan dinonaktifkan. "
        "Untuk menyimpan permanen, install dan jalankan Ministack terlebih dahulu:\n\n"
        "```\npip install ministack\npython -m ministack serve\n```",
        icon="⚠️",
    )
    if connection_error:
        with st.expander("🔍 Detail Error Teknis (klik untuk melihat)"):
            st.code(connection_error, language="text")
    # TIDAK PAKAI st.stop() — fitur manipulasi LOKAL tetap jalan
    cloud_available = False
else:
    cloud_available = True

st.markdown("---")

# --- Session state keys for image state across reruns ---
IMG_KEYS = [
    "up_file_bytes",
    "up_filename",
    "up_original_image",
    "up_orig_w",
    "up_orig_h",
    "up_valid",
]

for k in IMG_KEYS:
    if k not in st.session_state:
        st.session_state[k] = None

upload_col, options_col = st.columns([3, 2])

with upload_col:
    st.subheader("1. Pilih Gambar")
    uploaded_file = st.file_uploader(
        "Pilih file gambar (JPG, PNG, WebP, BMP - maks 10 MB)",
        type=config.SUPPORTED_FORMATS,
        accept_multiple_files=False,
        key="image_uploader_widget",
    )

    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        valid, err_msg = validate_image(file_bytes, uploaded_file.name)
        if not valid:
            st.error(err_msg)
            for k in IMG_KEYS:
                st.session_state[k] = None
            st.session_state["up_valid"] = False
        else:
            try:
                original_image = load_image(file_bytes)
                orig_w, orig_h = get_image_dimensions(original_image)
                st.session_state["up_file_bytes"] = file_bytes
                st.session_state["up_filename"] = uploaded_file.name
                st.session_state["up_original_image"] = original_image
                st.session_state["up_orig_w"] = orig_w
                st.session_state["up_orig_h"] = orig_h
                st.session_state["up_valid"] = True
                st.success(f"✅ Gambar berhasil dimuat ({orig_w} × {orig_h} px)")
                st.image(
                    original_image,
                    caption=f"Asli: {uploaded_file.name} ({orig_w} × {orig_h})",
                    use_container_width=True,
                )
            except Exception as exc:
                st.error(f"Gagal memuat gambar: {exc}")
                for k in IMG_KEYS:
                    st.session_state[k] = None
                st.session_state["up_valid"] = False
    else:
        # Clear state if user removed the file
        for k in IMG_KEYS:
            st.session_state[k] = None

# Pull validated state from session
has_image = st.session_state.get("up_valid") is True
s_file_bytes = st.session_state.get("up_file_bytes")
s_filename = st.session_state.get("up_filename")
s_original_image = st.session_state.get("up_original_image")
s_orig_w = st.session_state.get("up_orig_w")
s_orig_h = st.session_state.get("up_orig_h")

with options_col:
    st.subheader("2. Opsi Manipulasi")

    st.markdown("#### ✂️ Resize Gambar")
    enable_resize = st.checkbox("Aktifkan resize", value=False, disabled=not has_image)
    resize_options = None

    if enable_resize and has_image:
        maintain_ratio = st.checkbox("Pertahankan aspect ratio", value=True, key="ratio_cb")

        max_w = max(int(s_orig_w), 100)
        max_h = max(int(s_orig_h), 100)

        if maintain_ratio:
            scale_pct = st.slider(
                "Skala (%)",
                min_value=10,
                max_value=200,
                value=100,
                step=5,
                help="Skala relatif dari ukuran asli",
            )
            target_w = max(1, int(s_orig_w * scale_pct / 100))
            target_h = max(1, int(s_orig_h * scale_pct / 100))
            st.caption(f"Dimensi target: **{target_w} × {target_h}** px")
            resize_options = {
                "width": target_w,
                "height": target_h,
                "maintain_aspect_ratio": True,
            }
        else:
            target_w = st.slider(
                "Lebar (px)",
                min_value=16,
                max_value=max_w,
                value=int(s_orig_w),
                step=1,
            )
            target_h = st.slider(
                "Tinggi (px)",
                min_value=16,
                max_value=max_h,
                value=int(s_orig_h),
                step=1,
            )
            resize_options = {
                "width": target_w,
                "height": target_h,
                "maintain_aspect_ratio": False,
            }

    st.markdown("#### 🎨 Filter Warna")
    color_filter = st.selectbox(
        "Pilih filter warna",
        ["none", "grayscale", "sepia", "invert"],
        format_func=lambda x: {
            "none": "❌ Tanpa filter",
            "grayscale": "⬜ Grayscale (Hitam Putih)",
            "sepia": "🟫 Sepia (Cokelat Tua)",
            "invert": "🔄 Invert (Negatif)",
        }.get(x, x),
        disabled=not has_image,
    )
    selected_filter = None if color_filter == "none" else color_filter

    st.markdown("#### 🔖 Watermark Teks")
    enable_watermark = st.checkbox(
        "Tambahkan watermark teks otomatis",
        value=True,
        disabled=not has_image,
    )
    watermark_options = None
    if enable_watermark and has_image:
        nim = st.text_input(
            "NIM Mahasiswa",
            value="1234567890",
            disabled=not has_image,
            help="NIM akan ditampilkan dalam watermark",
        )
        wm_position = st.selectbox(
            "Posisi Watermark",
            ["bottom-right", "bottom-left", "top-right", "top-left"],
            format_func=lambda x: {
                "bottom-right": "Kanan Bawah",
                "bottom-left": "Kiri Bawah",
                "top-right": "Kanan Atas",
                "top-left": "Kiri Atas",
            }.get(x, x),
            disabled=not has_image,
        )
        wm_text = f"Uploaded via Mini Cloud Storage - {nim}"
        watermark_options = {"text": wm_text, "position": wm_position}

    st.markdown("#### 📦 Format Output")
    output_format = st.selectbox(
        "Format penyimpanan",
        ["JPEG", "PNG", "WEBP"],
        format_func=lambda x: {
            "JPEG": "JPEG - Ukuran kecil (tidak support transparansi)",
            "PNG": "PNG - Kualitas tinggi (support transparansi)",
            "WEBP": "WebP - Ukuran paling kecil (modern)",
        }.get(x, x),
        disabled=not has_image,
    )
    quality = 85
    if output_format in ("JPEG", "WEBP"):
        quality = st.slider(
            "Kualitas",
            min_value=10,
            max_value=95,
            value=85,
            step=5,
            help="Semakin tinggi semakin tajam, ukuran semakin besar",
            disabled=not has_image,
        )

st.markdown("---")

preview_col, save_col = st.columns([3, 2])

# Always compute pipeline result if we have an image (for preview and save consistency)
final_image = None
final_bytes = None
final_size = None
final_w = None
final_h = None
size_mb = None
size_kb = None
orig_size_kb = None

if has_image:
    try:
        final_image, final_bytes, final_size = apply_pipeline(
            s_original_image,
            resize_options,
            selected_filter,
            watermark_options,
            output_format,
            quality,
        )
        final_w, final_h = get_image_dimensions(final_image)
        size_kb = final_size / 1024
        size_mb = size_kb / 1024
        orig_size_kb = len(s_file_bytes) / 1024
    except Exception as exc:
        st.error(f"Gagal memproses gambar: {exc}")
        final_image = None
        final_bytes = None
        final_size = None

with preview_col:
    st.subheader("3. Preview Hasil")
    if not has_image:
        st.info("Unggah gambar terlebih dahulu untuk melihat preview.")
    elif final_image is None:
        st.warning("Preview tidak tersedia karena terjadi error saat memproses.")
    else:
        m1, m2, m3 = st.columns(3)
        delta_pct = ((final_size - len(s_file_bytes)) / len(s_file_bytes)) * 100
        m1.metric("Dimensi", f"{final_w} × {final_h} px")
        m2.metric(
            "Ukuran File",
            f"{size_mb:.2f} MB" if size_mb >= 1 else f"{size_kb:.1f} KB",
            delta=f"{delta_pct:.1f}%",
            delta_color="inverse",
        )
        m3.metric("Format", output_format)

        st.image(
            final_image,
            caption=f"Hasil manipulasi: {output_format} ({final_w} × {final_h})",
            use_container_width=True,
        )

with save_col:
    st.subheader("4. Simpan ke Cloud")
    if not has_image:
        st.info("Unggah gambar terlebih dahulu.")
    elif final_bytes is None:
        st.warning("Tidak dapat menyimpan: pemrosesan gambar gagal.")
    elif not cloud_available:
        st.warning(
            "⚠️ Cloud (S3 + DynamoDB) tidak terhubung. Anda dapat melihat preview di atas, "
            "tapi tombol simpan permanen dinonaktifkan. "
            "Jalankan **Ministack** untuk menyimpan ke cloud:\n\n"
            "```\npip install ministack\npython -m ministack serve\n```"
        )
        st.button(
            "💾 Upload & Simpan ke Cloud",
            type="primary",
            use_container_width=True,
            disabled=True,
            help="Cloud tidak terhubung",
        )
    else:
        st.info(
            f"Data akan disimpan ke:\n"
            f"- **S3 Bucket**: `{config.S3_BUCKET_NAME}`\n"
            f"- **DynamoDB Table**: `{config.DYNAMODB_TABLE_NAME}`"
        )
        if st.button(
            "💾 Upload & Simpan ke Cloud",
            type="primary",
            use_container_width=True,
        ):
            with st.status("Menyimpan ke cloud...", expanded=True) as status:
                try:
                    image_id = str(uuid.uuid4())
                    fmt_ext = output_format.lower()
                    base_name = (
                        s_filename.rsplit(".", 1)[0] if "." in s_filename else s_filename
                    )
                    s3_key = f"images/{image_id}_{base_name}.{fmt_ext}"
                    content_type = f"image/{fmt_ext}"

                    st.write(f"📤 Mengunggah gambar ke S3: `{s3_key}`...")
                    storage_svc.upload_image(final_bytes, s3_key, content_type)
                    st.write("✅ Upload ke S3 berhasil")

                    manipulations = []
                    if resize_options:
                        manipulations.append("resize")
                    if selected_filter:
                        manipulations.append(selected_filter)
                    if watermark_options:
                        manipulations.append("watermark")
                    orig_ext = (
                        s_filename.rsplit(".", 1)[-1].lower()
                        if "." in s_filename
                        else ""
                    )
                    if output_format.lower() != orig_ext:
                        manipulations.append("format_conversion")

                    metadata = ImageMetadata(
                        image_id=image_id,
                        original_filename=s_filename,
                        s3_key=s3_key,
                        file_format=output_format,
                        file_size_bytes=final_size,
                        original_width=int(s_orig_w),
                        original_height=int(s_orig_h),
                        final_width=final_w,
                        final_height=final_h,
                        upload_timestamp=datetime.now(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        manipulations_applied=manipulations,
                        watermark_text=(
                            watermark_options["text"] if watermark_options else None
                        ),
                        color_filter=selected_filter,
                        output_quality=(
                            quality if output_format in ("JPEG", "WEBP") else None
                        ),
                    )

                    st.write(f"💾 Menyimpan metadata ke DynamoDB: `{image_id}`...")
                    metadata_svc.save_metadata(metadata)
                    st.write("✅ Metadata tersimpan")

                    status.update(
                        label="🎉 Berhasil disimpan!", state="complete", expanded=False
                    )
                    manip_str = (
                        ", ".join(manipulations) if manipulations else "Tidak ada"
                    )
                    st.success(
                        "Gambar berhasil disimpan!\n\n"
                        f"- **Image ID**: `{image_id}`\n"
                        f"- **S3 Key**: `{s3_key}`\n"
                        f"- **Ukuran**: {size_mb:.2f} MB ({final_size:,} bytes)\n"
                        f"- **Manipulasi**: {manip_str}"
                    )
                except MiniCloudError as exc:
                    status.update(
                        label="❌ Gagal menyimpan", state="error", expanded=True
                    )
                    st.error(f"Error: {exc}")
                except Exception as exc:
                    status.update(
                        label="❌ Gagal menyimpan", state="error", expanded=True
                    )
                    st.error(f"Error tidak terduga: {exc}")
