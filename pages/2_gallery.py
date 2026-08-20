from pathlib import Path

import streamlit as st
from PIL import Image as PILImage

from services.models import MiniCloudError

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


# ---------------------------------------------------------------------------
# Konfigurasi halaman (HARUS dipanggil PALING AWAL sebelum widget apapun)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Galeri Gambar — Mini Cloud Image Studio",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _nav_sidebar_row(img_path: Path, page_path: Path, label: str) -> None:
    _icol, _lcol = st.columns([2, 5], gap="small")
    _img_pil = _load_pil(img_path)
    if _img_pil:
        _icol.image(_img_pil, use_container_width=True)
    with _lcol:
        st.page_link(page=str(page_path), label=label)


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
_gal_hc1, _gal_hc2 = st.columns([2, 8], gap="medium")
_gal_head_pil = _load_pil(NAV_GALLERY)
if _gal_head_pil:
    _gal_hc1.image(_gal_head_pil, use_container_width=True)
else:
    _gal_hc1.markdown("## 🖼️")
_gal_hc2.title("Galeri Gambar")

st.markdown(
    "Menampilkan semua gambar yang tersimpan di S3 dengan metadata dari DynamoDB."
)

if not connection_ok:
    st.warning(
        "⚠️ Koneksi ke cloud lokal gagal. Galeri tidak dapat dimuat karena "
        "bergantung pada S3 + DynamoDB. Jalankan **Ministack** untuk melihat "
        "gambar yang tersimpan:\n\n"
        "```\npip install ministack\npython -m ministack serve\n```",
        icon="⚠️",
    )
    if connection_error:
        with st.expander("🔍 Detail Error Teknis"):
            st.code(connection_error, language="text")
    st.info(
        "💡 Anda masih bisa menggunakan halaman **Upload Gambar** untuk "
        "melakukan manipulasi gambar secara LOKAL tanpa menyimpan ke cloud."
    )
    # Gallery memang butuh cloud, jadi stop di sini TAPI beri opsi navigasi ke Upload
    st.stop()

st.markdown("---")


def fmt_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MB"
    elif n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def load_gallery():
    try:
        items = metadata_svc.list_all_metadata()
        return items
    except MiniCloudError as exc:
        st.error(f"Gagal memuat metadata: {exc}")
        return []


def get_image_with_fallback(s3_key: str):
    try:
        image_bytes = storage_svc.get_image_bytes(s3_key)
        return image_bytes, None
    except MiniCloudError as exc:
        return None, str(exc)


refresh_col, _ = st.columns([1, 4])
with refresh_col:
    refresh_btn = st.button("🔄 Muat Ulang Galeri", use_container_width=True)

if "gallery_items" not in st.session_state or refresh_btn:
    with st.spinner("Memuat galeri dari DynamoDB..."):
        st.session_state["gallery_items"] = load_gallery()

items = st.session_state["gallery_items"]

if not items:
    st.info("📭 Galeri kosong. Belum ada gambar yang diunggah.")
    st.markdown("Silakan unggah gambar di halaman **Upload Gambar**.")
    st.stop()

total_size = sum(m.file_size_bytes for m in items)
st.markdown(
    f"**Total:** {len(items)} gambar · **Total ukuran:** {fmt_size(total_size)}"
)
st.markdown("---")

# Delete action state handling (single delete at a time, outside of loop)
pending_delete = st.session_state.get("pending_delete_meta")
delete_just_done = False

if pending_delete is not None:
    meta = pending_delete
    st.warning(f"⚠️ Konfirmasi penghapusan gambar: **{meta['original_filename']}**")
    dcol1, dcol2, _ = st.columns([1, 1, 3])
    if dcol1.button("✅ Ya, Hapus Sekarang", type="primary", use_container_width=True, key="confirm_del_global"):
        del_errors = []
        try:
            storage_svc.delete_image(meta["s3_key"])
        except MiniCloudError as exc:
            del_errors.append(f"S3: {exc}")
        try:
            metadata_svc.delete_metadata(meta["image_id"])
        except MiniCloudError as exc:
            del_errors.append(f"DynamoDB: {exc}")
        if del_errors:
            st.error("Sebagian penghapusan gagal:\n- " + "\n- ".join(del_errors))
        else:
            st.success(f"✅ Gambar '{meta['original_filename']}' berhasil dihapus.")
        st.session_state["pending_delete_meta"] = None
        st.session_state.pop("gallery_items", None)
        delete_just_done = True
    if dcol2.button("❌ Batal", use_container_width=True, key="cancel_del_global"):
        st.session_state["pending_delete_meta"] = None
        st.rerun()

if delete_just_done:
    st.rerun()

cols_per_row = 4
for i in range(0, len(items), cols_per_row):
    row = items[i : i + cols_per_row]
    cols = st.columns(cols_per_row)
    for col, meta in zip(cols, row):
        with col:
            with st.container(border=True):
                img_bytes, img_err = get_image_with_fallback(meta.s3_key)
                if img_bytes:
                    st.image(
                        img_bytes,
                        caption=f"{meta.final_width}×{meta.final_height} · {meta.file_format}",
                        use_container_width=True,
                    )
                else:
                    st.warning("⚠️ Gambar tidak dapat dimuat dari S3")
                    if img_err:
                        st.caption(img_err)

                st.markdown(f"**File:** {meta.original_filename}")
                st.markdown(f"**Ukuran:** {fmt_size(meta.file_size_bytes)}")

                manip_str = (
                    ", ".join(meta.manipulations_applied)
                    if meta.manipulations_applied
                    else "—"
                )
                st.caption(f"**Manipulasi:** {manip_str}")
                st.caption(f"**Upload:** {meta.upload_timestamp}")

                detail_key = f"detail_{meta.image_id}"
                if st.button(
                    "📋 Detail",
                    key=f"btn_detail_{meta.image_id}",
                    use_container_width=True,
                ):
                    cur = st.session_state.get(detail_key, False)
                    st.session_state[detail_key] = not cur

                if st.session_state.get(detail_key, False):
                    st.markdown("---")
                    st.markdown("**Metadata Lengkap:**")
                    st.json(
                        {
                            "image_id": meta.image_id,
                            "original_filename": meta.original_filename,
                            "s3_key": meta.s3_key,
                            "file_format": meta.file_format,
                            "file_size_bytes": meta.file_size_bytes,
                            "original_width": meta.original_width,
                            "original_height": meta.original_height,
                            "final_width": meta.final_width,
                            "final_height": meta.final_height,
                            "upload_timestamp": meta.upload_timestamp,
                            "manipulations_applied": meta.manipulations_applied,
                            "watermark_text": meta.watermark_text,
                            "color_filter": meta.color_filter,
                            "output_quality": meta.output_quality,
                        }
                    )

                if st.button(
                    "🗑️ Hapus",
                    key=f"btn_del_{meta.image_id}",
                    use_container_width=True,
                ):
                    st.session_state["pending_delete_meta"] = {
                        "image_id": meta.image_id,
                        "original_filename": meta.original_filename,
                        "s3_key": meta.s3_key,
                    }
                    st.rerun()
