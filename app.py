"""
app.py — Entrypoint Streamlit untuk Mini Cloud Image Studio.

Bertanggung jawab atas:
- Konfigurasi halaman Streamlit (judul, ikon, layout)
- Inisialisasi koneksi cloud (StorageService, MetadataService) satu kali
  dan menyimpannya di st.session_state agar tersedia di semua halaman
- Pengecekan status koneksi ke MinIO/LocalStack saat startup
- Tampilan sidebar: status koneksi dan navigasi
- Tampilan halaman utama: deskripsi aplikasi dan kartu fitur
"""

from pathlib import Path

import streamlit as st
from PIL import Image as PILImage

from config import AppConfig
from services.models import MiniCloudError
from services.storage_service import StorageService
from services.metadata_service import MetadataService

ROOT_DIR = Path(__file__).resolve().parent
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

# ---------------------------------------------------------------------------
# Konfigurasi halaman (harus dipanggil paling awal)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Mini Cloud Image Studio",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "Mini Cloud Image Studio — Aplikasi manipulasi gambar berbasis cloud lokal."
    },
)

# ---------------------------------------------------------------------------
# Inisialisasi koneksi (hanya sekali per sesi)
# ---------------------------------------------------------------------------

if "storage_service" not in st.session_state:
    config = AppConfig()

    storage_svc = StorageService(config)
    metadata_svc = MetadataService(config)

    connection_ok = True
    connection_error: str | None = None

    try:
        storage_svc.ensure_bucket_exists()
        metadata_svc.ensure_table_exists()
    except MiniCloudError as exc:
        connection_ok = False
        connection_error = str(exc)
    except Exception as exc:  # noqa: BLE001
        connection_ok = False
        connection_error = (
            f"Koneksi cloud gagal: {type(exc).__name__}: {exc}. "
            f"Pastikan LocalStack atau MinIO sudah berjalan di endpoint {config.ENDPOINT_URL}."
        )

    # Simpan ke session_state agar tersedia di semua halaman
    st.session_state["storage_service"] = storage_svc
    st.session_state["metadata_service"] = metadata_svc
    st.session_state["connection_ok"] = connection_ok
    st.session_state["connection_error"] = connection_error
    st.session_state["config"] = config
    st.session_state["uploaded_image"] = None
    st.session_state["uploaded_filename"] = None
    st.session_state["original_size_bytes"] = None

# Ambil status koneksi dari session_state
_connection_ok: bool = st.session_state.get("connection_ok", False)
_connection_error: str | None = st.session_state.get("connection_error")
_config: AppConfig = st.session_state.get("config", AppConfig())

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

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

    # --- Status koneksi ---
    st.subheader("Status Koneksi")
    if _connection_ok:
        st.success("✅ Terhubung ke Ministack (S3 + DynamoDB)")
    else:
        st.error("❌ Koneksi Gagal")
        st.markdown(
            f"**Endpoint:** `{_config.ENDPOINT_URL}`"
        )
        with st.expander("💡 Panduan Troubleshooting", expanded=True):
            st.markdown(
                """
**Kemungkinan penyebab dan solusi (DEFAULT menggunakan MINISTACK):**

1. **Ministack belum berjalan (RECOMMENDED — Python-based, install via pip)**
   ```
   pip install ministack
   python -m ministack serve
   ```
   *Atau* via Docker jika tersedia:
   ```
   docker run --rm -p 4566:4566 localstack/localstack
   ```

2. **LocalStack belum berjalan (alternatif Ministack — Docker-based)**
   Jalankan LocalStack dengan perintah:
   ```
   localstack start
   ```
   atau via Docker:
   ```
   docker run --rm -p 4566:4566 localstack/localstack
   ```

3. **MinIO belum berjalan (hanya S3 — butuh DynamoDB terpisah)**
   Jalankan MinIO dengan perintah:
   ```
   minio server /data --console-address ":9001"
   ```

4. **Konfigurasi endpoint salah**
   Periksa file `.env` dan pastikan nilai berikut sudah benar:
   ```
   ENDPOINT_URL=http://localhost:4566   # Ministack / LocalStack (default)
   # atau
   ENDPOINT_URL=http://localhost:9000   # MinIO (hanya S3)
   AWS_ACCESS_KEY_ID=test
   AWS_SECRET_ACCESS_KEY=test
   AWS_REGION=us-east-1
   ```

5. **Port diblokir firewall**
   Pastikan port `4566` (Ministack / LocalStack) atau `9000` (MinIO) dapat diakses.
                """
            )
        if _connection_error:
            with st.expander("🔍 Detail Error Teknis"):
                st.code(_connection_error, language="text")

    st.markdown("---")

    # --- Navigasi (icon pixel art + page link) ---
    st.subheader("Navigasi")

    def _nav_row(img_path: Path, page_path: Path, label: str) -> None:
        _icol, _lcol = st.columns([2, 5], gap="small")
        _img_pil = _load_pil(img_path)
        if _img_pil:
            _icol.image(_img_pil, use_container_width=True)
        with _lcol:
            st.page_link(page=str(page_path), label=label)

    if APP_PY.exists():
        _nav_row(NAV_BERANDA, APP_PY, "Beranda")
    if UPLOAD_PY.exists():
        _nav_row(NAV_UPLOAD, UPLOAD_PY, "Upload Gambar")
    if GALLERY_PY.exists():
        _nav_row(NAV_GALLERY, GALLERY_PY, "Galeri Gambar")

    st.markdown("---")
    st.caption("Mini Cloud Image Studio v1.0")
    st.caption("Powered by Streamlit + boto3")

