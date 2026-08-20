"""
services/storage_service.py — Operasi S3 via boto3 untuk Mini Cloud Image Studio.

Mengelola semua interaksi dengan bucket S3 (Ministack / LocalStack / MinIO):
pembuatan bucket, upload, download, penghapusan, presigned URL, dan listing objek.
"""

import boto3
from botocore.client import Config as BotoClientConfig
from botocore.exceptions import BotoCoreError, ClientError

from config import AppConfig
from services.models import StorageError


class StorageService:
    """
    Mengelola semua operasi terhadap S3 (Ministack / LocalStack / MinIO) melalui boto3.

    Semua ClientError + BotoCoreError dari boto3 ditangkap dan di-raise ulang
    sebagai StorageError agar lapisan UI dapat menampilkan pesan yang informatif.

    Catatan kompatibilitas Ministack:
      - Menggunakan signature_version = "s3v4" (Signature Version 4)
      - Menggunakan s3_us_east_1_regional_endpoint + addressing_style = "path"
        (virtual-hosted-style kadang gagal di endpoint localhost tanpa DNS internal)
    """

    def __init__(self, config: AppConfig = AppConfig) -> None:
        """
        Inisialisasi boto3 S3 client menggunakan konfigurasi dari AppConfig.

        Parameters
        ----------
        config : AppConfig
            Kelas atau instance konfigurasi aplikasi. Default menggunakan
            kelas AppConfig langsung (atribut kelas sebagai nilai).
        """
        self.config = config
        s3_config = BotoClientConfig(
            signature_version=config.S3_SIGNATURE_VERSION,
            s3={
                "addressing_style": config.S3_ADDRESSING_STYLE,
            },
        )
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=config.ENDPOINT_URL,
            aws_access_key_id=config.AWS_ACCESS_KEY,
            aws_secret_access_key=config.AWS_SECRET_KEY,
            region_name=config.AWS_REGION,
            config=s3_config,
        )

    def ensure_bucket_exists(self) -> None:
        """
        Pastikan bucket S3 sudah ada; buat jika belum (idempoten).

        Menggunakan `head_bucket` untuk mengecek keberadaan bucket.
        Jika bucket belum ada (404 / NoSuchBucket), buat dengan
        `create_bucket`. Error lain dari boto3 di-raise sebagai StorageError.

        Raises
        ------
        StorageError
            Jika operasi S3 gagal karena alasan selain bucket tidak ada.
        """
        bucket = self.config.S3_BUCKET_NAME
        region = self.config.AWS_REGION

        try:
            self.s3_client.head_bucket(Bucket=bucket)
        except (ClientError, BotoCoreError) as e:
            error_code = getattr(e.response, "get", lambda *_: None)("Error", {}).get("Code") if isinstance(e, ClientError) else type(e).__name__
            error_code = error_code or getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
            if error_code in ("404", "NoSuchBucket") or isinstance(e, BotoCoreError):
                if error_code in ("404", "NoSuchBucket"):
                    try:
                        if region == "us-east-1":
                            self.s3_client.create_bucket(Bucket=bucket)
                        else:
                            self.s3_client.create_bucket(
                                Bucket=bucket,
                                CreateBucketConfiguration={"LocationConstraint": region},
                            )
                    except (ClientError, BotoCoreError) as create_err:
                        raise StorageError(
                            f"Gagal membuat bucket '{bucket}': {create_err}"
                        ) from create_err
                else:
                    raise StorageError(
                        f"Gagal terhubung ke endpoint cloud untuk bucket '{bucket}': {e}"
                    ) from e
            else:
                raise StorageError(
                    f"Gagal memeriksa bucket '{bucket}' (kode: {error_code}): {e}"
                ) from e

    def upload_image(
        self,
        image_bytes: bytes,
        s3_key: str,
        content_type: str,
    ) -> str:
        """
        Upload gambar ke bucket S3.

        Parameters
        ----------
        image_bytes : bytes
            Data gambar yang akan diunggah.
        s3_key : str
            Key objek di bucket S3 (mis. "images/abc123_foto.jpg").
        content_type : str
            MIME type gambar (mis. "image/jpeg", "image/png").

        Returns
        -------
        str
            s3_key yang sama yang diberikan sebagai parameter.

        Raises
        ------
        StorageError
            Jika operasi put_object gagal.
        """
        try:
            self.s3_client.put_object(
                Bucket=self.config.S3_BUCKET_NAME,
                Key=s3_key,
                Body=image_bytes,
                ContentType=content_type,
            )
            return s3_key
        except (ClientError, BotoCoreError) as e:
            if isinstance(e, ClientError):
                error_code = e.response["Error"]["Code"]
            else:
                error_code = type(e).__name__
            raise StorageError(
                f"Upload gagal untuk key '{s3_key}' (kode: {error_code}): {e}"
            ) from e

    def get_image_bytes(self, s3_key: str) -> bytes:
        """
        Ambil gambar dari S3 sebagai bytes.

        Parameters
        ----------
        s3_key : str
            Key objek di bucket S3.

        Returns
        -------
        bytes
            Isi file gambar.

        Raises
        ------
        StorageError
            Jika operasi get_object gagal (mis. objek tidak ditemukan).
        """
        try:
            response = self.s3_client.get_object(
                Bucket=self.config.S3_BUCKET_NAME,
                Key=s3_key,
            )
            return response["Body"].read()
        except (ClientError, BotoCoreError) as e:
            if isinstance(e, ClientError):
                error_code = e.response["Error"]["Code"]
            else:
                error_code = type(e).__name__
            raise StorageError(
                f"Gagal mengambil objek '{s3_key}' (kode: {error_code}): {e}"
            ) from e

    def delete_image(self, s3_key: str) -> None:
        """
        Hapus gambar dari bucket S3.

        Parameters
        ----------
        s3_key : str
            Key objek di bucket S3.

        Raises
        ------
        StorageError
            Jika operasi delete_object gagal.
        """
        try:
            self.s3_client.delete_object(
                Bucket=self.config.S3_BUCKET_NAME,
                Key=s3_key,
            )
        except (ClientError, BotoCoreError) as e:
            if isinstance(e, ClientError):
                error_code = e.response["Error"]["Code"]
            else:
                error_code = type(e).__name__
            raise StorageError(
                f"Gagal menghapus objek '{s3_key}' (kode: {error_code}): {e}"
            ) from e

    def generate_presigned_url(self, s3_key: str, expiry: int = 3600) -> str:
        """
        Buat URL presigned sementara untuk akses objek gambar di S3.

        Jika pembuatan presigned URL gagal (mis. endpoint MinIO/LocalStack
        tidak mendukung), fallback ke URL langsung yang dapat diakses.

        Parameters
        ----------
        s3_key : str
            Key objek di bucket S3.
        expiry : int, optional
            Waktu berlaku URL dalam detik. Default 3600 (1 jam).

        Returns
        -------
        str
            URL presigned (jika berhasil) atau URL langsung (fallback).
        """
        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.config.S3_BUCKET_NAME,
                    "Key": s3_key,
                },
                ExpiresIn=expiry,
            )
            return url
        except Exception:
            # Fallback ke URL langsung jika presigned URL tidak didukung
            return (
                f"{self.config.ENDPOINT_URL}"
                f"/{self.config.S3_BUCKET_NAME}"
                f"/{s3_key}"
            )

    def list_objects(self) -> list[dict]:
        """
        Daftar semua objek di bucket S3, dengan dukungan pagination.

        Menggunakan ContinuationToken untuk mengambil semua objek meskipun
        jumlahnya melebihi batas satu halaman respons S3 (1000 objek).

        Returns
        -------
        list[dict]
            List dict dengan format ``[{"key": str, "size": int}, ...]``.
            Mengembalikan list kosong jika bucket tidak memiliki objek.

        Raises
        ------
        StorageError
            Jika operasi list_objects_v2 gagal.
        """
        try:
            results: list[dict] = []
            kwargs: dict = {"Bucket": self.config.S3_BUCKET_NAME}

            while True:
                response = self.s3_client.list_objects_v2(**kwargs)
                for obj in response.get("Contents", []):
                    results.append({"key": obj["Key"], "size": obj["Size"]})

                # Lanjutkan ke halaman berikutnya jika ada
                if response.get("IsTruncated"):
                    kwargs["ContinuationToken"] = response["NextContinuationToken"]
                else:
                    break

            return results
        except (ClientError, BotoCoreError) as e:
            if isinstance(e, ClientError):
                error_code = e.response["Error"]["Code"]
            else:
                error_code = type(e).__name__
            raise StorageError(
                f"Gagal menampilkan daftar objek di bucket "
                f"'{self.config.S3_BUCKET_NAME}' (kode: {error_code}): {e}"
            ) from e
