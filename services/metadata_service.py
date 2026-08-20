"""
services/metadata_service.py — Operasi DynamoDB untuk Mini Cloud Image Studio.

Mengelola semua interaksi dengan tabel DynamoDB melalui boto3 resource API.
Kompatibel penuh dengan **Ministack**, LocalStack, dan AWS DynamoDB.
"""

import boto3
from botocore.client import Config as BotoClientConfig
from botocore.exceptions import BotoCoreError, ClientError
from decimal import Decimal
from typing import Optional

from config import AppConfig
from services.models import ImageMetadata, MetadataError


class MetadataService:
    """
    Mengelola penyimpanan dan pengambilan metadata gambar di DynamoDB.

    Setiap instance terikat ke satu tabel DynamoDB yang dikonfigurasi
    melalui AppConfig. Semua ClientError + BotoCoreError dari boto3 di-wrap
    menjadi MetadataError agar lapisan UI dapat menanganinya secara seragam.
    """

    def __init__(self, config: AppConfig = AppConfig) -> None:
        """
        Inisialisasi DynamoDB resource dan referensi tabel.

        Parameters
        ----------
        config:
            Kelas atau instance AppConfig. Nilai default menggunakan
            kelas AppConfig langsung (atribut class-level).
        """
        self.config = config
        dynamo_config = BotoClientConfig(
            # Ministack default DynamoDB kompatibel dengan signature v4
            signature_version=config.S3_SIGNATURE_VERSION,
            retries={
                "max_attempts": 3,
                "mode": "standard",
            },
        )
        self.dynamodb = boto3.resource(
            "dynamodb",
            endpoint_url=config.ENDPOINT_URL,
            aws_access_key_id=config.AWS_ACCESS_KEY,
            aws_secret_access_key=config.AWS_SECRET_KEY,
            region_name=config.AWS_REGION,
            config=dynamo_config,
        )
        self.table = self.dynamodb.Table(config.DYNAMODB_TABLE_NAME)

    # ------------------------------------------------------------------
    # Table lifecycle
    # ------------------------------------------------------------------

    def ensure_table_exists(self) -> None:
        """
        Buat tabel DynamoDB jika belum ada (idempoten).

        Tabel dibuat dengan:
        - Partition key: ``image_id`` (String)
        - Billing mode: PAY_PER_REQUEST (on-demand)

        Jika tabel sudah ada, metode ini langsung kembali tanpa error.
        Setelah pembuatan, menunggu hingga status tabel menjadi ACTIVE.

        Raises
        ------
        MetadataError
            Jika terjadi error boto3 selain ResourceInUseException
            (tabel sedang dibuat oleh proses lain).
        """
        try:
            table = self.dynamodb.create_table(
                TableName=self.config.DYNAMODB_TABLE_NAME,
                KeySchema=[
                    {"AttributeName": "image_id", "KeyType": "HASH"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "image_id", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            # Tunggu hingga tabel benar-benar ACTIVE sebelum melanjutkan
            table.wait_until_exists()
            # Perbarui referensi tabel agar atribut-nya ter-refresh
            self.table = table

        except (ClientError, BotoCoreError) as exc:
            if isinstance(exc, ClientError):
                error_code = exc.response["Error"]["Code"]
            else:
                error_code = type(exc).__name__
            if error_code == "ResourceInUseException":
                # Tabel sudah ada atau sedang dibuat — tidak perlu tindakan
                return
            raise MetadataError(
                f"Gagal membuat tabel DynamoDB '{self.config.DYNAMODB_TABLE_NAME}' "
                f"({error_code}): {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _metadata_to_item(metadata: ImageMetadata) -> dict:
        """
        Konversi dataclass ``ImageMetadata`` ke dict yang siap dikirim ke DynamoDB.

        boto3 resource API menerima Python native types secara langsung.
        Nilai ``None`` disimpan sebagai DynamoDB NULL secara otomatis.
        """
        return {
            "image_id": metadata.image_id,
            "original_filename": metadata.original_filename,
            "s3_key": metadata.s3_key,
            "file_format": metadata.file_format,
            "file_size_bytes": metadata.file_size_bytes,
            "original_width": metadata.original_width,
            "original_height": metadata.original_height,
            "final_width": metadata.final_width,
            "final_height": metadata.final_height,
            "upload_timestamp": metadata.upload_timestamp,
            "manipulations_applied": metadata.manipulations_applied,
            "watermark_text": metadata.watermark_text,
            "color_filter": metadata.color_filter,
            "output_quality": metadata.output_quality,
        }

    @staticmethod
    def _item_to_metadata(item: dict) -> ImageMetadata:
        """
        Konversi dict DynamoDB item kembali ke dataclass ``ImageMetadata``.

        DynamoDB resource mengembalikan angka sebagai ``Decimal`` —
        semua field integer di-cast kembali ke ``int``.
        Field opsional yang tidak ada di item di-default ke ``None``.
        """
        return ImageMetadata(
            image_id=item["image_id"],
            original_filename=item["original_filename"],
            s3_key=item["s3_key"],
            file_format=item["file_format"],
            file_size_bytes=int(item["file_size_bytes"]),
            original_width=int(item["original_width"]),
            original_height=int(item["original_height"]),
            final_width=int(item["final_width"]),
            final_height=int(item["final_height"]),
            upload_timestamp=item["upload_timestamp"],
            manipulations_applied=list(item.get("manipulations_applied", [])),
            watermark_text=item.get("watermark_text"),
            color_filter=item.get("color_filter"),
            output_quality=(
                int(item["output_quality"])
                if item.get("output_quality") is not None
                else None
            ),
        )

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def save_metadata(self, metadata: ImageMetadata) -> None:
        """
        Simpan metadata gambar ke DynamoDB.

        Operasi ini bersifat idempoten — jika item dengan ``image_id``
        yang sama sudah ada, item tersebut akan ditimpa sepenuhnya.

        Parameters
        ----------
        metadata:
            Objek ``ImageMetadata`` yang akan disimpan.

        Raises
        ------
        MetadataError
            Jika terjadi error boto3 saat menyimpan item.
        """
        try:
            item = self._metadata_to_item(metadata)
            self.table.put_item(Item=item)
        except (ClientError, BotoCoreError) as exc:
            if isinstance(exc, ClientError):
                error_code = exc.response["Error"]["Code"]
            else:
                error_code = type(exc).__name__
            raise MetadataError(
                f"Gagal menyimpan metadata untuk image_id '{metadata.image_id}' "
                f"({error_code}): {exc}"
            ) from exc

    def get_metadata(self, image_id: str) -> Optional[ImageMetadata]:
        """
        Ambil metadata gambar berdasarkan ID unik.

        Parameters
        ----------
        image_id:
            UUID v4 gambar yang dicari.

        Returns
        -------
        ImageMetadata | None
            Objek metadata jika ditemukan, ``None`` jika tidak ada.

        Raises
        ------
        MetadataError
            Jika terjadi error boto3 saat mengambil item.
        """
        try:
            response = self.table.get_item(Key={"image_id": image_id})
        except (ClientError, BotoCoreError) as exc:
            if isinstance(exc, ClientError):
                error_code = exc.response["Error"]["Code"]
            else:
                error_code = type(exc).__name__
            raise MetadataError(
                f"Gagal mengambil metadata untuk image_id '{image_id}' "
                f"({error_code}): {exc}"
            ) from exc

        item = response.get("Item")
        if item is None:
            return None
        return self._item_to_metadata(item)

    def list_all_metadata(self) -> list[ImageMetadata]:
        """
        Ambil semua metadata gambar dari DynamoDB via paginated scan.

        Menangani pagination secara otomatis menggunakan ``LastEvaluatedKey``
        sehingga semua item dikembalikan meskipun tabel memiliki banyak data.

        Returns
        -------
        list[ImageMetadata]
            Daftar semua metadata yang tersimpan. Kosong jika tabel kosong.

        Raises
        ------
        MetadataError
            Jika terjadi error boto3 saat melakukan scan.
        """
        items: list[dict] = []
        try:
            # Scan halaman pertama
            response = self.table.scan()
            items.extend(response.get("Items", []))

            # Lanjutkan scan selama masih ada halaman berikutnya
            while "LastEvaluatedKey" in response:
                response = self.table.scan(
                    ExclusiveStartKey=response["LastEvaluatedKey"]
                )
                items.extend(response.get("Items", []))

        except (ClientError, BotoCoreError) as exc:
            if isinstance(exc, ClientError):
                error_code = exc.response["Error"]["Code"]
            else:
                error_code = type(exc).__name__
            raise MetadataError(
                f"Gagal mengambil daftar metadata ({error_code}): {exc}"
            ) from exc

        return [self._item_to_metadata(item) for item in items]

    def update_metadata(self, image_id: str, updates: dict) -> None:
        """
        Perbarui satu atau beberapa field metadata gambar secara parsial.

        Parameters
        ----------
        image_id:
            UUID v4 gambar yang akan diperbarui.
        updates:
            Dict berisi pasangan field-name → value yang ingin diperbarui.
            Contoh: ``{"file_size_bytes": 1024, "color_filter": "sepia"}``

        Raises
        ------
        MetadataError
            Jika ``updates`` kosong atau terjadi error boto3.
        """
        if not updates:
            raise MetadataError(
                f"Tidak ada field yang diberikan untuk diperbarui pada image_id '{image_id}'."
            )

        # Bangun UpdateExpression secara dinamis dari kunci dalam updates
        set_expressions = []
        expression_attribute_names: dict = {}
        expression_attribute_values: dict = {}

        for idx, (key, value) in enumerate(updates.items()):
            placeholder_name = f"#field{idx}"
            placeholder_value = f":val{idx}"
            set_expressions.append(f"{placeholder_name} = {placeholder_value}")
            expression_attribute_names[placeholder_name] = key
            expression_attribute_values[placeholder_value] = value

        update_expression = "SET " + ", ".join(set_expressions)

        try:
            self.table.update_item(
                Key={"image_id": image_id},
                UpdateExpression=update_expression,
                ExpressionAttributeNames=expression_attribute_names,
                ExpressionAttributeValues=expression_attribute_values,
            )
        except (ClientError, BotoCoreError) as exc:
            if isinstance(exc, ClientError):
                error_code = exc.response["Error"]["Code"]
            else:
                error_code = type(exc).__name__
            raise MetadataError(
                f"Gagal memperbarui metadata untuk image_id '{image_id}' "
                f"({error_code}): {exc}"
            ) from exc

    def delete_metadata(self, image_id: str) -> None:
        """
        Hapus metadata gambar dari DynamoDB.

        Operasi ini bersifat idempoten — menghapus item yang tidak ada
        tidak akan menghasilkan error.

        Parameters
        ----------
        image_id:
            UUID v4 gambar yang akan dihapus.

        Raises
        ------
        MetadataError
            Jika terjadi error boto3 saat menghapus item.
        """
        try:
            self.table.delete_item(Key={"image_id": image_id})
        except (ClientError, BotoCoreError) as exc:
            if isinstance(exc, ClientError):
                error_code = exc.response["Error"]["Code"]
            else:
                error_code = type(exc).__name__
            raise MetadataError(
                f"Gagal menghapus metadata untuk image_id '{image_id}' "
                f"({error_code}): {exc}"
            ) from exc