# ---------------------------------------------------------------------------
# Halaman utama
# ---------------------------------------------------------------------------

# --- Judul halaman dengan logo estudio pixel art ---
_hcol1, _hcol2 = st.columns([1, 8], gap="medium")
_logo_head_pil = _load_pil(LOGO_ESTUDIO)
if _logo_head_pil:
    _hcol1.image(_logo_head_pil, width=90)
else:
    _hcol1.markdown("# 🖼️")
_hcol2.title("Mini Cloud Image Studio")

st.markdown(
    "Selamat datang di **Mini Cloud Image Studio** — platform manipulasi gambar "
    "berbasis cloud lokal menggunakan **Ministack** (boto3 compatible S3 + DynamoDB Python clone)."
)

# Banner status koneksi di halaman utama jika gagal
if not _connection_ok:
    st.warning(
        "⚠️ Koneksi ke cloud lokal gagal. Beberapa fitur mungkin tidak tersedia. "
        "Periksa panduan troubleshooting di sidebar (install & jalankan Ministack).",
        icon="⚠️",
    )

st.markdown("---")

# --- Kartu fitur ---
st.subheader("✨ Fitur Utama")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(
        """
        #### ⬆️ Upload Gambar
        Unggah file gambar (JPG, PNG, WebP, BMP) dengan ukuran hingga **10 MB**
        langsung ke bucket S3 pada **Ministack** (open-source Python LocalStack clone).
        """
    )

with col2:
    st.markdown(
        """
        #### ✂️ Resize & Filter
        Ubah dimensi gambar dengan slider, terapkan filter warna
        (**Grayscale**, **Sepia**, **Invert**), dan lihat preview secara real-time.
        """
    )

with col3:
    st.markdown(
        """
        #### 🔖 Watermark
        Tambahkan teks watermark semi-transparan di salah satu dari empat sudut gambar
        dengan ukuran font yang proporsional.
        """
    )

with col4:
    st.markdown(
        """
        #### 🖼️ Galeri & Manajemen
        Lihat semua gambar yang tersimpan dalam tampilan grid, baca metadata lengkap,
        dan hapus gambar beserta metadatanya sekaligus.
        """
    )

st.markdown("---")

# --- Cara Penggunaan ---
st.subheader("🚀 Cara Penggunaan")

step1, step2, step3 = st.columns(3)

with step1:
    st.info(
        "**Langkah 1 — Upload**\n\n"
        "Buka halaman **Upload Gambar** melalui sidebar, pilih file gambar, "
        "atur opsi manipulasi, lalu klik *Upload & Simpan*."
    )

with step2:
    st.info(
        "**Langkah 2 — Manipulasi**\n\n"
        "Sesuaikan ukuran gambar, pilih filter warna, aktifkan watermark, "
        "dan pilih format output (JPEG / PNG / WebP)."
    )

with step3:
    st.info(
        "**Langkah 3 — Galeri**\n\n"
        "Buka halaman **Galeri Gambar** untuk melihat semua gambar yang tersimpan, "
        "melihat detail metadata, atau menghapus gambar."
    )

# --- Ringkasan konfigurasi ---
with st.expander("⚙️ Konfigurasi Aktif"):
    cfg_col1, cfg_col2 = st.columns(2)
    with cfg_col1:
        st.markdown(
            f"""
| Parameter | Nilai |
|-----------|-------|
| Endpoint URL | `{_config.ENDPOINT_URL}` |
| Region | `{_config.AWS_REGION}` |
| S3 Bucket | `{_config.S3_BUCKET_NAME}` |
"""
        )
    with cfg_col2:
        st.markdown(
            f"""
| Parameter | Nilai |
|-----------|-------|
| DynamoDB Table | `{_config.DYNAMODB_TABLE_NAME}` |
| Ukuran Maks. | `{_config.MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB` |
| Format Didukung | `{", ".join(_config.SUPPORTED_FORMATS).upper()}` |
"""
        )
