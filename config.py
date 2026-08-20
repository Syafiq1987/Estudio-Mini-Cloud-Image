"""
config.py — Konfigurasi koneksi dan konstanta aplikasi Mini Cloud Image Studio.

Membaca konfigurasi dari environment variables (via python-dotenv) dengan
nilai default yang sensible untuk lingkungan pengembangan lokal menggunakan
**Ministack** (open-source Python clone S3 + DynamoDB compatible dengan boto3).
"""

import os
from dotenv import load_dotenv

# Muat variabel dari file .env jika ada (tidak wajib)
load_dotenv()


class AppConfig:
    """
    Konfigurasi terpusat untuk seluruh aplikasi.

    Semua nilai dibaca dari environment variables. Jika tidak ditemukan,
    digunakan nilai default yang sesuai untuk lingkungan lokal (Ministack).
    """

    # --- Koneksi Cloud (DEFAULT: Ministack — compatible dengan LocalStack / MinIO) ---
    ENDPOINT_URL: str = os.getenv("ENDPOINT_URL", "http://localhost:4566")
    AWS_ACCESS_KEY: str = os.getenv("AWS_ACCESS_KEY_ID", os.getenv("AWS_ACCESS_KEY", "test"))
    AWS_SECRET_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", os.getenv("AWS_SECRET_KEY", "test"))
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")

    # --- Boto3 Client Config untuk kompatibilitas penuh dengan Ministack ---
    # Ministack (seperti MinIO) mensyaratkan:
    #   - signature_version = "s3v4"   (Signature Version 4)
    #   - addressing_style = "path"    (path-style, bukan virtual-hosted-style)
    #     → virtual-hosted-style kadang gagal di endpoint localhost (DNS issue).
    S3_ADDRESSING_STYLE: str = os.getenv("S3_ADDRESSING_STYLE", "path")
    S3_SIGNATURE_VERSION: str = os.getenv("S3_SIGNATURE_VERSION", "s3v4")

    # --- Nama Resource AWS ---
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "mini-cloud-studio")
    DYNAMODB_TABLE_NAME: str = os.getenv("DYNAMODB_TABLE_NAME", "image-metadata")

    # --- Batasan Upload ---
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB

    # --- Format Gambar yang Didukung ---
    SUPPORTED_FORMATS: list = ["jpg", "jpeg", "png", "webp", "bmp"]
